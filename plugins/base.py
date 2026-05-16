from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RequestContext:
    id: str
    method: str
    host: str
    port: int
    path: str
    headers: dict[str, str]
    body: bytes = b""
    client_addr: tuple[str, int] = ("", 0)
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def url(self) -> str:
        scheme = "https" if self.port == 443 else "http"
        path = self.path or "/"
        return f"{scheme}://{self.host}:{self.port}{path}"


@dataclass
class ResponseContext:
    request: RequestContext
    status_code: int
    headers: dict[str, str]
    body: bytes = b""
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed_ms(self) -> float:
        return (self.timestamp - self.request.timestamp) * 1000


class ProxyPlugin(ABC):
    name: str = "base"
    enabled: bool = True

    async def on_request(self, ctx: RequestContext) -> RequestContext | None:
        return ctx

    async def on_response(self, ctx: ResponseContext) -> ResponseContext | None:
        return ctx

    async def on_connect(self, host: str, port: int) -> bool:
        return True

    async def on_startup(self) -> None:
        pass

    async def on_shutdown(self) -> None:
        pass
