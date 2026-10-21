"""Deterministic compliance gate.

Rules, not prompts. A prompt asking the model to "avoid absolute claims" is a
suggestion; a regex that blocks the plan is a control.
"""

from __future__ import annotations

import re
from collections import Counter

from ..blackboard import Blackboard
from ..contracts import ComplianceIssue
from .base import AgentContext, BaseAgent

ABSOLUTE = re.compile(r"(最好|最强|第一品牌|唯一|100%|保证|绝对|永久|零风险|稳赚)")
PII_MOBILE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
PII_ID = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
DISCOUNT = re.compile(r"(\d(?:\.\d)?)\s*折")

MAX_LIFT = 0.12          # anything above 12pct absolute lift is not credible
MIN_DISCOUNT = 5.0       # below 5折 the offer is assumed to breach cost line
MAX_PER_SEGMENT = 2      # frequency cap within one plan


class Compliance(BaseAgent):
    name = "compliance"
    role = "compliance"
    system = ""

    def run(self, ctx: AgentContext, bb: Blackboard, **kwargs) -> list[ComplianceIssue]:
        claims = bb.read_list("claims")
        actions = bb.read_list("actions")
        known = {e["id"] for e in bb.read_list("evidence")}
        issues: list[ComplianceIssue] = []

        for c in claims:
            missing = set(c.get("evidence_ids", [])) - known
            if missing:
                issues.append(
                    ComplianceIssue(
                        code="orphan_claim",
                        detail=f"结论 {c['id']} 引用了不存在的证据 {sorted(missing)}",
                    )
                )

        if not actions:
            issues.append(ComplianceIssue(code="no_action", detail="方案没有任何可执行动作"))

        for a in actions:
            text = f"{a.get('segment', '')} {a.get('offer', '')} {a.get('timing', '')}"
            if ABSOLUTE.search(text):
                issues.append(
                    ComplianceIssue(code="absolute_claim", detail=f"动作 {a['id']} 含绝对化表述：{ABSOLUTE.search(text).group(0)}")
                )
            if PII_MOBILE.search(text) or PII_ID.search(text):
                issues.append(ComplianceIssue(code="pii", detail=f"动作 {a['id']} 疑似包含个人敏感信息"))
            m = DISCOUNT.search(a.get("offer", ""))
            if m and float(m.group(1)) < MIN_DISCOUNT:
                issues.append(
                    ComplianceIssue(
                        code="discount_floor",
                        detail=f"动作 {a['id']} 折扣 {m.group(1)} 折低于 {MIN_DISCOUNT} 折底线",
                    )
                )
            lift = a.get("expected_lift")
            if lift is not None and lift > MAX_LIFT:
                issues.append(
                    ComplianceIssue(
                        code="overclaim_lift",
                        detail=f"动作 {a['id']} 预期提升 {lift:.1%} 超出 {MAX_LIFT:.0%} 的合理上限",
                    )
                )

        for segment, count in Counter(a.get("segment") for a in actions).items():
            if segment and count > MAX_PER_SEGMENT:
                issues.append(
                    ComplianceIssue(
                        code="frequency_cap",
                        detail=f"人群「{segment}」在同一方案中出现 {count} 次，超过频控上限 {MAX_PER_SEGMENT}",
                        severity="warn",
                    )
                )

        bb.write("compliance", [i.model_dump() for i in issues], self.name)
        ctx.tracer.emit(
            "compliance",
            agent=self.name,
            issues=len(issues),
            blocking=sum(1 for i in issues if i.severity == "block"),
        )
        return issues
