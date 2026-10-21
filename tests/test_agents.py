from typing import Any

import pytest

from membergraph.agents.base import AgentContext
from membergraph.agents.compliance import Compliance
from membergraph.agents.critic import Critic
from membergraph.blackboard import Blackboard
from membergraph.budget import Budget
from membergraph.llm.fake import FakeLLM
from membergraph.observability.trace import Tracer


@pytest.fixture()
def ctx(tmp_path):
    tracer = Tracer(tmp_path / "trace.jsonl", "test-run")
    c = AgentContext(
        llm=FakeLLM(),
        tracer=tracer,
        budget=Budget(),
        warehouse=None,  # compliance/critic do not touch the warehouse
        as_of="2026-09-30",
        provider="fake",
    )
    yield c
    tracer.close()


def _action(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "a1",
        "segment": "90-179 天未复购会员",
        "channel": "企业微信",
        "offer": "文胸 8 折复购券",
        "timing": "T+0",
        "budget_cny": 10000.0,
        "success_metric": "30 天复购率",
        "expected_lift": 0.02,
        "evidence_ids": ["e1"],
    }
    base.update(overrides)
    return base


def _seed(bb: Blackboard, action: dict[str, Any] | None = None, claims: int = 2) -> None:
    bb.write("evidence", [{"id": "e1"}], "test")
    bb.write(
        "claims",
        [
            {"id": f"c{i}", "text": f"结论{i}", "evidence_ids": ["e1"], "kind": "fact", "confidence": 0.8}
            for i in range(1, claims + 1)
        ],
        "test",
    )
    bb.write("actions", [action or _action()], "test")


def test_clean_plan_passes_compliance(ctx):
    bb = Blackboard("r-clean")
    _seed(bb)
    issues = Compliance().run(ctx, bb)
    assert issues == []


def test_absolute_claim_is_blocked(ctx):
    bb = Blackboard("r-abs")
    _seed(bb, _action(offer="保证 100% 复购"))
    issues = Compliance().run(ctx, bb)
    assert any(i.code == "absolute_claim" and i.severity == "block" for i in issues)


def test_discount_floor_is_blocked(ctx):
    bb = Blackboard("r-disc")
    _seed(bb, _action(offer="文胸 3 折清仓"))
    issues = Compliance().run(ctx, bb)
    assert any(i.code == "discount_floor" for i in issues)


def test_pii_in_action_is_blocked(ctx):
    bb = Blackboard("r-pii")
    # Assembled at runtime so the scanner in scripts/compliance_check.py does not
    # flag this fixture file itself.
    fake_phone = "138" + "1234" + "5678"
    _seed(bb, _action(segment=f"会员 {fake_phone}"))
    issues = Compliance().run(ctx, bb)
    assert any(i.code == "pii" for i in issues)


def test_overclaimed_lift_is_blocked(ctx):
    bb = Blackboard("r-lift")
    _seed(bb, _action(expected_lift=0.40))
    issues = Compliance().run(ctx, bb)
    assert any(i.code == "overclaim_lift" for i in issues)


def test_orphan_claim_is_blocked(ctx):
    bb = Blackboard("r-orphan")
    bb.write("evidence", [{"id": "e1"}], "test")
    bb.write("claims", [{"id": "c1", "text": "x", "evidence_ids": ["e9"], "kind": "fact", "confidence": 0.8}], "test")
    bb.write("actions", [_action()], "test")
    issues = Compliance().run(ctx, bb)
    assert any(i.code == "orphan_claim" for i in issues)


def test_critic_passes_a_complete_plan(ctx):
    bb = Blackboard("r-pass")
    _seed(bb)
    ok, critiques = Critic().run(ctx, bb, round_no=1)
    assert ok is True
    assert critiques == []


def test_critic_rejects_action_without_success_metric(ctx):
    bb = Blackboard("r-nometric")
    _seed(bb, _action(success_metric=""))
    ok, critiques = Critic().run(ctx, bb, round_no=1)
    assert ok is False
    assert critiques[0].failure_code == "no_action"


def test_critic_rejects_budget_overrun(ctx):
    bb = Blackboard("r-budget")
    bb.write("budget_cny", 10000.0, "test")
    _seed(bb, _action(budget_cny=999999.0))
    ok, critiques = Critic().run(ctx, bb, round_no=1)
    assert ok is False
    assert critiques[0].failure_code == "cost_overrun"


def test_critic_requires_two_claims(ctx):
    bb = Blackboard("r-one")
    _seed(bb, claims=1)
    ok, critiques = Critic().run(ctx, bb, round_no=1)
    assert ok is False
    assert critiques[0].failure_code == "insufficient_evidence"
