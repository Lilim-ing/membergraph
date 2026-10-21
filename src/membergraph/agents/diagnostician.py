from __future__ import annotations

from ..blackboard import Blackboard
from ..contracts import Claim
from .base import AgentContext, BaseAgent

SYSTEM = (
    "你是会员增长诊断者。基于给定证据写归因结论，每条结论必须引用 evidence id。"
    "区分事实（fact）与推断（inference）。不要引入证据之外的数字。只输出 JSON。"
)


def build_evidence_payload(evidence: list[dict]) -> list[dict]:
    out = []
    for e in evidence:
        d = e.get("detail", {})
        if e["kind"] == "metric":
            out.append(
                {
                    "id": e["id"],
                    "kind": "metric",
                    "label": d.get("label"),
                    "unit": d.get("unit"),
                    "dimension": d.get("dimension"),
                    "current": d.get("current"),
                    "previous": d.get("previous"),
                    "delta": d.get("delta"),
                    "breakdown": d.get("breakdown", []),
                    "prev_breakdown": d.get("prev_breakdown", []),
                }
            )
        elif e["kind"] == "decomposition":
            out.append({"id": e["id"], "kind": "decomposition", "detail": d})
    return out


class Diagnostician(BaseAgent):
    name = "diagnostician"
    role = "diagnostician"
    system = SYSTEM

    def run(self, ctx: AgentContext, bb: Blackboard, **kwargs) -> None:
        evidence = bb.read_list("evidence")
        primary = evidence[0]["id"] if evidence else None
        data = ctx.ask(
            self.role,
            self.system,
            {
                "topic": bb.read("topic", ""),
                "primary_evidence_id": primary,
                "evidence": build_evidence_payload(evidence),
            },
        )
        known = {e["id"] for e in evidence}
        claims: list[Claim] = []
        for raw in data.get("claims", []):
            ids = [i for i in raw.get("evidence_ids", []) if i in known]
            if not ids:
                continue  # a claim that cannot be grounded is dropped, not softened
            claims.append(Claim(**{**raw, "evidence_ids": ids}))
        bb.write("claims", [c.model_dump() for c in claims], self.name)
        ctx.tracer.emit(
            "diagnose",
            agent=self.name,
            claims=len(claims),
            evidence=len(evidence),
            dropped=len(data.get("claims", [])) - len(claims),
        )
