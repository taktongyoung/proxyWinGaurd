"""Tests for proxy/handler.py covering all 5 Codex-review bug fixes."""
from __future__ import annotations

import asyncio
import struct
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from proxy.handler import ProxyHandler, ConnectionStats
from plugins.base import RequestContext, ResponseContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stream_reader(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


def _make_handler() -> ProxyHandler:
    return ProxyHandler(plugins=[], vpn_ip=None, auth={}, stats=ConnectionStats())


def _make_request_ctx(**kwargs) -> RequestContext:
    defaults = dict(id="test", method="GET", host="example.com", port=80, path="/", headers={})
    defaults.update(kwargs)
    return RequestContext(**defaults)


# ---------------------------------------------------------------------------
# Bug 3 — _parse_url IPv6 support
# ---------------------------------------------------------------------------

class TestParseUrl:
    def test_plain_http(self):
        host, port, path = ProxyHandler._parse_url("http://example.com/foo")
        assert host == "example.com"
        assert port == 80
        assert path == "/foo"

    def test_plain_https(self):
        host, port, path = ProxyHandler._parse_url("https://example.com:8443/bar")
        assert host == "example.com"
        assert port == 8443
        assert path == "/bar"

    def test_ipv6_with_port(self):
        host, port, path = ProxyHandler._parse_url("http://[::1]:8080/api")
        assert host == "::1"
        assert port == 8080
        assert path == "/api"

    def test_ipv6_without_port(self):
        host, port, path = ProxyHandler._parse_url("http://[::1]/")
        assert host == "::1"
        assert port == 80
        assert path == "/"

    def test_no_path(self):
        host, port, path = ProxyHandler._parse_url("http://example.com")
        assert host == "example.com"
        assert path == "/"

    def test_no_scheme(self):
        host, port, path = ProxyHandler._parse_url("example.com:9090/x")
        assert host == "example.com"
        assert port == 9090


# ---------------------------------------------------------------------------
# Bug 1 — _read_full_response reads complete response
# ---------------------------------------------------------------------------

class TestReadFullResponse:
    @pytest.mark.asyncio
    async def test_content_length(self):
        body = b"Hello, World!"
        raw = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Length: 13\r\n"
            b"\r\n" + body
        )
        reader = _make_stream_reader(raw)
        result = await ProxyHandler._read_full_response(reader)
        assert result.endswith(body)
        assert b"HTTP/1.1 200 OK" in result

    @pytest.mark.asyncio
    async def test_content_length_large(self):
        body = b"X" * 200_000
        raw = (
            f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        reader = _make_stream_reader(raw)
        result = await ProxyHandler._read_full_response(reader)
        assert result.endswith(body)

    @pytest.mark.asyncio
    async def test_chunked(self):
        raw = (
            b"HTTP/1.1 200 OK\r\n"
            b"Transfer-Encoding: chunked\r\n"
            b"\r\n"
            b"5\r\nHello\r\n"
            b"6\r\nWorld!\r\n"
            b"0\r\n\r\n"
        )
        reader = _make_stream_reader(raw)
        result = await ProxyHandler._read_full_response(reader)
        assert b"Hello" in result
        assert b"World!" in result

    @pytest.mark.asyncio
    async def test_eof_fallback(self):
        body = b"no content-length here"
        raw = b"HTTP/1.1 200 OK\r\n\r\n" + body
        reader = _make_stream_reader(raw)
        result = await ProxyHandler._read_full_response(reader)
        assert result.endswith(body)

    @pytest.mark.asyncio
    async def test_empty_body(self):
        raw = b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n\r\n"
        reader = _make_stream_reader(raw)
        result = await ProxyHandler._read_full_response(reader)
        assert b"204 No Content" in result


# ---------------------------------------------------------------------------
# Bug 2 — _rebuild_response reflects plugin modifications
# ---------------------------------------------------------------------------

class TestRebuildResponse:
    def test_basic(self):
        req = _make_request_ctx()
        ctx = ResponseContext(
            request=req, status_code=200,
            headers={"content-type": "text/plain"},
            body=b"Hello",
        )
        out = ProxyHandler._rebuild_response(ctx)
        assert b"HTTP/1.1 200 OK" in out
        assert b"content-type: text/plain" in out
        assert b"Hello" in out

    def test_content_length_recalculated(self):
        req = _make_request_ctx()
        ctx = ResponseContext(
            request=req, status_code=200,
            headers={"content-length": "999"},  # wrong — plugin changed body
            body=b"short",
        )
        out = ProxyHandler._rebuild_response(ctx)
        assert b"content-length: 5" in out

    def test_plugin_modified_status_code(self):
        req = _make_request_ctx()
        ctx = ResponseContext(
            request=req, status_code=403,
            headers={}, body=b"Forbidden",
        )
        out = ProxyHandler._rebuild_response(ctx)
        assert b"HTTP/1.1 403 OK" in out
        assert b"Forbidden" in out

    def test_plugin_modified_body_propagates(self):
        req = _make_request_ctx()
        original_body = b"original content"
        modified_body = b"MODIFIED by plugin"
        ctx = ResponseContext(
            request=req, status_code=200,
            headers={"content-length": str(len(original_body))},
            body=modified_body,
        )
        out = ProxyHandler._rebuild_response(ctx)
        assert b"MODIFIED by plugin" in out
        assert b"original content" not in out
        # content-length must match modified body
        assert f"content-length: {len(modified_body)}".encode() in out

    def test_empty_body_removes_content_length(self):
        req = _make_request_ctx()
        ctx = ResponseContext(
            request=req, status_code=204,
            headers={"content-length": "100"},
            body=b"",
        )
        out = ProxyHandler._rebuild_response(ctx)
        assert b"content-length" not in out


# ---------------------------------------------------------------------------
# Bug 4 — SOCKS5 subnegotiation version check (RFC 1929)
# ---------------------------------------------------------------------------

class _FakeReader:
    """Feeds bytes sequentially via readexactly()."""
    def __init__(self, data: bytes):
        self._buf = bytearray(data)

    async def readexactly(self, n: int) -> bytes:
        if len(self._buf) < n:
            raise asyncio.IncompleteReadError(bytes(self._buf), n)
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    async def read(self, n: int = -1) -> bytes:
        if not self._buf:
            return b""
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out


class _FakeWriter:
    def __init__(self):
        self.written = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.written.extend(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        pass


class TestSocks5Auth:
    @pytest.mark.asyncio
    async def test_valid_version_correct_credentials(self):
        handler = ProxyHandler(
            plugins=[], vpn_ip=None,
            auth={"enabled": True, "username": "user", "password": "pass"},
            stats=ConnectionStats(),
        )
        # ver=1, ulen=4, "user", plen=4, "pass"
        payload = bytes([0x01, 4]) + b"user" + bytes([4]) + b"pass"
        reader = _FakeReader(payload)
        writer = _FakeWriter()
        result = await handler._socks5_authenticate(reader, writer)
        assert result is True
        assert writer.written == b"\x01\x00"

    @pytest.mark.asyncio
    async def test_valid_version_wrong_credentials(self):
        handler = ProxyHandler(
            plugins=[], vpn_ip=None,
            auth={"enabled": True, "username": "user", "password": "pass"},
            stats=ConnectionStats(),
        )
        payload = bytes([0x01, 4]) + b"user" + bytes([5]) + b"wrong"
        reader = _FakeReader(payload)
        writer = _FakeWriter()
        result = await handler._socks5_authenticate(reader, writer)
        assert result is False
        assert writer.written == b"\x01\x01"

    @pytest.mark.asyncio
    async def test_invalid_subnegotiation_version_rejected(self):
        """Bug 4: version != 0x01 must be rejected immediately."""
        handler = ProxyHandler(
            plugins=[], vpn_ip=None,
            auth={"enabled": True, "username": "user", "password": "pass"},
            stats=ConnectionStats(),
        )
        # ver=0x05 (wrong — should be 0x01)
        payload = bytes([0x05, 4]) + b"user" + bytes([4]) + b"pass"
        reader = _FakeReader(payload)
        writer = _FakeWriter()
        result = await handler._socks5_authenticate(reader, writer)
        assert result is False
        assert writer.written == b"\x01\x01"


# ---------------------------------------------------------------------------
# Bug 5 — wait_closed() is called (integration-style check via mock)
# ---------------------------------------------------------------------------

class TestWaitClosed:
    @pytest.mark.asyncio
    async def test_wait_closed_called_on_remote_writer(self):
        handler = _make_handler()

        raw_response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"
        remote_reader = _make_stream_reader(raw_response)

        remote_writer = MagicMock()
        remote_writer.write = MagicMock()
        remote_writer.drain = AsyncMock()
        remote_writer.close = MagicMock()
        remote_writer.wait_closed = AsyncMock()

        client_writer = MagicMock()
        client_writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 9999))
        client_writer.write = MagicMock()
        client_writer.drain = AsyncMock()
        client_writer.close = MagicMock()
        client_writer.wait_closed = AsyncMock()

        raw_head = b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n"

        with patch("proxy.handler.open_tunnel", return_value=(remote_reader, remote_writer)):
            await handler.handle_http(
                reader=_make_stream_reader(b""),
                writer=client_writer,
                first_line="GET http://example.com/ HTTP/1.1",
                headers={"host": "example.com"},
                raw_head=raw_head,
            )

        remote_writer.wait_closed.assert_awaited_once()
        client_writer.wait_closed.assert_awaited_once()
