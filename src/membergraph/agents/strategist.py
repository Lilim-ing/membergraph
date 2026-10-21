from __future__ import annotations

from ..blackboard import Blackboard
from ..contracts import Action
from ..tools.experiment import segment_buckets
from .base import AgentContext, BaseAgent

SYSTEM = (
    "你是会员增长策略负责人。基于已核实的结论给出可执行动作：人群、渠道、权益、时点、预算、成功指标。"
    "每个动作必须引用证据。禁止绝对化承诺。只输出 JSON。"
)


class Strategist(BaseAgent):
    name = "strategist"
    role = "strategist"
    system = SYSTEM

    def run(
        self,
        ctx: AgentContext,
        bb: Blackboard,
        round_no: int = 1,
        critique: dict | None = None,
        **kwargs,
    ) -> None:
        claims = bb.read_list("claims")
        if round_no == 1:
            segments = segment_buckets(ctx.warehouse, ctx.as_of)
            bb.write("segments", segments, self.name)
        else:
            segments = bb.read("segments", {})

        known = {e["id"] for e in bb.read_list("evidence")}
        payload = {
            "topic": bb.read("topic", ""),
            "claims": claims,
            "segments": segments,
            "budget_cny": float(bb.read("budget_cny", 30000)),
            "round": round_no,
        }
        if critique:
            payload["critique"] = critique

        data = ctx.ask(self.role, self.system, payload)
        actions: list[Action] = []
        for raw in data.get("actions", []):
            ids = [i for i in raw.get("evidence_ids", []) if i in known]
            if not ids:
                continue
            actions.append(Action(**{**raw, "evidence_ids": ids}))

        bb.write("actions", [a.model_dump() for a in actions], self.name)
        ctx.tracer.emit(
            "strategize",
            agent=self.name,
            round=round_no,
            actions=len(actions),
            revised=bool(critique),
        )
