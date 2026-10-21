"""OpenAI-compatible provider (DeepSeek, OpenAI, or any compatible gateway).

Cost figures are estimates: the rates below are configurable defaults, not a
claim about current vendor pricing.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .base import LLM, LLMResult


class LLMError(RuntimeError):
    pass


class OpenAICompatLLM(LLM):
    def __init__(
        self,
        model: str = "deepseek-chat",
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.2,
        timeout_s: float = 60.0,
        usd_per_mtok_in: float = 0.14,
        usd_per_mtok_out: float = 0.28,
    ) -> None:
        self.name = f"openai-compat:{model}"
        self.model = model
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = (base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")).rstrip("/")
        self.temperature = temperature
        self.timeout_s = timeout_s
        self.usd_per_mtok_in = usd_per_mtok_in
        self.usd_per_mtok_out = usd_per_mtok_out

    def complete(self, role: str, system: str, payload: dict[str, Any]) -> LLMResult:
        if not self.api_key:
            raise LLMError(
                "missing API key: set DEEPSEEK_API_KEY, or run with --provider fake"
            )
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "temperature": self.temperature,
            "response_format": {"type": "json_object"},
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
                timeout=self.timeout_s,
            )
        except httpx.HTTPError as exc:  # network layer
            raise LLMError(f"{role}: request failed: {exc}") from exc

        if resp.status_code >= 400:
            raise LLMError(f"{role}: HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMError(f"{role}: malformed response: {str(data)[:300]}") from exc

        usage = data.get("usage", {}) or {}
        tin = int(usage.get("prompt_tokens", 0))
        tout = int(usage.get("completion_tokens", 0))
        cost = tin / 1_000_000 * self.usd_per_mtok_in + tout / 1_000_000 * self.usd_per_mtok_out

        return LLMResult(
            data=parsed,
            tokens_in=tin,
            tokens_out=tout,
            cost_usd=cost,
            model=self.model,
        )
