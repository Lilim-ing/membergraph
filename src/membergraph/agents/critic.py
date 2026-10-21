from __future__ import annotations

from ..blackboard import Blackboard
from ..contracts import Critique
from .base import AgentContext, BaseAgent

SYSTEM = (
    "你是增长方案评审者。只按三条判据打回：证据不足、成本超限、动作缺失。"
    "打回必须给出 failure_code、原因和修复建议。不要为了显得严格而打回。只输出 JSON。"
)


class Critic(BaseAgent):
    name = "critic"
    role = "critic"
    system = SYSTEM

    def run(self, ctx: AgentContext, bb: Blackboard, round_no: int = 1, **kwargs) -> tuple[bool, list[Critique]]:
        claims = bb.read_list("claims")
        actions = bb.read_list("actions")
        evidence_ids = [e["id"] for e in bb.read_list("evidence")]
        max_budget = float(bb.read("budget_cny", 30000)) * 1.5

        data = ctx.ask(
            self.role,
            self.system,
            {
                "claims": claims,
                "actions": actions,
                "evidence_ids": evidence_ids,
                "max_budget_cny": max_budget,
                "round": round_no,
            },
        )
        critiques = [Critique(**c) for c in data.get("critiques", [])]
        verdict = str(data.get("verdict", "pass"))
        bb.write(f"critique_r{round_no}", [c.model_dump() for c in critiques], self.name)
        ctx.tracer.emit(
            "critique",
            agent=self.name,
            round=round_no,
            verdict=verdict,
            failure_codes=[c.failure_code for c in critiques],
        )
        return verdict == "pass", critiques
