from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import aiofiles

from .base import ProxyPlugin, RequestContext, ResponseContext
from utils.logger import get_logger

log = get_logger("plugin.traffic_logger")


class TrafficLoggerPlugin(ProxyPlugin):
    name = "traffic_logger"

    def __init__(self, log_file: str = "logs/traffic.log", enabled: bool = True):
        self.enabled = enabled
        self.log_file = Path(log_file)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._writer_task: asyncio.Task | None = None

    async def on_startup(self) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def on_shutdown(self) -> None:
        if self._writer_task:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass

    async def _writer_loop(self) -> None:
        async with aiofiles.open(self.log_file, "a", encoding="utf-8") as f:
            while True:
                line = await self._queue.get()
                await f.write(line + "\n")
                await f.flush()

    async def on_request(self, ctx: RequestContext) -> RequestContext | None:
        entry = {
            "type": "request",
            "id": ctx.id,
            "method": ctx.method,
            "host": ctx.host,
            "port": ctx.port,
            "path": ctx.path,
            "client": f"{ctx.client_addr[0]}:{ctx.client_addr[1]}",
            "timestamp": ctx.timestamp,
        }
        await self._queue.put(json.dumps(entry))
        return ctx

    async def on_response(self, ctx: ResponseContext) -> ResponseContext | None:
        entry = {
            "type": "response",
            "id": ctx.request.id,
            "status": ctx.status_code,
            "elapsed_ms": round(ctx.elapsed_ms, 2),
            "bytes": len(ctx.body),
            "timestamp": ctx.timestamp,
        }
        await self._queue.put(json.dumps(entry))
        return ctx

    async def on_connect(self, host: str, port: int) -> bool:
        entry = {"type": "connect", "host": host, "port": port}
        await self._queue.put(json.dumps(entry))
        return True

    def get_recent_logs(self, n: int = 100) -> list[dict]:
        if not self.log_file.exists():
            return []
        lines = self.log_file.read_text(encoding="utf-8").splitlines()
        recent = lines[-n:] if len(lines) > n else lines
        result = []
        for line in recent:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return result
