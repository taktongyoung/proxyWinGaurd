from __future__ import annotations

import asyncio
from typing import Any

from utils.logger import get_logger
from .wireguard import WireGuardAdapter

log = get_logger("vpn.manager")


class VPNManager:
    def __init__(self, config: dict):
        vpn_cfg = config.get("vpn", {})
        self._adapter = WireGuardAdapter(
            config_file=vpn_cfg.get("config_file", "wg0.conf"),
            interface=vpn_cfg.get("interface", "wg0"),
        )
        self._auto_connect: bool = vpn_cfg.get("auto_connect", True)
        self._health_task: asyncio.Task | None = None

    @property
    def interface_ip(self) -> str | None:
        return self._adapter.interface_ip

    @property
    def is_connected(self) -> bool:
        return self._adapter.is_connected

    async def start(self) -> bool:
        if not self._auto_connect:
            log.info("VPN auto-connect disabled, skipping")
            return True

        ok = await self._adapter.connect()
        if ok:
            self._health_task = asyncio.create_task(self._health_monitor())
        return ok

    async def stop(self) -> None:
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        if self._adapter.is_connected:
            await self._adapter.disconnect()

    async def get_status(self) -> dict[str, Any]:
        return await self._adapter.get_status()

    async def _health_monitor(self) -> None:
        while True:
            await asyncio.sleep(30)
            if not self._adapter.is_connected:
                log.warning("[warn]VPN disconnected, attempting reconnect...[/warn]")
                await self._adapter.connect()
