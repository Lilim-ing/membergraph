"""Experiment sizing, campaign read-outs, and segment sizing."""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

from .warehouse import Warehouse


def sample_size(
    baseline: float, mde_abs: float, alpha: float = 0.05, power: float = 0.8
) -> dict[str, Any]:
    """Two-proportion sample size per group.

    baseline and mde_abs are absolute rates (0.12, 0.02), not percentages.
    """
    p1 = float(baseline)
    p2 = float(baseline) + float(mde_abs)
    if not (0.0 < p1 < 1.0) or not (0.0 < p2 < 1.0):
        raise ValueError("baseline and baseline+mde must both fall in (0, 1)")
    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    z_beta = NormalDist().inv_cdf(power)
    p_bar = (p1 + p2) / 2
    numerator = (
        z_alpha * math.sqrt(2 * p_bar * (1 - p_bar))
        + z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    ) ** 2
    per_group = math.ceil(numerator / (mde_abs**2))
    return {
        "baseline": round(p1, 6),
        "target": round(p2, 6),
        "mde_abs": round(mde_abs, 6),
        "mde_rel": round(mde_abs / p1, 4),
        "alpha": alpha,
        "power": power,
        "per_group": per_group,
        "total": per_group * 2,
    }


def achieved_power(n_per_group: int, p1: float, p2: float, alpha: float = 0.05) -> float:
    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    se = math.sqrt(p1 * (1 - p1) / n_per_group + p2 * (1 - p2) / n_per_group)
    if se == 0:
        return 1.0
    z = abs(p2 - p1) / se - z_alpha
    return round(NormalDist().cdf(z), 4)


def campaign_summary(w: Warehouse) -> dict[str, Any]:
    df = w.query(
        """
        SELECT campaign_id, treated, COUNT(*) AS n, SUM(converted) AS conv, SUM(revenue) AS rev
        FROM campaign_assignments GROUP BY 1, 2 ORDER BY 1, 2
        """
    )
    out = []
    for cid, g in df.groupby("campaign_id"):
        t = g[g["treated"] == 1]
        c = g[g["treated"] == 0]
        if t.empty or c.empty:
            continue
        n_t, n_c = int(t["n"].iloc[0]), int(c["n"].iloc[0])
        p_t = float(t["conv"].iloc[0]) / n_t
        p_c = float(c["conv"].iloc[0]) / n_c
        se = math.sqrt(p_t * (1 - p_t) / n_t + p_c * (1 - p_c) / n_c)
        z = (p_t - p_c) / se if se else 0.0
        p_value = 2 * (1 - NormalDist().cdf(abs(z)))
        out.append(
            {
                "campaign_id": cid,
                "n_treated": n_t,
                "n_control": n_c,
                "rate_treated": round(p_t, 4),
                "rate_control": round(p_c, 4),
                "lift_abs": round(p_t - p_c, 4),
                "lift_rel": round((p_t - p_c) / p_c, 4) if p_c else None,
                "z": round(z, 3),
                "p_value": round(p_value, 4),
                "revenue_treated": round(float(t["rev"].iloc[0]), 2),
                "revenue_control": round(float(c["rev"].iloc[0]), 2),
            }
        )
    return {"campaigns": out, "count": len(out)}


def segment_buckets(w: Warehouse, as_of: str) -> dict[str, Any]:
    """Observable segment sizes used by the strategist to pick a target group."""
    by_level = w.query(
        """
        SELECT m.member_level AS k, COUNT(*) AS members
        FROM members m WHERE CAST(m.register_date AS DATE) <= CAST(? AS DATE)
        GROUP BY 1 ORDER BY 2 DESC
        """,
        [as_of],
    )
    recency = w.query(
        """
        WITH lb AS (
          SELECT member_id, MAX(CAST(order_time AS DATE)) AS d
          FROM orders WHERE status <> 'refunded' GROUP BY member_id
        ),
        calc AS (
          SELECT m.member_id, lb.d, DATE_DIFF('day', lb.d, CAST(? AS DATE)) AS gap
          FROM members m LEFT JOIN lb USING(member_id)
          WHERE CAST(m.register_date AS DATE) <= CAST(? AS DATE)
        )
        SELECT
          CASE
            WHEN d IS NULL THEN 'never_purchased'
            WHEN gap < 30 THEN '0-29d'
            WHEN gap < 90 THEN '30-89d'
            WHEN gap < 180 THEN '90-179d'
            ELSE '180d+'
          END AS k,
          COUNT(*) AS members
        FROM calc
        GROUP BY 1 ORDER BY 1
        """,
        [as_of, as_of],
    )
    return {
        "as_of": as_of,
        "by_level": [
            {"key": str(r["k"]), "members": int(r["members"])} for _, r in by_level.iterrows()
        ],
        "by_recency": [
            {"key": str(r["k"]), "members": int(r["members"])} for _, r in recency.iterrows()
        ],
    }
