import pytest

from membergraph.budget import Budget, BudgetExceeded


def test_llm_charge_accumulates_and_raises_over_limit():
    b = Budget(max_usd=0.01, max_tool_calls=5)
    b.charge_llm(0.006, 100)
    assert b.spent_usd == pytest.approx(0.006)
    with pytest.raises(BudgetExceeded):
        b.charge_llm(0.005, 100)


def test_tool_calls_are_capped():
    b = Budget(max_tool_calls=2)
    b.charge_tool()
    b.charge_tool()
    with pytest.raises(BudgetExceeded):
        b.charge_tool()


def test_level_reports_warning_then_exhaustion():
    b = Budget(max_usd=1.0, max_tool_calls=10)
    assert b.level() == 0
    b.charge_llm(0.85, 10)
    assert b.level() == 1

    # Spending past max_usd is refused by charge_llm, so exhaustion is reached
    # through the tool-call budget instead.
    b2 = Budget(max_usd=10.0, max_tool_calls=1)
    b2.charge_tool()
    assert b2.level() == 2


def test_snapshot_is_json_safe():
    b = Budget(max_usd=1.0, max_tool_calls=3)
    b.charge_llm(0.1, 42)
    b.charge_tool()
    snap = b.snapshot()
    assert snap["tokens"] == 42
    assert snap["tool_calls"] == 1
    assert snap["level"] == 0
