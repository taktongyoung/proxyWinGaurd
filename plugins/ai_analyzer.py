from __future__ import annotations

import asyncio
from collections import deque
from typing import TYPE_CHECKING

from .base import ProxyPlugin, RequestContext, ResponseContext
from utils.logger import get_logger

if TYPE_CHECKING:
    from ai.claude_client import ClaudeClient

log = get_logger("plugin.ai_analyzer")


class AIAnalyzerPlugin(ProxyPlugin):
    name = "ai_analyzer"

    def __init__(
        self,
        claude_client: "ClaudeClient | None" = None,
        analyze_every_n_requests: int = 100,
        enabled: bool = True,
    ):
        self.enabled = enabled
        self._claude = claude_client
        self._analyze_every = analyze_every_n_requests
        self._request_count = 0
        self._recent: deque[dict] = deque(maxlen=200)
        self._analysis_task: asyncio.Task | None = None

    def set_claude_client(self, client: "ClaudeClient") -> None:
        self._claude = client

    async def on_request(self, ctx: RequestContext) -> RequestContext | None:
        self._request_count += 1
        self._recent.append(
            {
                "method": ctx.method,
                "host": ctx.host,
                "port": ctx.port,
                "path": ctx.path,
                "timestamp": ctx.timestamp,
            }
        )

        if self._request_count % self._analyze_every == 0:
            self._schedule_analysis()

        return ctx

    def _schedule_analysis(self) -> None:
        if self._analysis_task and not self._analysis_task.done():
            return
        self._analysis_task = asyncio.create_task(self._run_analysis())

    async def _run_analysis(self) -> None:
        if not self._claude:
            return
        try:
            logs = list(self._recent)
            result = await self._claude.analyze_traffic(logs)
            log.info(f"[ai]AI Traffic Analysis:[/ai] {result[:200]}...")
        except Exception as exc:
            log.warning(f"AI analysis failed: {exc}")

    async def on_shutdown(self) -> None:
        if self._analysis_task:
            self._analysis_task.cancel()
            try:
                await self._analysis_task
            except asyncio.CancelledError:
                pass
