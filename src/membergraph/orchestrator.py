"""Orchestration: plan -> gather evidence -> diagnose -> strategise -> critique -> comply.

Two behaviours matter more than the happy path:

1. A claim that cannot be grounded is dropped before it reaches the plan.
2. When the budget runs out the run degrades and says so, instead of either
   crashing or pretending it finished.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .agents.analyst import Analyst
from .agents.base import AgentContext
from .agents.compliance import Compliance
from .agents.critic import Critic
from .agents.diagnostician import Diagnostician
from .agents.planner import Planner
from .agents.strategist import Strategist
from .blackboard import Blackboard
from .budget import Budget, BudgetExceeded
from .contracts import Evidence, Plan, SubQuestion, digest, now_iso
from .llm import build_llm
from .observability.trace import Tracer
from .render import plan_to_markdown
from .tools.cohort import DECOMP_SPECS, decompose
from .tools.warehouse import Warehouse
from .utils import fmt_delta, fmt_value, month_window


@dataclass
class RunConfig:
    topic: str
    provider: str = "fake"
    as_of: str = "2026-09-30"
    out_dir: Path = field(default_factory=lambda: Path("runs/demo"))
    budget_usd: float = 0.60
    budget_cny: float = 30_000
    max_tool_calls: int = 30
    max_wall_ms: int = 120_000
    model: str | None = None


class Orchestrator:
    def __init__(self, data_dir: str | Path, config: RunConfig, tracer_sink: Any = None) -> None:
        self.data_dir = Path(data_dir)
        self.config = config
        self.tracer_sink = tracer_sink

    def run(self) -> Plan:
        cfg = self.config
        run_id = f"mg-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        out_dir = Path(cfg.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        tracer = Tracer(out_dir / "trace.jsonl", run_id, sink=self.tracer_sink)
        budget = Budget(
            max_usd=cfg.budget_usd,
            max_tool_calls=cfg.max_tool_calls,
            max_wall_ms=cfg.max_wall_ms,
        )
        degraded = False
        degrade_reason = ""

        planner, analyst = Planner(), Analyst()
        diagnostician, strategist = Diagnostician(), Strategist()
        critic, compliance = Critic(), Compliance()

        with Warehouse(self.data_dir) as warehouse:
            ctx = AgentContext(
                llm=build_llm(cfg.provider, **({"model": cfg.model} if cfg.model else {})),
                tracer=tracer,
                budget=budget,
                warehouse=warehouse,
                as_of=cfg.as_of,
                provider=cfg.provider,
            )
            bb = Blackboard(run_id)
            bb.write("topic", cfg.topic, "orchestrator")
            bb.write("budget_cny", cfg.budget_cny, "orchestrator")
            tracer.emit("run_start", agent="orchestrator", topic=cfg.topic, provider=cfg.provider, as_of=cfg.as_of)

            try:
                planner.run(ctx, bb)
                questions = [SubQuestion(**q) for q in bb.read("sub_questions", [])]

                for q in questions:
                    try:
                        analyst.run(ctx, bb, sub_question=q.model_dump())
                    except BudgetExceeded as exc:
                        degraded = True
                        degrade_reason = f"取证阶段预算耗尽（{exc.kind}），仅完成部分子问题"
                        tracer.emit("degrade", agent="orchestrator", reason=degrade_reason, stage="analysis")
                        break

                if not degraded:
                    try:
                        ev = self._decompose(ctx, bb, questions)
                        if ev is None:
                            tracer.emit(
                                "decomposition_skipped",
                                agent="orchestrator",
                                reason="主指标暂无 shift-share 定义，跳过以免输出误导性归因",
                            )
                    except BudgetExceeded as exc:
                        degraded = True
                        degrade_reason = f"分解阶段预算耗尽（{exc.kind}），跳过结构/行为拆解"
                        tracer.emit("degrade", agent="orchestrator", reason=degrade_reason, stage="decompose")

                diagnostician.run(ctx, bb)

                strategist.run(ctx, bb, round_no=1)

                max_rounds = 2 if budget.level() < 2 else 1
                for r in range(1, max_rounds + 1):
                    try:
                        ok, critiques = critic.run(ctx, bb, round_no=r)
                    except BudgetExceeded as exc:
                        degraded = True
                        degrade_reason = f"评审阶段预算耗尽（{exc.kind}），跳过第 {r} 轮评审"
                        tracer.emit("degrade", agent="orchestrator", reason=degrade_reason, stage="critique")
                        break
                    if ok:
                        break
                    if r == max_rounds:
                        tracer.emit("critique_exhausted", agent="critic", round=r)
                        break
                    strategist.run(
                        ctx,
                        bb,
                        round_no=r + 1,
                        critique=critiques[0].model_dump() if critiques else None,
                    )

                compliance.run(ctx, bb)

            except Exception as exc:  # noqa: BLE001 - we want the trace to survive anything
                tracer.emit("run_error", agent="orchestrator", error=f"{type(exc).__name__}: {exc}")
                tracer.close()
                raise

            critiques_all: list[dict[str, Any]] = []
            for key, value in bb.snapshot().items():
                if key.startswith("critique_r"):
                    critiques_all.extend(value or [])

            plan = Plan(
                run_id=run_id,
                topic=cfg.topic,
                provider=cfg.provider,
                sub_questions=[SubQuestion(**q) for q in bb.read("sub_questions", [])],
                evidence=[Evidence(**e) for e in bb.read("evidence", [])],
                claims=bb.read("claims", []),
                actions=bb.read("actions", []),
                critiques=critiques_all,
                compliance=bb.read("compliance", []),
                degraded=degraded,
                degrade_reason=degrade_reason,
                budget=budget.snapshot(),
                finished_at=now_iso(),
            )

            (out_dir / "plan.json").write_text(
                json.dumps(plan.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (out_dir / "plan.md").write_text(plan_to_markdown(plan), encoding="utf-8")
            (out_dir / "blackboard.json").write_text(
                json.dumps(
                    {k: {"revision": len(v), "value": v[-1].value} for k, v in
                     {key: bb.history(key) for key in bb.snapshot()}.items()},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            tracer.emit(
                "run_end",
                agent="orchestrator",
                degraded=degraded,
                claims=len(plan.claims),
                evidence=len(plan.evidence),
                actions=len(plan.actions),
                blocking_issues=sum(1 for i in plan.compliance if i.severity == "block"),
                cost_usd=plan.budget.get("spent_usd"),
            )
            tracer.close()
            return plan

    # -- helpers ---------------------------------------------------------
    def _decompose(
        self, ctx: AgentContext, bb: Blackboard, questions: list[SubQuestion]
    ) -> Evidence | None:
        primary = questions[0] if questions else None
        metric = primary.metric if primary else "aov"
        if metric not in DECOMP_SPECS:
            return None
        allowed_dims = DECOMP_SPECS[metric]["dims"].split(",")
        dimension = primary.dimension if primary and primary.dimension in allowed_dims else allowed_dims[0]

        cur_w, prev_w = month_window(ctx.as_of)
        ctx.budget.charge_tool()
        result = decompose(
            ctx.warehouse,
            metric,
            dimension,
            prev_w["start"],
            prev_w["end"],
            cur_w["start"],
            cur_w["end"],
        )
        unit = result["unit"]
        ev = Evidence(
            id=f"e{len(bb.read_list('evidence')) + 1}",
            kind="decomposition",
            query={"metric": metric, "dimension": dimension, "current": cur_w, "previous": prev_w},
            summary=(
                f"{metric} 按 {dimension} 分解：总变化 {fmt_delta(result['total_change'], unit)}，"
                f"结构效应 {fmt_delta(result['structural_effect'], unit)}，"
                f"行为效应 {fmt_delta(result['behavioural_effect'], unit)}"
            ),
            value=result["total_change"],
            unit=unit,
            rows=len(result["contributors"]),
            detail=result,
            digest=digest(result),
            created_by="analyst",
        )
        bb.append("evidence", ev.model_dump(), "analyst")
        ctx.tracer.emit(
            "tool_call",
            agent="analyst",
            tool="decompose",
            metric=metric,
            dimension=dimension,
            total_change=result["total_change"],
            evidence_id=ev.id,
        )
        return ev
