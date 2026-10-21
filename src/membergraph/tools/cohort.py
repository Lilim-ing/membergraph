"""Cohort retention and shift-share decomposition."""

from __future__ import annotations

from typing import Any

from .warehouse import Warehouse


def cohort_retention(w: Warehouse, cohort_month: str, periods: int = 6) -> dict[str, Any]:
    """Retention of the members whose first paid order falls in `cohort_month`.

    Period 0 is the acquisition window itself, so its rate is 1.0 by
    construction -- that is stated rather than hidden.
    """
    size = w.scalar(
        """
        WITH fo AS (
          SELECT member_id, MIN(CAST(order_time AS DATE)) AS d
          FROM orders WHERE status <> 'refunded' GROUP BY member_id
        )
        SELECT COUNT(*) FROM fo WHERE STRFTIME(d, '%Y-%m') = ?
        """,
        [cohort_month],
    )
    if not size:
        return {"cohort": cohort_month, "size": 0, "periods": [], "periods_requested": periods}

    df = w.query(
        """
        WITH fo AS (
          SELECT member_id, MIN(CAST(order_time AS DATE)) AS d
          FROM orders WHERE status <> 'refunded' GROUP BY member_id
        ),
        coh AS (SELECT member_id, d FROM fo WHERE STRFTIME(d, '%Y-%m') = ?),
        buys AS (
          SELECT o.member_id, DATE_DIFF('day', c.d, CAST(o.order_time AS DATE)) AS off
          FROM orders o JOIN coh c USING(member_id)
          WHERE o.status <> 'refunded'
        )
        SELECT FLOOR(off / 30.0) AS period, COUNT(DISTINCT member_id) AS n
        FROM buys WHERE off >= 0 AND off < ?
        GROUP BY 1 ORDER BY 1
        """,
        [cohort_month, periods * 30],
    )
    got = {int(r["period"]): int(r["n"]) for _, r in df.iterrows()}
    series = [
        {"period": p, "members": got.get(p, 0), "rate": round(got.get(p, 0) / size, 4)}
        for p in range(periods)
    ]
    return {"cohort": cohort_month, "size": int(size), "periods": series}


DECOMP_SPECS: dict[str, dict[str, str]] = {
    "aov": {
        "num": "SUM(o.paid_amount)",
        "den": "COUNT(*)",
        "join": "FROM orders o JOIN members m USING(member_id)",
        "where": "o.status <> 'refunded'",
        "dims": "channel,member_level,city_tier",
        "unit": "元",
    },
    "upt": {
        "num": "SUM(i.qty)",
        "den": "COUNT(DISTINCT o.order_id)",
        "join": "FROM order_items i JOIN orders o USING(order_id)",
        "where": "o.status <> 'refunded'",
        "dims": "channel,category",
        "unit": "件/单",
    },
    "return_rate": {
        "num": "SUM(CASE WHEN i.is_returned = 1 THEN i.qty ELSE 0 END)",
        "den": "SUM(i.qty)",
        "join": "FROM order_items i JOIN orders o USING(order_id)",
        "where": "1 = 1",
        "dims": "category",
        "unit": "%",
    },
}


def decompose(
    w: Warehouse,
    metric: str,
    dimension: str,
    p0_start: str,
    p0_end: str,
    p1_start: str,
    p1_end: str,
) -> dict[str, Any]:
    """Shift-share decomposition of a ratio metric.

    total change = structural effect (mix shift) + behavioural effect
    (within-group change) + interaction residual.
    """
    spec = DECOMP_SPECS.get(metric)
    if spec is None:
        raise ValueError(f"decomposition supports {sorted(DECOMP_SPECS)}, got {metric!r}")
    if dimension not in spec["dims"].split(","):
        raise ValueError(f"{metric} decomposition supports {spec['dims'].split(',')}")

    dim_expr = {"channel": "o.channel", "category": "i.category", "member_level": "m.member_level"}[dimension]
    base = f"""
        SELECT {dim_expr} AS k, {spec['num']} AS n, {spec['den']} AS d
        {spec['join']}
        WHERE {spec['where']} AND CAST(o.order_time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        GROUP BY 1
    """
    a = w.query(base, [p0_start, p0_end]).set_index("k")
    b = w.query(base, [p1_start, p1_end]).set_index("k")
    keys = sorted(set(a.index) | set(b.index))

    A_n, A_d = float(a["n"].sum()), float(a["d"].sum())
    B_n, B_d = float(b["n"].sum()), float(b["d"].sum())
    v0_total = A_n / A_d if A_d else 0.0
    v1_total = B_n / B_d if B_d else 0.0

    structural = behavioural = 0.0
    rows = []
    for k in keys:
        n0 = float(a["n"].get(k, 0.0))
        d0 = float(a["d"].get(k, 0.0))
        n1 = float(b["n"].get(k, 0.0))
        d1 = float(b["d"].get(k, 0.0))
        v0 = n0 / d0 if d0 else 0.0
        v1 = n1 / d1 if d1 else 0.0
        w0 = d0 / A_d if A_d else 0.0
        w1 = d1 / B_d if B_d else 0.0
        s = (w1 - w0) * v0
        be = w0 * (v1 - v0)
        structural += s
        behavioural += be
        rows.append(
            {
                "key": str(k),
                "base_value": round(v0, 6),
                "curr_value": round(v1, 6),
                "base_share": round(w0, 6),
                "curr_share": round(w1, 6),
                "structural_effect": round(s, 6),
                "behavioural_effect": round(be, 6),
                "total_effect": round(w1 * v1 - w0 * v0, 6),
            }
        )

    total = v1_total - v0_total
    interaction = total - structural - behavioural
    rows.sort(key=lambda r: abs(r["total_effect"]), reverse=True)
    return {
        "metric": metric,
        "dimension": dimension,
        "base_period": [p0_start, p0_end],
        "curr_period": [p1_start, p1_end],
        "base_value": round(v0_total, 6),
        "curr_value": round(v1_total, 6),
        "total_change": round(total, 6),
        "structural_effect": round(structural, 6),
        "behavioural_effect": round(behavioural, 6),
        "interaction_effect": round(interaction, 6),
        "unit": spec["unit"],
        "contributors": rows,
    }
