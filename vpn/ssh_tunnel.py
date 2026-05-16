"""SSH dynamic port forwarding — creates a local SOCKS5 proxy over SSH."""
from __future__ import annotations

import asyncio
import select
import socket
import struct
import threading
from typing import Any

import paramiko

from utils.logger import get_logger

log = get_logger("vpn.ssh_tunnel")

_CHUNK = 4096


class SSHTunnel:
    """Connects to an SSH server and exposes a local SOCKS5 proxy on *local_port*."""

    def __init__(
        self,
        host: str,
        port: int = 22,
        username: str = "",
        password: str = "",
        local_socks_port: int = 9050,
    ):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._local_port = local_socks_port
        self._client: paramiko.SSHClient | None = None
        self._transport: paramiko.Transport | None = None
        self._stop = threading.Event()
        self._server_thread: threading.Thread | None = None
        self.is_connected = False
        self.interface_ip: str | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._connect_sync)

    def _connect_sync(self) -> bool:
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                self._host,
                port=self._port,
                username=self._username,
                password=self._password,
                timeout=15,
                banner_timeout=15,
                auth_timeout=15,
            )
            self._client = client
            self._transport = client.get_transport()
            self.is_connected = True
            self.interface_ip = self._host  # outbound IP is the SSH server
            log.info(f"SSH tunnel connected to {self._username}@{self._host}:{self._port}")

            self._stop.clear()
            self._server_thread = threading.Thread(
                target=self._run_socks_server, daemon=True
            )
            self._server_thread.start()
            return True
        except Exception as exc:
            log.error(f"SSH connection failed: {exc}")
            self.is_connected = False
            return False

    async def disconnect(self) -> None:
        self._stop.set()
        if self._client:
            self._client.close()
        self.is_connected = False
        log.info("SSH tunnel disconnected")

    async def get_status(self) -> dict[str, Any]:
        return {
            "type": "ssh",
            "host": self._host,
            "connected": self.is_connected,
            "local_socks_port": self._local_port,
            "interface_ip": self.interface_ip,
        }

    # ------------------------------------------------------------------
    # SOCKS5 server (runs in background thread, forwards via SSH transport)
    # ------------------------------------------------------------------

    def _run_socks_server(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", self._local_port))
        srv.listen(128)
        srv.settimeout(1.0)
        log.info(f"SSH SOCKS5 relay listening on 127.0.0.1:{self._local_port}")

        while not self._stop.is_set():
            try:
                conn, addr = srv.accept()
                t = threading.Thread(
                    target=self._handle_socks_client, args=(conn,), daemon=True
                )
                t.start()
            except socket.timeout:
                continue
            except Exception as exc:
                if not self._stop.is_set():
                    log.debug(f"SOCKS server accept error: {exc}")
        srv.close()

    def _handle_socks_client(self, sock: socket.socket) -> None:
        try:
            # --- greeting ---
            header = _recv_exact(sock, 2)
            if not header or header[0] != 0x05:
                return
            n_methods = header[1]
            _recv_exact(sock, n_methods)
            sock.sendall(b"\x05\x00")  # no-auth

            # --- request ---
            req = _recv_exact(sock, 4)
            if not req or req[1] != 0x01:
                sock.sendall(b"\x05\x07\x00\x01" + b"\x00" * 6)
                return

            atyp = req[3]
            if atyp == 0x01:
                raw = _recv_exact(sock, 4)
                dest_host = socket.inet_ntoa(raw)
            elif atyp == 0x03:
                length = _recv_exact(sock, 1)[0]
                dest_host = _recv_exact(sock, length).decode(errors="replace")
            elif atyp == 0x04:
                raw = _recv_exact(sock, 16)
                dest_host = socket.inet_ntop(socket.AF_INET6, raw)
            else:
                sock.sendall(b"\x05\x08\x00\x01" + b"\x00" * 6)
                return

            port_bytes = _recv_exact(sock, 2)
            dest_port = struct.unpack("!H", port_bytes)[0]

            # --- open SSH channel ---
            try:
                channel = self._transport.open_channel(
                    "direct-tcpip",
                    (dest_host, dest_port),
                    ("127.0.0.1", 0),
                )
            except Exception as exc:
                log.debug(f"SSH channel open failed {dest_host}:{dest_port}: {exc}")
                sock.sendall(b"\x05\x05\x00\x01" + b"\x00" * 6)
                return

            sock.sendall(b"\x05\x00\x00\x01" + b"\x00" * 4 + b"\x00\x00")
            log.debug(f"SSH tunnel → {dest_host}:{dest_port}")
            _relay_sync(sock, channel)

        except Exception as exc:
            log.debug(f"SOCKS5 client error: {exc}")
        finally:
            try:
                sock.close()
            except Exception:
                pass


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Connection closed")
        buf += chunk
    return buf


def _relay_sync(client_sock: socket.socket, channel: paramiko.Channel) -> None:
    channel.setblocking(False)
    client_sock.setblocking(False)
    try:
        while True:
            r, _, _ = select.select([client_sock, channel], [], [], 5.0)
            if client_sock in r:
                data = client_sock.recv(_CHUNK)
                if not data:
                    break
                channel.sendall(data)
            if channel in r:
                data = channel.recv(_CHUNK)
                if not data:
                    break
                client_sock.sendall(data)
    except Exception:
        pass
    finally:
        try:
            channel.close()
        except Exception:
            pass
