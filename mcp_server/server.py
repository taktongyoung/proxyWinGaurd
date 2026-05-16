from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

from utils.logger import get_logger
from .tools import ProxyTools

if TYPE_CHECKING:
    from proxy.handler import ConnectionStats
    from vpn.manager import VPNManager
    from plugins.base import ProxyPlugin
    from ai.claude_client import ClaudeClient
    from ai.openai_client import OpenAIClient

log = get_logger("mcp.server")


class MCPServer:
    def __init__(
        self,
        stats: "ConnectionStats",
        vpn_manager: "VPNManager",
        plugins: list["ProxyPlugin"],
        claude: "ClaudeClient | None",
        openai_client: "OpenAIClient | None",
        plugin_dir: Path | None = None,
    ):
        self._proxy_tools = ProxyTools(
            stats=stats,
            vpn_manager=vpn_manager,
            plugins=plugins,
            claude=claude,
            openai_client=openai_client,
            plugin_dir=plugin_dir or Path("plugins"),
        )
        self._mcp = FastMCP("autoproxy")
        self._register_tools()
        self._register_resources()

    def _register_tools(self) -> None:
        mcp = self._mcp
        tools = self._proxy_tools

        @mcp.tool(description="Get current proxy statistics: active connections, bytes transferred, total requests.")
        async def get_proxy_stats() -> str:
            result = await tools.get_proxy_stats()
            return json.dumps(result, indent=2, default=str)

        @mcp.tool(description="Send recent traffic logs to Claude for security analysis.")
        async def analyze_traffic(n_recent: int = 100) -> str:
            return await tools.analyze_traffic(n_recent)

        @mcp.tool(description="Enable or disable a proxy plugin by name.")
        async def toggle_plugin(plugin_name: str, enabled: bool) -> str:
            result = await tools.toggle_plugin(plugin_name, enabled)
            return json.dumps(result)

        @mcp.tool(description="Get WireGuard VPN connection status.")
        async def vpn_status() -> str:
            result = await tools.vpn_status()
            return json.dumps(result, indent=2, default=str)

        @mcp.tool(description="Use OpenAI to generate a new proxy plugin from a natural language description.")
        async def generate_plugin(description: str) -> str:
            result = await tools.generate_plugin(description)
            return json.dumps(result, indent=2, default=str)

        @mcp.tool(description="List all registered proxy plugins and their enabled state.")
        async def list_plugins() -> str:
            result = await tools.list_plugins()
            return json.dumps(result, indent=2)

        @mcp.tool(
            description=(
                "Retrieve code reviews collected by the codex_review plugin. "
                "Optionally filter by severity: none | low | medium | high."
            )
        )
        async def get_code_reviews(n: int = 20, severity: str = "") -> str:
            result = await tools.get_code_reviews(n, severity or None)
            return json.dumps(result, indent=2, default=str)

        @mcp.tool(
            description=(
                "Send a code snippet directly to OpenAI for review. "
                "Returns bugs, security issues, suggestions, severity, and a quality score."
            )
        )
        async def review_code_snippet(code: str, language: str = "python") -> str:
            result = await tools.review_code_snippet(code, language)
            return json.dumps(result, indent=2, default=str)

    def _register_resources(self) -> None:
        mcp = self._mcp
        tools = self._proxy_tools

        @mcp.resource("autoproxy://traffic_logs")
        async def traffic_logs() -> str:
            logs = await tools.get_traffic_logs(100)
            return json.dumps(logs, indent=2, default=str)

        @mcp.resource("autoproxy://active_connections")
        async def active_connections() -> str:
            conns = await tools.get_active_connections()
            return json.dumps(conns, indent=2, default=str)

        @mcp.resource("autoproxy://code_reviews")
        async def code_reviews() -> str:
            reviews = await tools.get_code_reviews(100)
            return json.dumps(reviews, indent=2, default=str)

    async def run(self) -> None:
        log.info("[mcp]MCP server starting on stdio transport[/mcp]")
        await self._mcp.run_async(transport="stdio")
