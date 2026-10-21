"""Provider-agnostic LLM interface.

Agents only ever see `LLMResult.data`, a dict that must validate against a
Pydantic model. That keeps the orchestration logic identical whether it runs
against a real model or the deterministic offline provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class LLMResult(BaseModel):
    data: dict[str, Any]
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    model: str = ""


class LLM(ABC):
    name: str = "abstract"

    @abstractmethod
    def complete(self, role: str, system: str, payload: dict[str, Any]) -> LLMResult:
        raise NotImplementedError
