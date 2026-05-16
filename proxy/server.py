from __future__ import annotations

import asyncio
from typing import Any

from plugins.base import ProxyPlugin
from utils.logger import get_logger
from .handler import ProxyHandler, ConnectionStats

log = get_logger("proxy.server")

_MAX_HEADER_SIZE = 65536


class ProxyServer:
    def __init__(self, config: dict, plugins: list[ProxyPlugin], vpn_ip: str | None):
        proxy_cfg = config.get("proxy", {})
        self._host: str = proxy_cfg.get("host", "127.0.0.1")
        self._http_port: int = proxy_cfg.get("port", 8080)
        self._socks5_port: int = proxy_cfg.get("socks5_port", 1080)
        self._auth: dict = proxy_cfg.get("auth", {})
        self._plugins = plugins
        self._vpn_ip = vpn_ip
        self._stats = ConnectionStats()
        self._handler = ProxyHandler(plugins, vpn_ip, self._auth, self._stats)
        self._http_server: asyncio.Server | None = None
        self._socks5_server: asyncio.Server | None = None

        ac = config.get("access_control", {})
        raw_ips = ac.get("allowed_ips", ["127.0.0.1"])
        self._allowed_ips: set[str] = set(raw_ips)

    @property
    def stats(self) -> ConnectionStats:
        return self._stats

    @property
    def allowed_ips(self) -> list[str]:
        return sorted(self._allowed_ips)

    def add_allowed_ip(self, ip: str) -> None:
        self._allowed_ips.add(ip)
        log.info(f"Allowed IP added: {ip}")

    def remove_allowed_ip(self, ip: str) -> None:
        self._allowed_ips.discard(ip)
        log.info(f"Allowed IP removed: {ip}")

    def _is_allowed(self, ip: str) -> bool:
        if not self._allowed_ips:
            return True
        return ip in self._allowed_ips

    def update_vpn_ip(self, ip: str | None) -> None:
        self._vpn_ip = ip
        self._handler._vpn_ip = ip

    async def start(self) -> None:
        self._http_server = await asyncio.start_server(
            self._handle_http_client,
            self._host,
            self._http_port,
        )
        self._socks5_server = await asyncio.start_server(
            self._handle_socks5_client,
            self._host,
            self._socks5_port,
        )

        log.info(f"HTTP/HTTPS proxy listening on [proxy]{self._host}:{self._http_port}[/proxy]")
        log.info(f"SOCKS5 proxy listening on [proxy]{self._host}:{self._socks5_port}[/proxy]")

        await asyncio.gather(
            self._http_server.serve_forever(),
            self._socks5_server.serve_forever(),
        )

    async def stop(self) -> None:
        if self._http_server:
            self._http_server.close()
            await self._http_server.wait_closed()
        if self._socks5_server:
            self._socks5_server.close()
            await self._socks5_server.wait_closed()

    async def _handle_http_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            peer_ip = writer.get_extra_info("peername", ("", 0))[0]
            if not self._is_allowed(peer_ip):
                log.warning(f"Blocked HTTP connection from {peer_ip}")
                writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return

            raw_head = await reader.read(_MAX_HEADER_SIZE)
            if not raw_head:
                return

            headers_text, _, _ = raw_head.partition(b"\r\n\r\n")
            lines = headers_text.decode(errors="replace").splitlines()
            if not lines:
                return

            first_line = lines[0]
            headers: dict[str, str] = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()

            if first_line.startswith("CONNECT "):
                await self._handler.handle_connect(reader, writer, first_line)
            else:
                await self._handler.handle_http(reader, writer, first_line, headers, raw_head)

        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            log.debug(f"HTTP client error: {e}")
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _handle_socks5_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            peer_ip = writer.get_extra_info("peername", ("", 0))[0]
            if not self._is_allowed(peer_ip):
                log.warning(f"Blocked SOCKS5 connection from {peer_ip}")
                return

            version_byte = await reader.readexactly(1)
            if version_byte[0] != 0x05:
                log.debug(f"Non-SOCKS5 byte: {version_byte!r}")
                return
            # Push the version byte back by prepending to a new reader
            # We reconstruct by passing directly to the handler with the byte already consumed
            await self._handler.handle_socks5(
                _PrefixedReader(version_byte, reader), writer
            )
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        except Exception as e:
            log.debug(f"SOCKS5 client error: {e}")
        finally:
            try:
                writer.close()
            except Exception:
                pass


class _PrefixedReader:
    """Wraps an asyncio.StreamReader, prepending already-read bytes."""

    def __init__(self, prefix: bytes, reader: asyncio.StreamReader):
        self._prefix = bytearray(prefix)
        self._reader = reader

    async def readexactly(self, n: int) -> bytes:
        result = bytearray()
        if self._prefix:
            take = min(n, len(self._prefix))
            result.extend(self._prefix[:take])
            del self._prefix[:take]
            n -= take
        if n > 0:
            result.extend(await self._reader.readexactly(n))
        return bytes(result)

    async def read(self, n: int = -1) -> bytes:
        if self._prefix:
            data = bytes(self._prefix)
            self._prefix = bytearray()
            return data
        return await self._reader.read(n)
