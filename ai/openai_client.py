from __future__ import annotations

import textwrap
from typing import Any

from openai import AsyncOpenAI

from utils.logger import get_logger

log = get_logger("ai.openai")

_PLUGIN_TEMPLATE = '''\
from __future__ import annotations
from plugins.base import ProxyPlugin, RequestContext, ResponseContext

class {class_name}(ProxyPlugin):
    name = "{plugin_name}"
    enabled = True

    async def on_request(self, ctx: RequestContext) -> RequestContext | None:
        ...

    async def on_response(self, ctx: ResponseContext) -> ResponseContext | None:
        ...

    async def on_connect(self, host: str, port: int) -> bool:
        ...
'''


class OpenAIClient:
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self._client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def generate_plugin(self, description: str) -> str:
        system = (
            "You are a Python expert writing proxy plugin code. "
            "Generate a complete, working Python module implementing a ProxyPlugin subclass. "
            "The plugin must inherit from ProxyPlugin in plugins.base. "
            "Return ONLY valid Python code with no markdown fences or explanation. "
            "The code must be importable and have no external dependencies beyond the project."
        )

        template_hint = _PLUGIN_TEMPLATE.format(
            class_name="MyPlugin", plugin_name="my_plugin"
        )

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"Plugin description: {description}\n\n"
                        f"Base template to follow:\n{template_hint}\n\n"
                        "Write the complete plugin implementation."
                    ),
                },
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content or ""

    async def analyze_code(self, code: str) -> dict[str, Any]:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a security-focused code reviewer. "
                        "Analyze the given Python plugin code for: "
                        "1) Security issues (code injection, file system access, network calls) "
                        "2) Correctness (does it follow the ProxyPlugin interface) "
                        "3) Performance concerns. "
                        "Return a JSON object with keys: "
                        "'safe' (bool), 'issues' (list of strings), 'severity' (low/medium/high)."
                    ),
                },
                {"role": "user", "content": f"Review this plugin:\n\n```python\n{code}\n```"},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        import json

        try:
            return json.loads(response.choices[0].message.content or "{}")
        except Exception:
            return {"safe": False, "issues": ["Failed to parse review"], "severity": "high"}

    async def review_code(self, code: str, language: str = "python") -> dict[str, Any]:
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior code reviewer with expertise in security and software quality. "
                        "Review the given code and return a JSON object with these keys:\n"
                        "- summary (string): one-sentence overall assessment\n"
                        "- issues (array): each item has {type, line_hint, description} where type is "
                        "  one of bug/security/performance/style\n"
                        "- suggestions (array of strings): actionable improvement ideas\n"
                        "- severity (string): none | low | medium | high — worst issue found\n"
                        "- score (integer 1-10): overall code quality, 10 is excellent\n"
                        "Return ONLY valid JSON, no markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Review this {language} code:\n\n```{language}\n{code}\n```",
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        import json as _json

        try:
            return _json.loads(response.choices[0].message.content or "{}")
        except Exception:
            return {
                "summary": "Failed to parse review response",
                "issues": [],
                "suggestions": [],
                "severity": "low",
                "score": 5,
            }
