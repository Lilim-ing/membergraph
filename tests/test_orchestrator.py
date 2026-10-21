import json
from pathlib import Path

from membergraph.observability.replay import render_trace
from membergraph.orchestrator import Orchestrator, RunConfig

TOPIC = "9月复购率环比下滑，给出一个30天挽回方案"


def _run(data_dir: Path, out: Path, **overrides) -> object:
    cfg = RunConfig(topic=TOPIC, provider="fake", out_dir=out, **overrides)
    return Orchestrator(data_dir, cfg).run()


def test_end_to_end_offline_run(data_dir, tmp_path):
    out = tmp_path / "run"
    plan = _run(data_dir, out)

    assert len(plan.evidence) >= 3
    assert len(plan.claims) >= 2
    assert len(plan.actions) >= 1
    assert plan.orphan_claims() == []
    assert plan.blocked is False
    assert plan.degraded is False
    assert plan.finished_at

    for name in ("plan.md", "plan.json", "trace.jsonl", "blackboard.json"):
        assert (out / name).exists(), name

    text = (out / "plan.md").read_text(encoding="utf-8")
    assert "## 一、核心结论" in text
    assert "## 四、评审记录" in text


def test_every_claim_points_at_real_evidence(data_dir, tmp_path):
    plan = _run(data_dir, tmp_path / "run")
    known = set(plan.evidence_index())
    for claim in plan.claims:
        assert set(claim.evidence_ids) <= known
    for action in plan.actions:
        assert set(action.evidence_ids) <= known


def test_budget_exhaustion_degrades_honestly(data_dir, tmp_path):
    out = tmp_path / "degraded"
    plan = _run(data_dir, out, max_tool_calls=3)

    assert plan.degraded is True
    assert "预算" in plan.degrade_reason
    assert len(plan.evidence) >= 1  # partial work is kept, not discarded

    events = [json.loads(line) for line in (out / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e["type"] == "degrade" for e in events)


def test_blackboard_keeps_revision_history(data_dir, tmp_path):
    out = tmp_path / "run"
    _run(data_dir, out)
    board = json.loads((out / "blackboard.json").read_text(encoding="utf-8"))
    assert board["evidence"]["revision"] >= 3
    assert board["claims"]["revision"] >= 1


def test_trace_is_replayable(data_dir, tmp_path):
    out = tmp_path / "run"
    _run(data_dir, out)
    html = render_trace(out / "trace.jsonl", out / "replay.html")
    content = html.read_text(encoding="utf-8")
    assert "EVENTS =" in content
    assert "lane-name" in content
    assert len(content) > 4000


def test_same_input_same_evidence_values(data_dir, tmp_path):
    """Two runs must agree on the numbers; only ids and timings differ."""
    a = _run(data_dir, tmp_path / "a")
    b = _run(data_dir, tmp_path / "b")
    assert len(a.evidence) == len(b.evidence)
    assert [round(e.value or 0, 6) for e in a.evidence] == [round(e.value or 0, 6) for e in b.evidence]
    assert a.run_id != b.run_id
