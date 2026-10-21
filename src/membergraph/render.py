"""Markdown rendering of a plan."""

from __future__ import annotations

from .contracts import Plan
from .utils import fmt_value


def plan_to_markdown(plan: Plan) -> str:
    ev = plan.evidence_index()
    lines: list[str] = [
        f"# {plan.topic}",
        "",
        f"> run_id `{plan.run_id}` · provider `{plan.provider}` · 生成于 {plan.finished_at or plan.started_at}",
        f"> 预算 ${plan.budget.get('spent_usd', 0):.4f} / ${plan.budget.get('max_usd', 0):.2f}"
        f" · 工具调用 {plan.budget.get('tool_calls', 0)}/{plan.budget.get('max_tool_calls', 0)}"
        f" · 耗时 {plan.budget.get('elapsed_ms', 0) / 1000:.1f}s",
    ]
    if plan.degraded:
        lines.append(f"> ⚠️ **本次运行已降级**：{plan.degrade_reason}")
    if plan.blocked:
        lines.append("> ⛔ **合规未通过**，方案不可直接执行。")
    lines += [
        "",
        "## 摘要",
        "",
        f"- 子问题 {len(plan.sub_questions)} 个，证据 {len(plan.evidence)} 条，结论 {len(plan.claims)} 条，动作 {len(plan.actions)} 个",
        f"- 合规问题 {len(plan.compliance)} 项（阻断 {sum(1 for i in plan.compliance if i.severity == 'block')} 项）",
        f"- 评审记录 {len(plan.critiques)} 条",
        "",
        "## 一、核心结论",
        "",
    ]

    for i, c in enumerate(plan.claims, 1):
        refs = ", ".join(f"[{eid}]" for eid in c.evidence_ids)
        lines.append(f"{i}. {c.text} {refs}  ")
        lines.append(f"   <sub>{c.kind} · 置信度 {c.confidence:.2f}</sub>")
        lines.append("")

    lines += ["## 二、证据清单", "", "| id | 类型 | 证据 | 数值 |", "|---|---|---|---|"]
    for e in plan.evidence:
        lines.append(f"| `{e.id}` | {e.kind} | {e.summary} | {fmt_value(e.value, e.unit)} |")

    lines += ["", "## 三、执行动作", ""]
    if not plan.actions:
        lines.append("_本次运行没有产出可执行动作。_")
    for i, a in enumerate(plan.actions, 1):
        refs = ", ".join(f"[{eid}]" for eid in a.evidence_ids)
        lines += [
            f"### 动作 {i}：{a.offer}",
            "",
            f"| 项 | 内容 |",
            f"|---|---|",
            f"| 人群 | {a.segment} |",
            f"| 渠道 | {a.channel} |",
            f"| 权益 | {a.offer} |",
            f"| 时点 | {a.timing} |",
            f"| 预算 | ¥{a.budget_cny:,.0f} |",
            f"| 成功指标 | {a.success_metric} |",
            f"| 预期提升 | {'—' if a.expected_lift is None else f'{a.expected_lift:.1%}'} |",
            f"| 依据 | {refs} |",
            "",
        ]

    if plan.critiques:
        lines += ["## 四、评审记录", "", "| 轮次 | 结论 | failure_code | 原因 |", "|---|---|---|---|"]
        for c in plan.critiques:
            lines.append(f"| {c.round} | 打回 | `{c.failure_code}` | {c.reason} |")
        lines.append("")
    else:
        lines += ["## 四、评审记录", "", "评审未打回：证据链完整、动作含成功指标、预算在约束内。", ""]

    if plan.compliance:
        lines += ["## 五、合规检查", "", "| 级别 | 规则 | 说明 |", "|---|---|---|"]
        for issue in plan.compliance:
            lines.append(f"| {issue.severity} | `{issue.code}` | {issue.detail} |")
        lines.append("")
    else:
        lines += ["## 五、合规检查", "", "全部通过。", ""]

    lines += [
        "## 六、方法与边界",
        "",
        "- 所有数值来自本地合成数据的只读查询，可用 `plan.json` 中的 `query` 字段复算。",
        "- 每条结论必须挂 `evidence_id`；无证据结论在生成阶段已被丢弃。",
        "- 指标口径见 `docs/METRICS.md`；数据假设见 `docs/DATA_ASSUMPTIONS.md`。",
        "- 本报告为机制演示，不构成任何经营建议。",
        "",
    ]
    return "\n".join(lines)
