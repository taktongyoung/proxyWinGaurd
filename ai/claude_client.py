from __future__ import annotations

import json
from typing import Any

import anthropic

from utils.logger import get_logger

log = get_logger("ai.claude")

_SYSTEM_PROMPT = """You are a network security analyst embedded in a proxy server.
You analyze HTTP/HTTPS traffic patterns to identify:
- Suspicious or anomalous behavior
- Data exfiltration attempts
- Malware command-and-control patterns
- Privacy violations or tracking
- Performance bottlenecks

Be concise and actionable. Format findings as bullet points.
Flag severity as [LOW], [MEDIUM], [HIGH], or [CRITICAL]."""


class ClaudeClient:
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
        self._cached_system: list[dict] = [
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    async def analyze_traffic(self, logs: list[dict]) -> str:
        sample = logs[-50:] if len(logs) > 50 else logs
        user_content = (
            f"Analyze these {len(sample)} recent proxy requests and identify any issues:\n\n"
            + json.dumps(sample, indent=2, default=str)
        )

        response = await self._client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=self._cached_system,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text

    async def suggest_filter_rules(self, anomaly_description: str) -> str:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=512,
            system=self._cached_system,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Based on this anomaly, suggest specific domain/URL filter rules "
                        f"in fnmatch format:\n\n{anomaly_description}\n\n"
                        "Return a JSON object with keys 'blocked_domains' (list) and "
                        "'blocked_patterns' (list of regex strings)."
                    ),
                }
            ],
        )
        return response.content[0].text

    async def explain_connection(self, ctx_dict: dict) -> str:
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=256,
            system=self._cached_system,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Briefly explain what this connection is doing and whether it looks legitimate:\n\n"
                        + json.dumps(ctx_dict, indent=2, default=str)
                    ),
                }
            ],
        )
        return response.content[0].text
