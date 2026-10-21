import pytest

from membergraph.tools.cohort import cohort_retention, decompose

AUG = ("2026-08-01", "2026-08-31")
SEP = ("2026-09-01", "2026-09-30")


def test_shift_share_components_sum_to_total(warehouse):
    res = decompose(warehouse, "aov", "channel", *AUG, *SEP)
    parts = res["structural_effect"] + res["behavioural_effect"] + res["interaction_effect"]
    assert parts == pytest.approx(res["total_change"], abs=1e-5)


def test_decomposition_lists_contributors_sorted_by_impact(warehouse):
    res = decompose(warehouse, "return_rate", "category", *AUG, *SEP)
    assert len(res["contributors"]) >= 3
    impacts = [abs(c["total_effect"]) for c in res["contributors"]]
    assert impacts == sorted(impacts, reverse=True)


def test_unsupported_metric_raises(warehouse):
    with pytest.raises(ValueError):
        decompose(warehouse, "repurchase_rate_90d", "channel", *AUG, *SEP)


def test_cohort_retention_period_zero_is_full(warehouse):
    res = cohort_retention(warehouse, "2026-03", periods=4)
    assert res["size"] > 0
    assert res["periods"][0]["rate"] == pytest.approx(1.0)
    # Retention is NOT asserted to be monotonic: a promo month inside a later
    # window can lift it, which is exactly what happens around 618 here.
    assert all(0.0 <= p["rate"] <= 1.0 for p in res["periods"])


def test_cohort_retention_handles_empty_cohort(warehouse):
    res = cohort_retention(warehouse, "1999-01", periods=3)
    assert res["size"] == 0
    assert res["periods"] == []
