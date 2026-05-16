from __future__ import annotations

import asyncio
from typing import Any

from utils.logger import get_logger

log = get_logger("vpn.manager")


class VPNManager:
    def __init__(self, config: dict):
        vpn_cfg = config.get("vpn", {})
        vpn_type = vpn_cfg.get("type", "wireguard")

        if vpn_type == "ssh":
            from .ssh_tunnel import SSHTunnel
            self._adapter = SSHTunnel(
                host=vpn_cfg.get("host", ""),
                port=vpn_cfg.get("port", 22),
                username=vpn_cfg.get("username", ""),
                password=vpn_cfg.get("password", ""),
                local_socks_port=vpn_cfg.get("local_socks_port", 9050),
            )
        elif vpn_type == "pptp":
            from .pptp import PPTPAdapter
            self._adapter = PPTPAdapter(
                name=vpn_cfg.get("name", "autoproxy-pptp"),
                host=vpn_cfg.get("host", ""),
                username=vpn_cfg.get("username", ""),
                password=vpn_cfg.get("password", ""),
            )
        else:
            from .wireguard import WireGuardAdapter
            self._adapter = WireGuardAdapter(
                config_file=vpn_cfg.get("config_file", "wg0.conf"),
                interface=vpn_cfg.get("interface", "wg0"),
            )

        self._vpn_type = vpn_type
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
        if ok and self._vpn_type == "ssh":
            from proxy import tunnel as _tunnel
            from .ssh_tunnel import SSHTunnel
            adapter: SSHTunnel = self._adapter  # type: ignore[assignment]
            _tunnel.upstream_socks5 = ("127.0.0.1", adapter._local_port)
            log.info(f"Upstream SOCKS5 set to 127.0.0.1:{adapter._local_port}")

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

        if self._vpn_type == "ssh":
            from proxy import tunnel as _tunnel
            _tunnel.upstream_socks5 = None
            log.info("Upstream SOCKS5 cleared")

    async def get_status(self) -> dict[str, Any]:
        return await self._adapter.get_status()

    async def _health_monitor(self) -> None:
        while True:
            await asyncio.sleep(30)
            if not self._adapter.is_connected:
                log.warning("[warn]VPN disconnected, attempting reconnect...[/warn]")
                if self._vpn_type == "ssh":
                    from proxy import tunnel as _tunnel
                    _tunnel.upstream_socks5 = None
                ok = await self._adapter.connect()
                if ok and self._vpn_type == "ssh":
                    from proxy import tunnel as _tunnel
                    from .ssh_tunnel import SSHTunnel
                    adapter: SSHTunnel = self._adapter  # type: ignore[assignment]
                    _tunnel.upstream_socks5 = ("127.0.0.1", adapter._local_port)
                    log.info(f"Upstream SOCKS5 restored to 127.0.0.1:{adapter._local_port}")
