"""Agent base: shared context, LLM accounting, and tracing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..blackboard import Blackboard
from ..budget import Budget
from ..contracts import digest
from ..llm.base import LLM
from ..observability.trace import Tracer
from ..tools.warehouse import Warehouse


@dataclass
class AgentContext:
    llm: LLM
    tracer: Tracer
    budget: Budget
    warehouse: Warehouse
    as_of: str
    provider: str

    def ask(self, role: str, system: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.budget.check_wall()
        result = self.llm.complete(role, system, payload)
        self.budget.charge_llm(result.cost_usd, result.tokens_in + result.tokens_out)
        self.tracer.emit(
            "llm_call",
            agent=role,
            model=result.model,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=round(result.cost_usd, 6),
            payload_digest=digest(payload),
        )
        return result.data


class BaseAgent:
    name: str = "base"
    role: str = "base"
    system: str = ""

    def run(self, ctx: AgentContext, bb: Blackboard, **kwargs: Any) -> None:
        raise NotImplementedError
