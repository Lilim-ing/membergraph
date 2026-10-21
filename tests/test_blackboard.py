import pytest

from membergraph.blackboard import Blackboard


def test_write_creates_new_revision_and_keeps_history():
    bb = Blackboard("run-1")
    bb.write("claims", [{"id": "c1"}], "diagnostician")
    bb.write("claims", [{"id": "c1"}, {"id": "c2"}], "diagnostician")

    assert bb.read("claims") == [{"id": "c1"}, {"id": "c2"}]
    assert len(bb.history("claims")) == 2
    assert bb.revisions()["claims"] == 2


def test_append_is_additive_and_versioned():
    bb = Blackboard("run-2")
    bb.append("evidence", {"id": "e1"}, "analyst")
    bb.append("evidence", {"id": "e2"}, "analyst")

    values = bb.read_list("evidence")
    assert [v["id"] for v in values] == ["e1", "e2"]
    assert bb.revisions()["evidence"] == 2


def test_append_rejects_non_list_key():
    bb = Blackboard("run-3")
    bb.write("topic", "hello", "orchestrator")
    with pytest.raises(TypeError):
        bb.append("topic", "x", "orchestrator")


def test_snapshot_is_isolated_from_later_writes():
    bb = Blackboard("run-4")
    bb.write("topic", "a", "orchestrator")
    snap = bb.snapshot()
    bb.write("topic", "b", "orchestrator")
    assert snap["topic"] == "a"
    assert bb.read("topic") == "b"
