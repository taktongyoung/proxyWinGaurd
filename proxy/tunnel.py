from __future__ import annotations

import asyncio
import socket
from typing import Any

from utils.logger import get_logger

log = get_logger("proxy.tunnel")

CHUNK = 65536


async def open_tunnel(
    host: str,
    port: int,
    local_ip: str | None = None,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
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
