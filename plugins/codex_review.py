from __future__ import annotations

import asyncio
import time
from collections import deque
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from .base import ProxyPlugin, RequestContext, ResponseContext
from utils.logger import get_logger

if TYPE_CHECKING:
    from ai.openai_client import OpenAIClient

log = get_logger("plugin.codex_review")

_EXT_TO_LANG: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "tsx", ".jsx": "jsx", ".go": "go", ".rs": "rust",
    ".java": "java", ".cpp": "cpp", ".c": "c", ".cs": "csharp",
    ".rb": "ruby", ".php": "php", ".swift": "swift", ".kt": "kotlin",
    ".sh": "bash", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
}

_MAX_CODE_SIZE = 60_000


class CodexReviewPlugin(ProxyPlugin):
    name = "codex_review"

    def __init__(
        self,
        openai_client: "OpenAIClient | None" = None,
        enabled: bool = True,
        max_body_size: int = _MAX_CODE_SIZE,
        min_lines: int = 5,
    ):
        self.enabled = enabled
        self._openai = openai_client
        self._max_body = max_body_size
        self._min_lines = min_lines
        self._reviews: deque[dict[str, Any]] = deque(maxlen=200)
        self._pending: set[asyncio.Task] = set()

    def get_recent_reviews(self, n: int = 20) -> list[dict[str, Any]]:
        return list(self._reviews)[-n:]

    def set_openai_client(self, client: "OpenAIClient") -> None:
        self._openai = client

    async def on_response(self, ctx: ResponseContext) -> ResponseContext | None:
        if not self._openai or not ctx.body:
            return ctx

        lang = self._detect_language(ctx.request)
        if not lang:
            return ctx

        snippet = ctx.body[: self._max_body]
        try:
            text = snippet.decode("utf-8", errors="replace")
        except Exception:
            return ctx

        if text.count("\n") < self._min_lines:
            return ctx

        task = asyncio.create_task(self._run_review(ctx.request.url, lang, text))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

        return ctx

    def _detect_language(self, req: RequestContext) -> str | None:
        raw_path = (req.path or "/").split("?")[0]
        ext = PurePosixPath(raw_path).suffix.lower()
        return _EXT_TO_LANG.get(ext)

    async def _run_review(self, url: str, language: str, code: str) -> None:
        try:
            result = await self._openai.review_code(code, language)
            result["url"] = url
            result["language"] = language
            result["reviewed_at"] = time.time()
            self._reviews.append(result)

            n_issues = len(result.get("issues", []))
            severity = result.get("severity", "none")
            score = result.get("score", "?")
            log.info(
                f"[bold cyan]Codex Review[/bold cyan] {language} "
                f"score={score}/10 issues={n_issues} [{severity}] {url}"
            )
        except Exception as exc:
            log.debug(f"Codex review failed for {url}: {exc}")

    async def on_shutdown(self) -> None:
        for task in list(self._pending):
            task.cancel()
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
