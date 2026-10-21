import pytest
from pydantic import ValidationError

from membergraph.contracts import Claim, Evidence, Plan


def _evidence(eid: str = "e1") -> Evidence:
    return Evidence(
        id=eid,
        kind="metric",
        query={"metric": "aov"},
        summary="客单价=287元",
        value=287.0,
        unit="元",
        rows=1,
        digest="abc123",
        created_by="analyst",
    )


def test_claim_requires_evidence():
    with pytest.raises(ValidationError):
        Claim(id="c1", text="复购在下滑", evidence_ids=[])


def test_orphan_claims_are_detected():
    plan = Plan(
        run_id="r1",
        topic="t",
        provider="fake",
        evidence=[_evidence("e1")],
        claims=[
            Claim(id="c1", text="grounded", evidence_ids=["e1"]),
            Claim(id="c2", text="ungrounded", evidence_ids=["e9"]),
        ],
    )
    assert plan.orphan_claims() == ["c2"]


def test_blocked_flag_only_counts_block_severity():
    plan = Plan(run_id="r1", topic="t", provider="fake")
    assert plan.blocked is False
    from membergraph.contracts import ComplianceIssue

    plan.compliance.append(ComplianceIssue(code="x", detail="warn only", severity="warn"))
    assert plan.blocked is False
    plan.compliance.append(ComplianceIssue(code="y", detail="block"))
    assert plan.blocked is True
