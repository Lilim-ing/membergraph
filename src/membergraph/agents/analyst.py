from __future__ import annotations

from ..blackboard import Blackboard
from ..contracts import Evidence, SubQuestion, digest
from ..tools.metrics import METRIC_META, compute_metric
from ..utils import fmt_delta, fmt_value, month_window
from .base import AgentContext, BaseAgent

SYSTEM = (
    "你是会员数据分析师。只使用已注册指标，选择该子问题需要的维度和时间窗口。"
    "不要编造数字，所有数值由工具返回。只输出 JSON。"
)


class Analyst(BaseAgent):
    name = "analyst"
    role = "analyst"
    system = SYSTEM

    def run(self, ctx: AgentContext, bb: Blackboard, **kwargs) -> Evidence:
        q = SubQuestion(**kwargs["sub_question"])
        decision = ctx.ask(
            self.role,
            self.system,
            {"sub_question": q.model_dump(), "available_metrics": ["compute_metric"]},
        )
        if decision.get("tool") != "compute_metric":
            raise ValueError(f"analyst picked unsupported tool: {decision.get('tool')!r}")

        # The agent may choose the dimension, but not a different metric than the
        # sub-question it was assigned -- that would silently change the question.
        args = decision.get("args", {})
        metric = args.get("metric", q.metric)
        dimension = args.get("dimension", q.dimension)
        if metric != q.metric:
            raise ValueError(f"analyst drifted from {q.metric!r} to {metric!r}")

        allowed = METRIC_META[metric]["dims"]
        if dimension not in allowed:
            ctx.tracer.emit(
                "dimension_fallback",
                agent=self.name,
                metric=metric,
                requested=dimension,
                used=allowed[0],
            )
            dimension = allowed[0]

        cur_w, prev_w = month_window(ctx.as_of)
        ctx.budget.charge_tool()
        cur = compute_metric(ctx.warehouse, metric, cur_w["start"], cur_w["end"], dimension)
        ctx.budget.charge_tool()
        prev = compute_metric(ctx.warehouse, metric, prev_w["start"], prev_w["end"], dimension)

        delta = (cur["value"] or 0.0) - (prev["value"] or 0.0)
        detail = {
            "label": cur["label"],
            "unit": cur["unit"],
            "definition": cur["definition"],
            "current": cur["value"],
            "previous": prev["value"],
            "delta": delta,
            "breakdown": cur["breakdown"],
            "prev_breakdown": prev["breakdown"],
            "dimension": dimension,
            "period": cur_w,
            "prev_period": prev_w,
            "is_primary": q.id == "q1",
        }
        ev = Evidence(
            id=f"e{len(bb.read_list('evidence')) + 1}",
            kind="metric",
            query={"metric": metric, "dimension": dimension, "current": cur_w, "previous": prev_w},
            summary=(
                f"{cur['label']}（{dimension or '整体'}）= {fmt_value(cur['value'], cur['unit'])}；"
                f"上期 {fmt_value(prev['value'], prev['unit'])}，{fmt_delta(delta, cur['unit'])}"
            ),
            value=cur["value"],
            unit=cur["unit"],
            rows=cur["n"],
            detail=detail,
            digest=digest({"query": q.model_dump(), "current": cur, "previous": prev}),
            created_by=self.name,
        )
        bb.append("evidence", ev.model_dump(), self.name)
        ctx.tracer.emit(
            "tool_call",
            agent=self.name,
            tool="compute_metric",
            metric=metric,
            dimension=dimension,
            value=cur["value"],
            delta=round(delta, 6),
            evidence_id=ev.id,
        )
        return ev
