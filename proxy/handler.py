from __future__ import annotations

import asyncio
import socket
import struct
import time
import uuid
from typing import Any, Protocol, runtime_checkable

from plugins.base import ProxyPlugin, RequestContext, ResponseContext
from utils.logger import get_logger
from .tunnel import open_tunnel, relay


@runtime_checkable
class StreamReaderLike(Protocol):
    async def readexactly(self, n: int) -> bytes: ...
    async def read(self, n: int = -1) -> bytes: ...

log = get_logger("proxy.handler")

SOCKS5_VERSION = 0x05
SOCKS5_NO_AUTH = 0x00
SOCKS5_USER_PASS = 0x02
SOCKS5_NO_ACCEPTABLE = 0xFF
SOCKS5_CMD_CONNECT = 0x01
SOCKS5_ATYP_IPV4 = 0x01
SOCKS5_ATYP_DOMAIN = 0x03
SOCKS5_ATYP_IPV6 = 0x04


class ConnectionStats:
    def __init__(self):
        self.active: dict[str, dict] = {}
        self.total_requests = 0
        self.total_bytes_sent = 0
        self.total_bytes_recv = 0


class ProxyHandler:
    def __init__(
        self,
        plugins: list[ProxyPlugin],
        vpn_ip: str | None,
        auth: dict | None,
        stats: ConnectionStats,
    ):
        self._plugins = plugins
        self._vpn_ip = vpn_ip
        self._auth = auth or {}
        self._stats = stats

    async def handle_http(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        first_line: str,
        headers: dict[str, str],
        raw_head: bytes,
    ) -> None:
        parts = first_line.split(" ", 2)
        if len(parts) < 2:
            writer.close()
            return

        method = parts[0].upper()
        url = parts[1]
        conn_id = str(uuid.uuid4())[:8]

        host, port, path = self._parse_url(url)
        if not host:
            writer.close()
            return

        ctx = RequestContext(
            id=conn_id,
            method=method,
            host=host,
            port=port,
            path=path,
            headers=headers,
            client_addr=writer.get_extra_info("peername", ("", 0)),
        )

        ctx = await self._run_request_plugins(ctx)
        if ctx is None:
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()
            return

        self._stats.total_requests += 1
        self._stats.active[conn_id] = {"host": host, "port": port, "method": method}

        try:
            remote_reader, remote_writer = await open_tunnel(host, port, self._vpn_ip)
        except Exception as e:
            log.warning(f"[{conn_id}] Failed to connect to {host}:{port}: {e}")
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()
            self._stats.active.pop(conn_id, None)
            return

        try:
            rebuilt = self._rebuild_request(method, path, headers, raw_head)
            remote_writer.write(rebuilt)
            await remote_writer.drain()

            # Forward any remaining request body not captured in the initial read
            await self._pipe_remaining_body(reader, remote_writer, headers, raw_head)

            # Bug 1 fix: read full response, not just first 65 KB
            response_data = await self._read_full_response(remote_reader)
            status_code, resp_headers, resp_body = self._parse_response(response_data)

            resp_ctx = ResponseContext(
                request=ctx,
                status_code=status_code,
                headers=resp_headers,
                body=resp_body,
            )
            resp_ctx = await self._run_response_plugins(resp_ctx)
            if resp_ctx is not None:
                # Bug 2 fix: send the (possibly plugin-modified) response, not raw bytes
                out = self._rebuild_response(resp_ctx)
                writer.write(out)
                await writer.drain()

            self._stats.total_bytes_sent += len(rebuilt)
            self._stats.total_bytes_recv += len(response_data)
        except Exception as e:
            log.debug(f"[{conn_id}] HTTP relay error: {e}")
        finally:
            remote_writer.close()
            try:
                await remote_writer.wait_closed()
            except Exception:
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            self._stats.active.pop(conn_id, None)

    async def handle_connect(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        first_line: str,
    ) -> None:
        parts = first_line.split(" ", 2)
        if len(parts) < 2:
            writer.close()
            return

        host_port = parts[1]
        conn_id = str(uuid.uuid4())[:8]

        try:
            host, port_str = host_port.rsplit(":", 1)
            port = int(port_str)
        except ValueError:
            writer.close()
            return

        allowed = await self._run_connect_plugins(host, port)
        if not allowed:
            writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            await writer.drain()
            writer.close()
            return

        self._stats.active[conn_id] = {"host": host, "port": port, "method": "CONNECT"}
        self._stats.total_requests += 1

        try:
            remote_reader, remote_writer = await open_tunnel(host, port, self._vpn_ip)
        except Exception as e:
            log.warning(f"[{conn_id}] CONNECT to {host}:{port} failed: {e}")
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            await writer.drain()
            writer.close()
            self._stats.active.pop(conn_id, None)
            return

        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()

        log.debug(f"[{conn_id}] CONNECT tunnel: {host}:{port}")
        byte_stats: dict = {}
        try:
            await relay(reader, writer, remote_reader, remote_writer, byte_stats)
        finally:
            self._stats.total_bytes_sent += byte_stats.get("bytes_sent", 0)
            self._stats.total_bytes_recv += byte_stats.get("bytes_recv", 0)
            self._stats.active.pop(conn_id, None)

    async def handle_socks5(
        self,
        reader: StreamReaderLike,
        writer: asyncio.StreamWriter,
    ) -> None:
        conn_id = str(uuid.uuid4())[:8]

        try:
            header = await reader.readexactly(2)
            n_methods = header[1]
            methods = await reader.readexactly(n_methods)

            use_auth = (
                self._auth.get("enabled")
                and self._auth.get("username")
                and SOCKS5_USER_PASS in methods
            )

            if use_auth:
                writer.write(bytes([SOCKS5_VERSION, SOCKS5_USER_PASS]))
                await writer.drain()
                if not await self._socks5_authenticate(reader, writer):
                    return
            elif SOCKS5_NO_AUTH in methods:
                writer.write(bytes([SOCKS5_VERSION, SOCKS5_NO_AUTH]))
                await writer.drain()
            else:
                writer.write(bytes([SOCKS5_VERSION, SOCKS5_NO_ACCEPTABLE]))
                await writer.drain()
                return

            req = await reader.readexactly(4)
            if req[1] != SOCKS5_CMD_CONNECT:
                writer.write(b"\x05\x07\x00\x01" + b"\x00" * 6)
                await writer.drain()
                return

            atyp = req[3]
            host, port = await self._socks5_read_address(reader, atyp)
            if not host:
                return

            allowed = await self._run_connect_plugins(host, port)
            if not allowed:
                writer.write(b"\x05\x02\x00\x01" + b"\x00" * 6)
                await writer.drain()
                return

            self._stats.active[conn_id] = {"host": host, "port": port, "method": "SOCKS5"}
            self._stats.total_requests += 1

            try:
                remote_reader, remote_writer = await open_tunnel(host, port, self._vpn_ip)
            except Exception as e:
                log.warning(f"[{conn_id}] SOCKS5 connect {host}:{port} failed: {e}")
                writer.write(b"\x05\x04\x00\x01" + b"\x00" * 6)
                await writer.drain()
                return

            writer.write(b"\x05\x00\x00\x01" + b"\x00" * 4 + b"\x00\x00")
            await writer.drain()

            log.debug(f"[{conn_id}] SOCKS5 tunnel: {host}:{port}")
            byte_stats: dict = {}
            try:
                await relay(reader, writer, remote_reader, remote_writer, byte_stats)
            finally:
                self._stats.total_bytes_sent += byte_stats.get("bytes_sent", 0)
                self._stats.total_bytes_recv += byte_stats.get("bytes_recv", 0)
                self._stats.active.pop(conn_id, None)

        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        except Exception as e:
            log.debug(f"[{conn_id}] SOCKS5 error: {e}")
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _socks5_authenticate(
        self, reader: StreamReaderLike, writer: asyncio.StreamWriter
    ) -> bool:
        # Bug 4 fix: verify subnegotiation version per RFC 1929
        ver = (await reader.readexactly(1))[0]
        if ver != 0x01:
            writer.write(b"\x01\x01")
            await writer.drain()
            return False
        ulen = (await reader.readexactly(1))[0]
        username = (await reader.readexactly(ulen)).decode(errors="replace")
        plen = (await reader.readexactly(1))[0]
        password = (await reader.readexactly(plen)).decode(errors="replace")

        ok = (
            username == self._auth.get("username")
            and password == self._auth.get("password")
        )
        writer.write(b"\x01\x00" if ok else b"\x01\x01")
        await writer.drain()
        return ok

    @staticmethod
    async def _socks5_read_address(
        reader: StreamReaderLike, atyp: int
    ) -> tuple[str, int]:
        if atyp == SOCKS5_ATYP_IPV4:
            raw = await reader.readexactly(4)
            host = socket.inet_ntoa(raw)
        elif atyp == SOCKS5_ATYP_DOMAIN:
            length = (await reader.readexactly(1))[0]
            host = (await reader.readexactly(length)).decode(errors="replace")
        elif atyp == SOCKS5_ATYP_IPV6:
            raw = await reader.readexactly(16)
            host = socket.inet_ntop(socket.AF_INET6, raw)
        else:
            return "", 0
        port_bytes = await reader.readexactly(2)
        port = struct.unpack("!H", port_bytes)[0]
        return host, port

    @staticmethod
    def _parse_url(url: str) -> tuple[str, int, str]:
        if url.startswith("http://"):
            url = url[7:]
            default_port = 80
        elif url.startswith("https://"):
            url = url[8:]
            default_port = 443
        else:
            default_port = 80

        slash = url.find("/")
        if slash == -1:
            host_part = url
            path = "/"
        else:
            host_part = url[:slash]
            path = url[slash:]

        # Bug 3 fix: handle IPv6 literal addresses like [::1]:8080
        if host_part.startswith("["):
            bracket_end = host_part.find("]")
            if bracket_end != -1:
                host = host_part[1:bracket_end]
                rest = host_part[bracket_end + 1:]
                port = default_port
                if rest.startswith(":"):
                    try:
                        port = int(rest[1:])
                    except ValueError:
                        pass
            else:
                host = host_part
                port = default_port
        elif ":" in host_part:
            host, port_str = host_part.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = default_port
        else:
            host = host_part
            port = default_port

        return host, port, path

    @staticmethod
    async def _read_full_response(reader: asyncio.StreamReader) -> bytes:
        """Read a complete HTTP response, honouring Content-Length and chunked encoding."""
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = await reader.read(4096)
            if not chunk:
                return buf
            buf += chunk

        header_end = buf.index(b"\r\n\r\n")
        header_section = buf[:header_end]
        body_buf = buf[header_end + 4:]

        content_length: int | None = None
        is_chunked = False
        for line in header_section.decode(errors="replace").splitlines()[1:]:
            if ":" in line:
                k, _, v = line.partition(":")
                k, v = k.strip().lower(), v.strip()
                if k == "content-length":
                    try:
                        content_length = int(v)
                    except ValueError:
                        pass
                elif k == "transfer-encoding" and "chunked" in v.lower():
                    is_chunked = True

        prefix = header_section + b"\r\n\r\n"

        if content_length is not None:
            remaining = content_length - len(body_buf)
            if remaining > 0:
                body_buf += await reader.readexactly(remaining)
            return prefix + body_buf[:content_length]

        if is_chunked:
            while not body_buf.endswith(b"0\r\n\r\n"):
                chunk = await reader.read(65536)
                if not chunk:
                    break
                body_buf += chunk
            return prefix + body_buf

        # Connection: close — read until EOF
        while True:
            chunk = await reader.read(65536)
            if not chunk:
                break
            body_buf += chunk
        return prefix + body_buf

    @staticmethod
    def _rebuild_response(ctx: ResponseContext) -> bytes:
        """Reconstruct HTTP response bytes from a (plugin-modified) ResponseContext."""
        status_line = f"HTTP/1.1 {ctx.status_code} OK\r\n"
        # Update Content-Length to match actual body after plugin changes
        headers = dict(ctx.headers)
        if ctx.body:
            headers["content-length"] = str(len(ctx.body))
        elif "content-length" in headers:
            del headers["content-length"]
        header_block = "\r\n".join(f"{k}: {v}" for k, v in headers.items())
        return f"{status_line}{header_block}\r\n\r\n".encode() + ctx.body

    @staticmethod
    def _parse_response(data: bytes) -> tuple[int, dict[str, str], bytes]:
        try:
            header_end = data.find(b"\r\n\r\n")
            if header_end == -1:
                return 200, {}, data
            header_bytes = data[:header_end]
            body = data[header_end + 4:]
            lines = header_bytes.decode(errors="replace").splitlines()
            status_code = 200
            if lines:
                parts = lines[0].split(" ", 2)
                if len(parts) >= 2:
                    try:
                        status_code = int(parts[1])
                    except ValueError:
                        pass
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            return status_code, headers, body
        except Exception:
            return 200, {}, data

    @staticmethod
    async def _pipe_remaining_body(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        headers: dict[str, str],
        raw_head: bytes,
    ) -> None:
        """Stream request body bytes that didn't fit in the initial raw_head read."""
        try:
            content_length = int(headers.get("content-length", 0))
        except ValueError:
            return
        if content_length <= 0:
            return
        header_end = raw_head.find(b"\r\n\r\n")
        already_sent = len(raw_head) - (header_end + 4) if header_end != -1 else 0
        remaining = content_length - already_sent
        while remaining > 0:
            chunk = await reader.read(min(remaining, 65536))
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
            remaining -= len(chunk)

    @staticmethod
    def _rebuild_request(method: str, path: str, headers: dict[str, str], raw: bytes) -> bytes:
        first_line = f"{method} {path} HTTP/1.1\r\n"
        header_lines = "\r\n".join(f"{k}: {v}" for k, v in headers.items())
        rebuilt = f"{first_line}{header_lines}\r\n\r\n".encode()
        header_end = raw.find(b"\r\n\r\n")
        if header_end != -1:
            body = raw[header_end + 4:]
            rebuilt += body
        return rebuilt

    async def _run_request_plugins(self, ctx: RequestContext) -> RequestContext | None:
        for plugin in self._plugins:
            if not plugin.enabled:
                continue
            try:
                result = await plugin.on_request(ctx)
                if result is None:
                    return None
                ctx = result
            except Exception as e:
                log.warning(f"Plugin {plugin.name} on_request error: {e}")
        return ctx

    async def _run_response_plugins(self, ctx: ResponseContext) -> ResponseContext | None:
        for plugin in self._plugins:
            if not plugin.enabled:
                continue
            try:
                result = await plugin.on_response(ctx)
                if result is None:
                    return None
                ctx = result
            except Exception as e:
                log.warning(f"Plugin {plugin.name} on_response error: {e}")
        return ctx

    async def _run_connect_plugins(self, host: str, port: int) -> bool:
        for plugin in self._plugins:
            if not plugin.enabled:
                continue
            try:
                allowed = await plugin.on_connect(host, port)
                if not allowed:
                    return False
            except Exception as e:
                log.warning(f"Plugin {plugin.name} on_connect error: {e}")
        return True
