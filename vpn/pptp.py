"""PPTP VPN adapter — uses Windows rasdial and netsh."""
from __future__ import annotations

import asyncio
import subprocess
from typing import Any

from utils.logger import get_logger

log = get_logger("vpn.pptp")


class PPTPAdapter:
    def __init__(self, name: str, host: str, username: str, password: str):
        self._name = name
        self._host = host
        self._username = username
        self._password = password
        self.is_connected = False
        self.interface_ip: str | None = None

    async def connect(self) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._connect_sync)

    def _connect_sync(self) -> bool:
        try:
            result = subprocess.run(
                ["rasdial", self._name, self._username, self._password],
                capture_output=True, text=True, timeout=30, encoding="cp949",
            )
            if result.returncode == 0 or "연결했습니다" in result.stdout or "connected" in result.stdout.lower():
                self.interface_ip = self._get_vpn_ip()
                self.is_connected = True
                log.info(f"PPTP VPN connected: {self._name} (IP: {self.interface_ip})")
                return True
            log.error(f"rasdial failed: {result.stdout.strip()} {result.stderr.strip()}")
            return False
        except Exception as exc:
            log.error(f"PPTP connect error: {exc}")
            return False

    async def disconnect(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._disconnect_sync)

    def _disconnect_sync(self) -> None:
        try:
            subprocess.run(["rasdial", self._name, "/disconnect"], capture_output=True, timeout=15)
            self.is_connected = False
            self.interface_ip = None
            log.info(f"PPTP VPN disconnected: {self._name}")
        except Exception as exc:
            log.warning(f"PPTP disconnect error: {exc}")

    def _get_vpn_ip(self) -> str | None:
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 f"(Get-NetIPAddress -InterfaceAlias '{self._name}' -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress"],
                capture_output=True, text=True, timeout=10,
            )
            ip = result.stdout.strip()
            return ip if ip else None
        except Exception:
            return None

    async def get_status(self) -> dict[str, Any]:
        ip = self._get_vpn_ip()
        self.is_connected = ip is not None
        self.interface_ip = ip
        return {
            "type": "pptp",
            "name": self._name,
            "host": self._host,
            "connected": self.is_connected,
            "interface_ip": self.interface_ip,
        }
