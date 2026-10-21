"""Deterministic offline provider.

This is NOT a mock that returns lorem ipsum. Every number it mentions comes
from the payload, i.e. from a real warehouse query. What is replaced is only
the *decision* layer: which sub-questions to ask, which dimension to blame,
which playbook to pick. That makes the offline run a genuine test of the
orchestration, ledger and compliance machinery, but it says nothing about a
real model's reasoning quality -- the README states this explicitly.
"""

from __future__ import annotations

from typing import Any

from .base import LLM, LLMResult

PLAN_RULES: list[tuple[tuple[str, ...], list[tuple[str, str, str]]]] = [
    (
        ("复购", "回购", "二次"),
        [
            ("repurchase_rate_90d", "register_channel", "复购率在不同注册渠道之间是否存在差异"),
            ("repurchase_rate_90d", "member_level", "哪一档会员的复购下滑最明显"),
            ("aov", "channel", "客单价是否与复购同步变化"),
            ("return_rate", "category", "退货率是否在拖累复购"),
        ],
    ),
    (
        ("流失", "沉睡", "召回", "沉默"),
        [
            ("churn_rate_180d", "member_level", "流失集中在哪一档会员"),
            ("active_rate_30d", "city_tier", "活跃率是否同步走弱"),
            ("repurchase_rate_90d", "member_level", "流失前是否已出现复购下滑"),
        ],
    ),
    (
        ("活跃", "打开", "互动"),
        [
            ("active_rate_30d", "member_level", "活跃率变化集中在哪一档会员"),
            ("active_rate_30d", "city_tier", "城市线级之间是否存在差异"),
            ("repurchase_rate_90d", "channel", "活跃变化是否传导到复购"),
        ],
    ),
    (
        ("客单", "连带", "件单", "折扣"),
        [
            ("aov", "channel", "客单价变化集中在哪些渠道"),
            ("upt", "category", "连带率是否同步变化"),
            ("discount_rate", "member_level", "折扣加深是否换来了客单提升"),
        ],
    ),
]

DEFAULT_PLAN = [
    ("repurchase_rate_90d", "register_channel", "复购率在注册渠道间的差异"),
    ("aov", "channel", "客单价是否同步变化"),
    ("churn_rate_180d", "member_level", "流失是否集中在特定会员层级"),
]


def _fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "%":
        return f"{value * 100:.1f}%"
    if unit == "元":
        return f"{value:.0f}元"
    return f"{value:.2f}"


def _delta(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "%":
        return f"{value * 100:+.2f}pct"
    if unit == "元":
        return f"{value:+,.0f}元"
    return f"{value:+.2f}"


class FakeLLM(LLM):
    name = "fake"

    COST_PER_CALL = 0.00018

    def complete(self, role: str, system: str, payload: dict[str, Any]) -> LLMResult:
        handler = getattr(self, f"_{role}", None)
        if handler is None:
            data: dict[str, Any] = {}
        else:
            data = handler(payload)
        return LLMResult(
            data=data,
            tokens_in=len(str(payload)) // 3,
            tokens_out=len(str(data)) // 3,
            cost_usd=self.COST_PER_CALL,
            model="fake-rule-engine",
        )

    # -- planner ---------------------------------------------------------
    def _planner(self, payload: dict[str, Any]) -> dict[str, Any]:
        topic = str(payload.get("topic", ""))
        chosen = DEFAULT_PLAN
        for keywords, plan in PLAN_RULES:
            if any(k in topic for k in keywords):
                chosen = plan
                break
        return {
            "sub_questions": [
                {
                    "id": f"q{i + 1}",
                    "question": question,
                    "metric": metric,
                    "dimension": dim,
                    "rationale": f"用 {metric} 在 {dim} 维度上验证该假设",
                }
                for i, (metric, dim, question) in enumerate(chosen)
            ]
        }

    # -- analyst ---------------------------------------------------------
    def _analyst(self, payload: dict[str, Any]) -> dict[str, Any]:
        q = payload["sub_question"]
        return {
            "tool": "compute_metric",
            "args": {"metric": q["metric"], "dimension": q.get("dimension")},
            "compare": True,
            "why": f"回答「{q['question']}」需要该指标的本期与上期对比",
        }

    # -- diagnostician ---------------------------------------------------
    def _diagnostician(self, payload: dict[str, Any]) -> dict[str, Any]:
        evidence = payload.get("evidence", [])
        if not evidence:
            return {"claims": []}

        metric_ev = [e for e in evidence if e.get("kind") == "metric"]
        decomp_ev = [e for e in evidence if e.get("kind") == "decomposition"]
        claims: list[dict[str, Any]] = []

        if metric_ev:
            primary_id = payload.get("primary_evidence_id")
            main = next((e for e in metric_ev if e["id"] == primary_id), None)
            if main is None:
                main = max(
                    metric_ev,
                    key=lambda e: abs((e.get("delta") or 0) / (abs(e.get("previous") or 0) or 1)),
                )
            unit = main.get("unit", "")
            claims.append(
                {
                    "id": "c1",
                    "text": (
                        f"{main['label']} 由 {_fmt(main.get('previous'), unit)} 变为 "
                        f"{_fmt(main.get('current'), unit)}（{_delta(main.get('delta'), unit)}），"
                        f"是本次议题最显著的变化。"
                    ),
                    "evidence_ids": [main["id"]],
                    "kind": "fact",
                    "confidence": 0.9,
                }
            )

            worst = None
            for ev in [main]:
                prev_map = {b["key"]: b["value"] for b in ev.get("prev_breakdown", [])}
                for b in ev.get("breakdown", []):
                    prev = prev_map.get(b["key"])
                    if prev is None:
                        continue
                    diff = b["value"] - prev
                    if worst is None or abs(diff) > abs(worst[2]):
                        worst = (ev, b, diff)
            if worst is not None:
                ev, b, diff = worst
                unit = ev.get("unit", "")
                claims.append(
                    {
                        "id": "c2",
                        "text": (
                            f"在 {ev['label']} 的 {ev['dimension']} 维度上，{b['key']} 由 "
                            f"{_fmt(b['value'] - diff, unit)} 变为 {_fmt(b['value'], unit)}"
                            f"（{_delta(diff, unit)}），是波动最大的分组。"
                        ),
                        "evidence_ids": [ev["id"]],
                        "kind": "inference",
                        "confidence": 0.78,
                    }
                )

        if decomp_ev:
            d = decomp_ev[0]["detail"]
            unit = d.get("unit", "")
            structural = d.get("structural_effect", 0.0)
            behavioural = d.get("behavioural_effect", 0.0)
            driver = "结构变化（人群构成）" if abs(structural) > abs(behavioural) else "行为变化（组内表现）"
            claims.append(
                {
                    "id": "c3",
                    "text": (
                        f"按 shift-share 分解，{driver}是主因：结构效应 {_delta(structural, unit)}，"
                        f"行为效应 {_delta(behavioural, unit)}，"
                        f"交互项 {_delta(d.get('interaction_effect', 0), unit)}。"
                    ),
                    "evidence_ids": [decomp_ev[0]["id"]],
                    "kind": "inference",
                    "confidence": 0.82,
                }
            )

        return {"claims": claims}

    # -- strategist ------------------------------------------------------
    def _strategist(self, payload: dict[str, Any]) -> dict[str, Any]:
        claims = payload.get("claims", [])
        text = " ".join(c.get("text", "") for c in claims)
        evidence_ids = sorted({eid for c in claims for eid in c.get("evidence_ids", [])})
        budget = float(payload.get("budget_cny", 30000))
        segments = payload.get("segments", {})

        templates: list[tuple[tuple[str, ...], list[dict[str, Any]]]] = [
            (
                ("复购", "二次"),
                [
                    {
                        "segment": "90-179 天未复购、历史购买≥2 单的会员",
                        "channel": "企业微信",
                        "offer": "文胸品类 8 折复购券（限 7 天）",
                        "timing": "T+0 发放，T+7 回收",
                        "success_metric": "30 天内复购率",
                        "expected_lift": 0.022,
                    },
                    {
                        "segment": "近 90 天购买 1 次、客单低于品类中位数的会员",
                        "channel": "小程序",
                        "offer": "满 399 减 50 组合券（文胸+内裤）",
                        "timing": "周末两天集中投放",
                        "success_metric": "连带率与 60 天复购率",
                        "expected_lift": 0.016,
                    },
                ],
            ),
            (
                ("流失", "沉睡", "沉默"),
                [
                    {
                        "segment": "180 天以上无购买的沉睡会员",
                        "channel": "短信",
                        "offer": "满 299 减 60 唤醒券",
                        "timing": "分两批，间隔 14 天",
                        "success_metric": "14 天内唤醒率",
                        "expected_lift": 0.015,
                    },
                    {
                        "segment": "沉睡但历史客单位于前 25% 的会员",
                        "channel": "导购一对一",
                        "offer": "专属新品试穿 + 免费换码",
                        "timing": "两周内完成触达",
                        "success_metric": "30 天内回访购买率",
                        "expected_lift": 0.012,
                    },
                ],
            ),
            (
                ("退货",),
                [
                    {
                        "segment": "近 90 天发生过退货的会员",
                        "channel": "站内信 + 客服触达",
                        "offer": "免费换码 + 一对一尺码咨询",
                        "timing": "退货完成后 48 小时内",
                        "success_metric": "换码后 60 天留存率",
                        "expected_lift": 0.018,
                    }
                ],
            ),
            (
                ("客单", "连带", "件单"),
                [
                    {
                        "segment": "近 90 天有购买、客单低于中位数的会员",
                        "channel": "小程序",
                        "offer": "满 399 减 50 凑单券",
                        "timing": "周末两天集中投放",
                        "success_metric": "客单价提升幅度",
                        "expected_lift": 0.03,
                    },
                    {
                        "segment": "购买文胸未购买配套内裤的会员",
                        "channel": "企业微信",
                        "offer": "内裤第二件 5 折",
                        "timing": "购买后 7 天内",
                        "success_metric": "连带率",
                        "expected_lift": 0.02,
                    },
                ],
            ),
        ]

        picked: list[dict[str, Any]] = []
        for keys, group in templates:
            if any(k in text for k in keys):
                picked.extend(group)
        if not picked:
            picked = templates[0][1]
        picked = picked[:2]

        weights = [0.6, 0.4] if len(picked) == 2 else [1.0]
        actions = []
        for i, tpl in enumerate(picked, 1):
            actions.append(
                {
                    "id": f"a{i}",
                    "segment": tpl["segment"],
                    "channel": tpl["channel"],
                    "offer": tpl["offer"],
                    "timing": tpl["timing"],
                    "budget_cny": round(budget * weights[i - 1], 2),
                    "success_metric": tpl["success_metric"],
                    "expected_lift": tpl["expected_lift"],
                    "evidence_ids": evidence_ids[:3] or ["e1"],
                }
            )
        return {"actions": actions, "notes": {"segment_pool": segments}}

    # -- critic ----------------------------------------------------------
    def _critic(self, payload: dict[str, Any]) -> dict[str, Any]:
        claims = payload.get("claims", [])
        actions = payload.get("actions", [])
        known = set(payload.get("evidence_ids", []))
        max_budget = float(payload.get("max_budget_cny", 50000))

        def fail(code: str, reason: str, suggestion: str, targets: list[str] | None = None):
            return {
                "verdict": "fail",
                "critiques": [
                    {
                        "id": f"cr-{payload.get('round', 1)}",
                        "target_claim_ids": targets or [],
                        "failure_code": code,
                        "reason": reason,
                        "suggestion": suggestion,
                        "round": int(payload.get("round", 1)),
                    }
                ],
            }

        if len(claims) < 2:
            return fail("insufficient_evidence", "结论数量不足，无法支撑一个增长方案。", "补充至少两个维度的证据后再下结论。")

        orphans = [c["id"] for c in claims if not set(c.get("evidence_ids", [])) <= known]
        if orphans:
            return fail(
                "insufficient_evidence",
                f"结论 {orphans} 引用了不存在的证据 id。",
                "回到取证阶段补齐证据，或删除无法支撑的结论。",
                orphans,
            )

        if not actions:
            return fail("no_action", "方案没有任何可执行动作。", "至少给出一个包含人群、渠道、时点与指标的动作为。")

        missing = [a["id"] for a in actions if not a.get("success_metric")]
        if missing:
            return fail("no_action", f"动作 {missing} 缺少成功指标。", "为每个动作补一个可测量的指标。", [])

        total = sum(float(a.get("budget_cny", 0)) for a in actions)
        if total > max_budget:
            return fail(
                "cost_overrun",
                f"动作预算合计 {total:.0f} 元，超过上限 {max_budget:.0f} 元。",
                "削减预算或减少动作数量。",
            )

        return {"verdict": "pass", "critiques": []}
