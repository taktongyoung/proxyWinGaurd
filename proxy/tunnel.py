from __future__ import annotations

import asyncio
import socket
import struct
from typing import Any

from utils.logger import get_logger

log = get_logger("proxy.tunnel")

CHUNK = 65536

# Set by VPNManager when an SSH tunnel is active
upstream_socks5: tuple[str, int] | None = None


async def open_tunnel(
    host: str,
    port: int,
    local_ip: str | None = None,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    # SSH tunnel takes priority over local_ip binding
    if upstream_socks5:
        return await _connect_via_socks5(host, port, *upstream_socks5)

    if local_ip:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((local_ip, 0))
            sock.setblocking(False)
            loop = asyncio.get_running_loop()
            await loop.sock_connect(sock, (host, port))
            reader, writer = await asyncio.open_connection(sock=sock)
        except OSError as e:
            log.warning(f"Cannot bind/connect via {local_ip}: {e}. Using default interface.")
            try:
                sock.close()
            except Exception:
                pass
            reader, writer = await asyncio.open_connection(host, port)
    else:
        reader, writer = await asyncio.open_connection(host, port)

    return reader, writer


async def _connect_via_socks5(
    host: str, port: int, socks_host: str, socks_port: int
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection(socks_host, socks_port)
    try:
        writer.write(b"\x05\x01\x00")
        await writer.drain()
        resp = await reader.readexactly(2)
        if resp[1] != 0x00:
            raise ConnectionError("SOCKS5 auth negotiation failed")

        host_bytes = host.encode()
        writer.write(
            bytes([0x05, 0x01, 0x00, 0x03, len(host_bytes)])
            + host_bytes
            + struct.pack("!H", port)
        )
        await writer.drain()

        resp = await reader.readexactly(4)
        if resp[1] != 0x00:
            raise ConnectionError(f"SOCKS5 CONNECT failed: code {resp[1]}")

        atyp = resp[3]
        if atyp == 0x01:
            await reader.readexactly(4)
        elif atyp == 0x03:
            length = (await reader.readexactly(1))[0]
            await reader.readexactly(length)
        elif atyp == 0x04:
            await reader.readexactly(16)
        await reader.readexactly(2)

        return reader, writer
    except Exception:
        writer.close()
        raise


async def relay(
    client_reader: Any,
    client_writer: asyncio.StreamWriter,
    remote_reader: asyncio.StreamReader,
    remote_writer: asyncio.StreamWriter,
    stats: dict,
) -> None:
    async def forward(src: Any, dst: asyncio.StreamWriter, key: str) -> None:
        try:
            while True:
                data = await src.read(CHUNK)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
                stats[key] = stats.get(key, 0) + len(data)
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            try:
                dst.close()
                await dst.wait_closed()
            except Exception:
                pass

    await asyncio.gather(
        forward(client_reader, remote_writer, "bytes_sent"),
        forward(remote_reader, client_writer, "bytes_recv"),
        return_exceptions=True,
    )
