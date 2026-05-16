from __future__ import annotations

import asyncio
import platform
import socket
import subprocess
from utils.logger import get_logger

log = get_logger("vpn.interface")

_IS_WINDOWS = platform.system() == "Windows"


async def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


class InterfaceHelper:
    @staticmethod
    async def get_interface_ip(interface_name: str) -> str | None:
        if _IS_WINDOWS:
            return await InterfaceHelper._get_ip_windows(interface_name)
        return await InterfaceHelper._get_ip_unix(interface_name)

    @staticmethod
    async def _get_ip_windows(interface_name: str) -> str | None:
        code, out, err = await _run(
            ["netsh", "interface", "ip", "show", "address", interface_name]
        )
        if code != 0:
            log.debug(f"netsh failed: {err.strip()}")
            return None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("IP Address:"):
                parts = line.split(":")
                if len(parts) >= 2:
                    return parts[1].strip()
        return None

    @staticmethod
    async def _get_ip_unix(interface_name: str) -> str | None:
        code, out, err = await _run(["ip", "addr", "show", interface_name])
        if code != 0:
            log.debug(f"ip addr failed: {err.strip()}")
            return None
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet ") and "inet6" not in line:
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1].split("/")[0]
        return None

    @staticmethod
    def bind_socket_to_ip(sock: socket.socket, local_ip: str) -> None:
        sock.bind((local_ip, 0))

    @staticmethod
    async def interface_exists(interface_name: str) -> bool:
        if _IS_WINDOWS:
            code, out, _ = await _run(
                ["netsh", "interface", "show", "interface", interface_name]
            )
            return code == 0 and interface_name in out
        else:
            code, _, _ = await _run(["ip", "link", "show", interface_name])
            return code == 0
