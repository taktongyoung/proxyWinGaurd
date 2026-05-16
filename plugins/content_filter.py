from __future__ import annotations

import re
from fnmatch import fnmatch

from .base import ProxyPlugin, RequestContext, ResponseContext
from utils.logger import get_logger

log = get_logger("plugin.content_filter")


class ContentFilterPlugin(ProxyPlugin):
    name = "content_filter"

    def __init__(
        self,
        blocked_domains: list[str] | None = None,
        blocked_patterns: list[str] | None = None,
        enabled: bool = False,
    ):
        self.enabled = enabled
        self.blocked_domains: list[str] = blocked_domains or []
        self.blocked_patterns: list[re.Pattern] = [
            re.compile(p) for p in (blocked_patterns or [])
        ]

    def _is_blocked_domain(self, host: str) -> bool:
        for pattern in self.blocked_domains:
            if fnmatch(host, pattern):
                return True
        return False

    def _is_blocked_url(self, url: str) -> bool:
        for pattern in self.blocked_patterns:
            if pattern.search(url):
                return True
        return False

    async def on_connect(self, host: str, port: int) -> bool:
        if self._is_blocked_domain(host):
            log.warning(f"Blocked CONNECT to [bold]{host}:{port}[/bold]")
            return False
        return True

    async def on_request(self, ctx: RequestContext) -> RequestContext | None:
        if self._is_blocked_domain(ctx.host):
            log.warning(f"Blocked request to [bold]{ctx.host}[/bold]")
            return None
        if self._is_blocked_url(ctx.url):
            log.warning(f"Blocked URL [bold]{ctx.url}[/bold]")
            return None
        return ctx

    def add_blocked_domain(self, domain: str) -> None:
        if domain not in self.blocked_domains:
            self.blocked_domains.append(domain)
            log.info(f"Added blocked domain: {domain}")

    def remove_blocked_domain(self, domain: str) -> None:
        if domain in self.blocked_domains:
            self.blocked_domains.remove(domain)
            log.info(f"Removed blocked domain: {domain}")

    def add_blocked_pattern(self, pattern: str) -> None:
        self.blocked_patterns.append(re.compile(pattern))
        log.info(f"Added blocked pattern: {pattern}")
