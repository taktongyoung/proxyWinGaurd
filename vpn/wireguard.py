from __future__ import annotations

import asyncio
import os
import platform
import re
from pathlib import Path
from typing import Any

from utils.logger import get_logger
from .interface import InterfaceHelper

log = get_logger("vpn.wireguard")

_IS_WINDOWS = platform.system() == "Windows"


async def _run(cmd: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"Command timed out: {' '.join(cmd)}")
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


class WireGuardAdapter:
    def __init__(self, config_file: str, interface: str = "wg0"):
        self.config_file = Path(config_file)
        self.interface = interface
        self._interface_ip: str | None = None
        self._connected = False

    @property
    def interface_ip(self) -> str | None:
        return self._interface_ip

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _parse_address_from_config(self) -> str | None:
        if not self.config_file.exists():
            return None
        text = self.config_file.read_text(encoding="utf-8")
        match = re.search(r"^\s*Address\s*=\s*([0-9./]+)", text, re.MULTILINE | re.IGNORECASE)
        if match:
            return match.group(1).split("/")[0]
        return None

    async def connect(self) -> bool:
        if not self.config_file.exists():
            log.error(f"WireGuard config not found: {self.config_file}")
            return False

        log.info(f"Bringing up WireGuard interface [vpn]{self.interface}[/vpn]")

        if _IS_WINDOWS:
            ok = await self._connect_windows()
        else:
            ok = await self._connect_unix()

        if ok:
            self._interface_ip = await self._resolve_ip()
            self._connected = True
            log.info(f"WireGuard up. Interface IP: [vpn]{self._interface_ip}[/vpn]")

        return ok

    async def _connect_windows(self) -> bool:
        wg_exe = self._find_wireguard_exe()
        if not wg_exe:
            log.error("WireGuard.exe not found. Install WireGuard from wireguard.com")
            return False

        code, out, err = await _run(
            [wg_exe, "/installtunnelservice", str(self.config_file.resolve())],
            timeout=60,
        )
        if code != 0:
            log.warning(f"installtunnelservice: {err.strip()} — trying wg-quick fallback")
            return await self._connect_windows_wgquick()
        return True

    async def _connect_windows_wgquick(self) -> bool:
        code, out, err = await _run(
            ["wg-quick", "up", str(self.config_file.resolve())],
            timeout=60,
        )
        if code != 0:
            log.error(f"wg-quick up failed: {err.strip()}")
            return False
        return True

    async def _connect_unix(self) -> bool:
        code, out, err = await _run(
            ["wg-quick", "up", str(self.config_file.resolve())],
            timeout=60,
        )
        if code != 0:
            log.error(f"wg-quick up failed: {err.strip()}")
            return False
        return True

    async def disconnect(self) -> bool:
        log.info(f"Bringing down WireGuard interface [vpn]{self.interface}[/vpn]")

        if _IS_WINDOWS:
            ok = await self._disconnect_windows()
        else:
            ok = await self._disconnect_unix()

        if ok:
            self._connected = False
            self._interface_ip = None

        return ok

    async def _disconnect_windows(self) -> bool:
        wg_exe = self._find_wireguard_exe()
        if wg_exe:
            code, out, err = await _run(
                [wg_exe, "/uninstalltunnelservice", self.interface], timeout=30
            )
            if code == 0:
                return True
            log.warning(f"uninstalltunnelservice failed: {err.strip()} — trying wg-quick")

        code, out, err = await _run(
            ["wg-quick", "down", str(self.config_file.resolve())], timeout=30
        )
        if code != 0:
            log.error(f"wg-quick down failed: {err.strip()}")
            return False
        return True

    async def _disconnect_unix(self) -> bool:
        code, out, err = await _run(
            ["wg-quick", "down", str(self.config_file.resolve())], timeout=30
        )
        if code != 0:
            log.error(f"wg-quick down failed: {err.strip()}")
            return False
        return True

    async def _resolve_ip(self) -> str | None:
        ip = await InterfaceHelper.get_interface_ip(self.interface)
        if not ip:
            ip = self._parse_address_from_config()
        return ip

    async def get_status(self) -> dict[str, Any]:
        if not self._connected:
            return {"connected": False, "interface": self.interface}

        code, out, err = await _run(["wg", "show", self.interface], timeout=10)
        stats: dict[str, Any] = {
            "connected": self._connected,
            "interface": self.interface,
            "ip": self._interface_ip,
        }
        if code == 0:
            stats["wg_output"] = out.strip()
        return stats

    @staticmethod
    def _find_wireguard_exe() -> str | None:
        candidates = [
            r"C:\Program Files\WireGuard\wireguard.exe",
            r"C:\Program Files (x86)\WireGuard\wireguard.exe",
        ]
        for path in candidates:
            if Path(path).exists():
                return path
        return None
