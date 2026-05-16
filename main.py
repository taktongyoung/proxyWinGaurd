from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

import click
import yaml
from rich.panel import Panel
from rich.table import Table

from utils.logger import get_logger, console

log = get_logger("main")


def _load_config(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        log.warning(f"Config not found at {config_path}, using defaults")
        return {}
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    def _expand(obj: Any) -> Any:
        if isinstance(obj, str):
            import re
            return re.sub(
                r"\$\{([^}]+)\}",
                lambda m: os.environ.get(m.group(1), m.group(0)),
                obj,
            )
        if isinstance(obj, dict):
            return {k: _expand(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_expand(i) for i in obj]
        return obj

    return _expand(raw)


def _build_plugins(config: dict, claude_client=None) -> list:
    from plugins.traffic_logger import TrafficLoggerPlugin
    from plugins.content_filter import ContentFilterPlugin
    from plugins.ai_analyzer import AIAnalyzerPlugin

    plugins_cfg = config.get("plugins", {})
    plugins = []

    tl_cfg = plugins_cfg.get("traffic_logger", {})
    plugins.append(
        TrafficLoggerPlugin(
            log_file=tl_cfg.get("log_file", "logs/traffic.log"),
            enabled=tl_cfg.get("enabled", True),
        )
    )

    cf_cfg = plugins_cfg.get("content_filter", {})
    plugins.append(
        ContentFilterPlugin(
            blocked_domains=cf_cfg.get("blocked_domains", []),
            enabled=cf_cfg.get("enabled", False),
        )
    )

    ai_cfg = plugins_cfg.get("ai_analyzer", {})
    analyzer = AIAnalyzerPlugin(
        claude_client=claude_client,
        analyze_every_n_requests=ai_cfg.get("analyze_every_n_requests", 100),
        enabled=ai_cfg.get("enabled", True),
    )
    plugins.append(analyzer)

    return plugins


def _build_plugins_with_openai(config: dict, claude_client=None, openai_client=None) -> list:
    plugins = _build_plugins(config, claude_client)

    from plugins.codex_review import CodexReviewPlugin
    cr_cfg = config.get("plugins", {}).get("codex_review", {})
    plugins.append(
        CodexReviewPlugin(
            openai_client=openai_client,
            enabled=cr_cfg.get("enabled", True),
            max_body_size=cr_cfg.get("max_body_size", 60_000),
            min_lines=cr_cfg.get("min_lines", 5),
        )
    )

    return plugins


def _build_ai_clients(config: dict):
    ai_cfg = config.get("ai", {})
    claude_client = None
    openai_client = None

    claude_cfg = ai_cfg.get("claude", {})
    if claude_cfg.get("enabled", True):
        api_key = claude_cfg.get("api_key", "")
        if api_key and not api_key.startswith("${"):
            try:
                from ai.claude_client import ClaudeClient
                claude_client = ClaudeClient(
                    api_key=api_key,
                    model=claude_cfg.get("model", "claude-sonnet-4-6"),
                )
                log.info("Claude client initialized")
            except Exception as e:
                log.warning(f"Claude client init failed: {e}")

    openai_cfg = ai_cfg.get("openai", {})
    if openai_cfg.get("enabled", True):
        api_key = openai_cfg.get("api_key", "")
        if api_key and not api_key.startswith("${"):
            try:
                from ai.openai_client import OpenAIClient
                openai_client = OpenAIClient(
                    api_key=api_key,
                    model=openai_cfg.get("model", "gpt-4o"),
                )
                log.info("OpenAI client initialized")
            except Exception as e:
                log.warning(f"OpenAI client init failed: {e}")

    return claude_client, openai_client


async def _run_proxy(config: dict, with_mcp: bool = False) -> None:
    from proxy.server import ProxyServer
    from vpn.manager import VPNManager

    claude_client, openai_client = _build_ai_clients(config)
    plugins = _build_plugins_with_openai(config, claude_client, openai_client)

    for plugin in plugins:
        try:
            await plugin.on_startup()
        except Exception as e:
            log.warning(f"Plugin {plugin.name} startup failed: {e}")

    vpn = VPNManager(config)
    vpn_ok = await vpn.start()
    if not vpn_ok:
        log.warning("[warn]VPN did not connect. Proxy will use default interface.[/warn]")

    server = ProxyServer(config, plugins, vpn.interface_ip)

    tasks: list[asyncio.Task] = []

    if with_mcp and config.get("mcp", {}).get("enabled", True):
        from mcp_server.server import MCPServer
        mcp = MCPServer(
            stats=server.stats,
            vpn_manager=vpn,
            plugins=plugins,
            claude=claude_client,
            openai_client=openai_client,
            plugin_dir=Path("plugins"),
        )
        tasks.append(asyncio.create_task(mcp.run()))

    tasks.append(asyncio.create_task(server.start()))

    _print_startup_banner(config, vpn)

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Shutting down...")
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await server.stop()
        await vpn.stop()
        for plugin in plugins:
            try:
                await plugin.on_shutdown()
            except Exception:
                pass
        log.info("Shutdown complete")


def _print_startup_banner(config: dict, vpn) -> None:
    proxy_cfg = config.get("proxy", {})
    table = Table(title="AutoProxy Status", show_header=True, header_style="bold cyan")
    table.add_column("Component", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("HTTP Proxy", f"{proxy_cfg.get('host', '0.0.0.0')}:{proxy_cfg.get('port', 8080)}")
    table.add_row("SOCKS5 Proxy", f"{proxy_cfg.get('host', '0.0.0.0')}:{proxy_cfg.get('socks5_port', 1080)}")
    table.add_row("VPN Status", "Connected" if vpn.is_connected else "Disconnected")
    table.add_row("VPN IP", vpn.interface_ip or "N/A")

    console.print(Panel(table, border_style="green"))


@click.group()
@click.option(
    "--config",
    "-c",
    default="config/config.yaml",
    show_default=True,
    help="Path to config file",
)
@click.pass_context
def cli(ctx: click.Context, config: str) -> None:
    ctx.ensure_object(dict)
    ctx.obj["config"] = _load_config(config)


@cli.command()
@click.option("--mcp", is_flag=True, default=False, help="Also start MCP server")
@click.pass_context
def start(ctx: click.Context, mcp: bool) -> None:
    """Start the proxy server and VPN."""
    config = ctx.obj["config"]
    try:
        asyncio.run(_run_proxy(config, with_mcp=mcp))
    except KeyboardInterrupt:
        pass


@cli.command()
@click.pass_context
def stop(ctx: click.Context) -> None:
    """Stop the proxy (send shutdown signal — use Ctrl+C when running in foreground)."""
    console.print("[yellow]Send Ctrl+C to the running proxy process to stop it.[/yellow]")


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show proxy and VPN status."""

    async def _check() -> None:
        from vpn.manager import VPNManager
        config = ctx.obj["config"]
        vpn = VPNManager(config)
        st = await vpn._adapter.get_status()

        table = Table(title="AutoProxy Status")
        table.add_column("Key", style="cyan")
        table.add_column("Value")
        for k, v in st.items():
            table.add_row(str(k), str(v))
        console.print(table)

    asyncio.run(_check())


@cli.command("mcp")
@click.pass_context
def run_mcp(ctx: click.Context) -> None:
    """Start in MCP-only server mode (stdio transport, no proxy)."""
    config = ctx.obj["config"]

    async def _mcp_only() -> None:
        from proxy.handler import ConnectionStats
        from vpn.manager import VPNManager
        from mcp_server.server import MCPServer

        claude_client, openai_client = _build_ai_clients(config)
        plugins = _build_plugins_with_openai(config, claude_client, openai_client)
        stats = ConnectionStats()
        vpn = VPNManager(config)

        mcp = MCPServer(
            stats=stats,
            vpn_manager=vpn,
            plugins=plugins,
            claude=claude_client,
            openai_client=openai_client,
            plugin_dir=Path("plugins"),
        )
        await mcp.run()

    asyncio.run(_mcp_only())


@cli.command("plugin")
@click.argument("action", type=click.Choice(["add", "list"]))
@click.argument("description", required=False, default="")
@click.pass_context
def plugin_cmd(ctx: click.Context, action: str, description: str) -> None:
    """Manage plugins. Use 'add <description>' to generate via OpenAI."""
    config = ctx.obj["config"]

    if action == "list":
        plugin_dir = Path("plugins")
        files = sorted(plugin_dir.glob("*.py"))
        table = Table(title="Plugin Files")
        table.add_column("File", style="cyan")
        table.add_column("Size")
        for f in files:
            if not f.name.startswith("_"):
                table.add_row(f.name, f"{f.stat().st_size} bytes")
        console.print(table)
        return

    if action == "add":
        if not description:
            console.print("[red]Description required for 'plugin add'[/red]")
            return

        async def _generate() -> None:
            _, openai_client = _build_ai_clients(config)
            if not openai_client:
                console.print("[red]OpenAI client not configured (check OPENAI_API_KEY)[/red]")
                return

            from mcp_server.tools import ProxyTools
            from proxy.handler import ConnectionStats
            from vpn.manager import VPNManager

            tools = ProxyTools(
                stats=ConnectionStats(),
                vpn_manager=VPNManager(config),
                plugins=[],
                claude=None,
                openai_client=openai_client,
                plugin_dir=Path("plugins"),
            )
            result = await tools.generate_plugin(description)
            console.print_json(data=result)

        asyncio.run(_generate())


if __name__ == "__main__":
    cli(obj={})
