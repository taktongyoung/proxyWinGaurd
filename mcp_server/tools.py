from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from proxy.handler import ConnectionStats
    from vpn.manager import VPNManager
    from plugins.base import ProxyPlugin
    from plugins.traffic_logger import TrafficLoggerPlugin
    from ai.claude_client import ClaudeClient
    from ai.openai_client import OpenAIClient


class ProxyTools:
    def __init__(
        self,
        stats: "ConnectionStats",
        vpn_manager: "VPNManager",
        plugins: list["ProxyPlugin"],
        claude: "ClaudeClient | None",
        openai_client: "OpenAIClient | None",
        plugin_dir: Path,
    ):
        self._stats = stats
        self._vpn = vpn_manager
        self._plugins = plugins
        self._claude = claude
        self._openai = openai_client
        self._plugin_dir = plugin_dir

    async def get_proxy_stats(self) -> dict[str, Any]:
        return {
            "active_connections": len(self._stats.active),
            "total_requests": self._stats.total_requests,
            "bytes_sent": self._stats.total_bytes_sent,
            "bytes_recv": self._stats.total_bytes_recv,
            "active_list": list(self._stats.active.values()),
        }

    async def analyze_traffic(self, n_recent: int = 100) -> str:
        if not self._claude:
            return "Claude client not configured"

        logger_plugin = self._get_traffic_logger()
        if not logger_plugin:
            return "Traffic logger plugin not active"

        logs = logger_plugin.get_recent_logs(n_recent)
        if not logs:
            return "No traffic logs available"

        return await self._claude.analyze_traffic(logs)

    async def toggle_plugin(self, plugin_name: str, enabled: bool) -> dict[str, Any]:
        for plugin in self._plugins:
            if plugin.name == plugin_name:
                plugin.enabled = enabled
                return {"plugin": plugin_name, "enabled": enabled, "status": "updated"}
        return {"error": f"Plugin '{plugin_name}' not found"}

    async def vpn_status(self) -> dict[str, Any]:
        return await self._vpn.get_status()

    async def generate_plugin(self, description: str) -> dict[str, Any]:
        if not self._openai:
            return {"error": "OpenAI client not configured"}

        code = await self._openai.generate_plugin(description)
        if not code:
            return {"error": "OpenAI returned empty code"}

        review = await self._openai.analyze_code(code)
        if not review.get("safe", False) and review.get("severity") == "high":
            return {
                "error": "Plugin failed safety review",
                "issues": review.get("issues", []),
                "code": code,
            }

        class_name = self._extract_class_name(code)
        filename = (class_name or "generated_plugin").lower().replace("plugin", "_plugin")
        out_path = self._plugin_dir / f"{filename}.py"
        out_path.write_text(code, encoding="utf-8")

        return {
            "status": "generated",
            "file": str(out_path),
            "class_name": class_name,
            "review": review,
        }

    async def list_plugins(self) -> list[dict[str, Any]]:
        return [
            {"name": p.name, "enabled": p.enabled, "class": type(p).__name__}
            for p in self._plugins
        ]

    async def get_traffic_logs(self, n: int = 50) -> list[dict]:
        logger = self._get_traffic_logger()
        if not logger:
            return []
        return logger.get_recent_logs(n)

    async def get_active_connections(self) -> list[dict]:
        return list(self._stats.active.values())

    async def get_code_reviews(self, n: int = 20, severity: str | None = None) -> list[dict]:
        from plugins.codex_review import CodexReviewPlugin
        for plugin in self._plugins:
            if isinstance(plugin, CodexReviewPlugin):
                reviews = plugin.get_recent_reviews(n)
                if severity:
                    reviews = [r for r in reviews if r.get("severity") == severity]
                return reviews
        return []

    async def review_code_snippet(self, code: str, language: str = "python") -> dict:
        if not self._openai:
            return {"error": "OpenAI client not configured"}
        return await self._openai.review_code(code, language)

    def _get_traffic_logger(self):
        from plugins.traffic_logger import TrafficLoggerPlugin
        for plugin in self._plugins:
            if isinstance(plugin, TrafficLoggerPlugin):
                return plugin
        return None

    @staticmethod
    def _extract_class_name(code: str) -> str | None:
        import re
        match = re.search(r"class\s+(\w+)\s*\(", code)
        return match.group(1) if match else None
