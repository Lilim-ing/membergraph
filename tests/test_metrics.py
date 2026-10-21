import pytest

from membergraph.tools.metrics import METRIC_META, compute_metric

SEP = ("2026-09-01", "2026-09-30")
AUG = ("2026-08-01", "2026-08-31")


@pytest.mark.parametrize("metric", sorted(METRIC_META))
def test_every_metric_runs_on_its_first_dimension(warehouse, metric):
    dim = METRIC_META[metric]["dims"][0]
    res = compute_metric(warehouse, metric, *SEP, dim)
    assert res["metric"] == metric
    assert res["value"] is not None
    assert res["breakdown"], f"{metric} returned no breakdown"


def test_dimension_query_returns_overall_value_not_a_group(warehouse):
    """Regression: the first breakdown row used to be returned as the total."""
    grouped = compute_metric(warehouse, "return_rate", *SEP, "category")
    overall = compute_metric(warehouse, "return_rate", *SEP, None)
    assert grouped["value"] == pytest.approx(overall["value"], rel=1e-9)
    assert len(grouped["breakdown"]) >= 3
    assert grouped["n"] == overall["n"]


def test_unsupported_dimension_is_rejected(warehouse):
    with pytest.raises(ValueError):
        compute_metric(warehouse, "return_rate", *SEP, "channel")


def test_repurchase_uses_rolling_window_not_immature_cohort(warehouse):
    """Regression: a first-order cohort in September has not had 90 days yet,
    so its repurchase rate collapses toward zero. The rolling definition keeps
    consecutive months comparable."""
    sep = compute_metric(warehouse, "repurchase_rate_90d", *SEP)
    aug = compute_metric(warehouse, "repurchase_rate_90d", *AUG)
    assert 0.05 < sep["value"] < 0.35
    assert abs(sep["value"] - aug["value"]) < 0.05

    # the same definition must not depend on the start of the window
    sep_only_end = compute_metric(warehouse, "repurchase_rate_90d", "2026-01-01", *SEP[1:])
    assert sep["value"] == pytest.approx(sep_only_end["value"], rel=1e-9)


def test_metric_definition_travels_with_the_number(warehouse):
    res = compute_metric(warehouse, "aov", *SEP)
    assert "已支付GMV" in res["definition"]
    assert res["unit"] == "元"
