"""Metric definitions.

Every metric here states its numerator and denominator explicitly. "Repurchase
rate" is not a universal constant -- it is a definition, and the definition
travels with the number.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .warehouse import Warehouse

# Dimension name -> SQL expression, by scope.
DIM_MEMBER = {
    "member_level": "m.member_level",
    "city_tier": "m.city_tier",
    "age_band": "m.age_band",
    # Repurchase is a member-level metric, so the only defensible channel cut is
    # the channel the member registered through -- not the channel of each order.
    "register_channel": "m.register_channel",
}
DIM_ORDER = {"channel": "o.channel"}
DIM_CATEGORY = {"category": "i.category"}

METRIC_META: dict[str, dict[str, Any]] = {
    "repurchase_rate_90d": {
        "label": "90天复购率",
        "unit": "%",
        "definition": (
            "近90天内购买≥2次的会员 / 近90天内购买≥1次的会员。"
            "采用滚动窗口而非首单 cohort，避免近期 cohort 未走完观察期造成的右删失偏差"
        ),
        "dims": ["register_channel", "member_level", "city_tier", "age_band"],
        "kind": "rate",
    },
    "active_rate_30d": {
        "label": "30天活跃率",
        "unit": "%",
        "definition": "期末前30天内有购买或行为事件的会员 / 期初已注册会员",
        "dims": ["member_level", "city_tier", "age_band"],
        "kind": "rate",
    },
    "aov": {
        "label": "客单价",
        "unit": "元",
        "definition": "已支付GMV / 已支付订单数",
        "dims": ["channel", "member_level", "city_tier", "age_band"],
        "kind": "ratio",
    },
    "return_rate": {
        "label": "退货率",
        "unit": "%",
        "definition": "退货件数 / 销售件数",
        "dims": ["category"],
        "kind": "rate",
    },
    "churn_rate_180d": {
        "label": "180天流失率",
        "unit": "%",
        "definition": "期初有过购买、且期末前180天无购买的会员 / 期初有过购买的会员",
        "dims": ["member_level", "city_tier"],
        "kind": "rate",
    },
    "repeat_gmv_share": {
        "label": "复购会员GMV占比",
        "unit": "%",
        "definition": "期内下单≥2次的会员贡献GMV / 期内总GMV",
        "dims": ["member_level"],
        "kind": "rate",
    },
    "upt": {
        "label": "连带率",
        "unit": "件/单",
        "definition": "已支付件数 / 已支付订单数",
        "dims": ["channel", "category"],
        "kind": "ratio",
    },
    "discount_rate": {
        "label": "折扣率",
        "unit": "%",
        "definition": "折扣金额 / 吊牌金额",
        "dims": ["channel", "member_level"],
        "kind": "rate",
    },
}


def list_metrics() -> list[dict[str, Any]]:
    return [{"name": k, **v} for k, v in METRIC_META.items()]


def _finish(
    metric: str,
    df: pd.DataFrame,
    dim: str | None,
    start: str,
    end: str,
    total: float | None = None,
) -> dict[str, Any]:
    meta = METRIC_META[metric]
    if dim and not df.empty:
        value = float(df["v"].iloc[0]) if total is None else float(total)
        breakdown = [
            {"key": str(r["k"]), "value": round(float(r["v"]), 6)}
            for _, r in df.iterrows()
            if not pd.isna(r["v"])
        ]
    else:
        value = float(df["v"].iloc[0]) if not df.empty and not pd.isna(df["v"].iloc[0]) else 0.0
        breakdown = []
    return {
        "metric": metric,
        "label": meta["label"],
        "unit": meta["unit"],
        "definition": meta["definition"],
        "value": round(value, 6),
        "start": start,
        "end": end,
        "dimension": dim,
        "breakdown": breakdown,
        "n": int(len(df)),
    }


def _dim_pick(dim: str | None, scope: dict[str, str]) -> tuple[str, str]:
    """Return (select_fragment, group_fragment) for the given dimension."""
    if not dim:
        return "", ""
    if dim not in scope:
        raise ValueError(f"dimension {dim!r} not supported here; choose from {sorted(scope)}")
    expr = scope[dim]
    return f", {expr} AS k", " GROUP BY 1 ORDER BY 2 DESC"


def repurchase_rate(w: Warehouse, start: str, end: str, dim: str | None = None) -> dict:
    """Rolling 90-day repurchase.

    Deliberately NOT a first-order cohort metric: a cohort acquired last month
    has not had 90 days to repurchase, so its rate collapses toward zero for
    purely mechanical reasons (right censoring). The rolling window keeps the
    number comparable month over month.
    """
    sel, grp = _dim_pick(dim, DIM_MEMBER)
    cte = f"""
    WITH per AS (
      SELECT o.member_id, COUNT(*) AS n {sel}
      FROM orders o JOIN members m USING(member_id)
      WHERE o.status <> 'refunded'
        AND CAST(o.order_time AS DATE) BETWEEN CAST(? AS DATE) - INTERVAL 89 DAY AND CAST(? AS DATE)
      GROUP BY {'k, ' if dim else ''}o.member_id
    )
    """
    expr = "AVG(CASE WHEN n >= 2 THEN 1.0 ELSE 0.0 END)"
    sql = f"{cte} SELECT {'k, ' if dim else ''}{expr} AS v FROM per {grp}"
    df = w.query(sql, [end, end])
    return _finish("repurchase_rate_90d", df, dim, start, end)


def active_rate_30d(w: Warehouse, start: str, end: str, dim: str | None = None) -> dict:
    sel, grp = _dim_pick(dim, DIM_MEMBER)
    cte = f"""
    WITH base AS (
      SELECT m.member_id {sel} FROM members m
      WHERE CAST(m.register_date AS DATE) <= CAST(? AS DATE)
    ),
    act AS (
      SELECT DISTINCT member_id FROM orders
      WHERE status <> 'refunded' AND CAST(order_time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
      UNION
      SELECT DISTINCT member_id FROM behaviors
      WHERE CAST(event_time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
    ),
    joined AS (
      SELECT b.*, a.member_id AS hit FROM base b LEFT JOIN act a USING(member_id)
    )
    """
    expr = "AVG(CASE WHEN hit IS NULL THEN 0.0 ELSE 1.0 END)"
    sql = f"{cte} SELECT {'k, ' if dim else ''}{expr} AS v FROM joined {grp}"
    df = w.query(sql, [start, end, end, start, end])
    return _finish("active_rate_30d", df, dim, start, end)


def aov(w: Warehouse, start: str, end: str, dim: str | None = None) -> dict:
    sel, grp = _dim_pick(dim, {**DIM_ORDER, **DIM_MEMBER})
    cte = f"""
    WITH base AS (
      SELECT o.paid_amount {sel}
      FROM orders o JOIN members m USING(member_id)
      WHERE o.status <> 'refunded'
        AND CAST(o.order_time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
    )
    """
    expr = "SUM(paid_amount) / NULLIF(COUNT(*), 0)"
    sql = f"{cte} SELECT {'k, ' if dim else ''}{expr} AS v FROM base {grp}"
    df = w.query(sql, [start, end])
    return _finish("aov", df, dim, start, end)


def return_rate(w: Warehouse, start: str, end: str, dim: str | None = None) -> dict:
    sel, grp = _dim_pick(dim, DIM_CATEGORY)
    cte = f"""
    WITH base AS (
      SELECT i.qty, i.is_returned {sel}
      FROM order_items i JOIN orders o USING(order_id)
      WHERE CAST(o.order_time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
    )
    """
    expr = "SUM(CASE WHEN is_returned = 1 THEN qty ELSE 0 END) / NULLIF(SUM(qty), 0)"
    sql = f"{cte} SELECT {'k, ' if dim else ''}{expr} AS v FROM base {grp}"
    df = w.query(sql, [start, end])
    return _finish("return_rate", df, dim, start, end)


def churn_rate_180d(w: Warehouse, start: str, end: str, dim: str | None = None) -> dict:
    sel, grp = _dim_pick(dim, DIM_MEMBER)
    cte = f"""
    WITH base AS (
      SELECT m.member_id {sel} FROM members m
      WHERE CAST(m.register_date AS DATE) <= CAST(? AS DATE)
    ),
    lb AS (
      SELECT member_id, MAX(CAST(order_time AS DATE)) AS d
      FROM orders WHERE status <> 'refunded' GROUP BY member_id
    ),
    joined AS (
      SELECT b.member_id {', b.k' if dim else ''}, lb.d
      FROM base b JOIN lb USING(member_id)
    )
    """
    expr = "AVG(CASE WHEN DATE_DIFF('day', d, CAST(? AS DATE)) >= 180 THEN 1.0 ELSE 0.0 END)"
    if dim:
        sql = f"{cte} SELECT k, {expr} AS v FROM joined GROUP BY 1 ORDER BY 2 DESC"
        df = w.query(sql, [start, end])
    else:
        sql = f"{cte} SELECT {expr} AS v FROM joined"
        df = w.query(sql, [start, end])
    return _finish("churn_rate_180d", df, dim, start, end)


def repeat_gmv_share(w: Warehouse, start: str, end: str, dim: str | None = None) -> dict:
    sel, grp = _dim_pick(dim, DIM_MEMBER)
    cte = f"""
    WITH per AS (
      SELECT o.member_id, COUNT(*) AS n, SUM(o.paid_amount) AS gmv {sel}
      FROM orders o JOIN members m USING(member_id)
      WHERE o.status <> 'refunded'
        AND CAST(o.order_time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
      GROUP BY {'k, ' if dim else ''}o.member_id
    )
    """
    expr = "SUM(CASE WHEN n >= 2 THEN gmv ELSE 0 END) / NULLIF(SUM(gmv), 0)"
    sql = f"{cte} SELECT {'k, ' if dim else ''}{expr} AS v FROM per {grp}"
    df = w.query(sql, [start, end])
    return _finish("repeat_gmv_share", df, dim, start, end)


def upt(w: Warehouse, start: str, end: str, dim: str | None = None) -> dict:
    sel, grp = _dim_pick(dim, {**DIM_ORDER, **DIM_CATEGORY})
    cte = f"""
    WITH base AS (
      SELECT o.order_id, i.qty {sel}
      FROM order_items i JOIN orders o USING(order_id)
      WHERE o.status <> 'refunded'
        AND CAST(o.order_time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
    )
    """
    expr = "SUM(qty) / NULLIF(COUNT(DISTINCT order_id), 0)"
    sql = f"{cte} SELECT {'k, ' if dim else ''}{expr} AS v FROM base {grp}"
    df = w.query(sql, [start, end])
    return _finish("upt", df, dim, start, end)


def discount_rate(w: Warehouse, start: str, end: str, dim: str | None = None) -> dict:
    sel, grp = _dim_pick(dim, {**DIM_ORDER, **DIM_MEMBER})
    cte = f"""
    WITH base AS (
      SELECT o.discount_amount, o.gross_amount {sel}
      FROM orders o JOIN members m USING(member_id)
      WHERE o.status <> 'refunded'
        AND CAST(o.order_time AS DATE) BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
    )
    """
    expr = "SUM(discount_amount) / NULLIF(SUM(gross_amount), 0)"
    sql = f"{cte} SELECT {'k, ' if dim else ''}{expr} AS v FROM base {grp}"
    df = w.query(sql, [start, end])
    return _finish("discount_rate", df, dim, start, end)


COMPUTERS = {
    "repurchase_rate_90d": repurchase_rate,
    "active_rate_30d": active_rate_30d,
    "aov": aov,
    "return_rate": return_rate,
    "churn_rate_180d": churn_rate_180d,
    "repeat_gmv_share": repeat_gmv_share,
    "upt": upt,
    "discount_rate": discount_rate,
}


def compute_metric(
    w: Warehouse, metric: str, start: str, end: str, dim: str | None = None
) -> dict[str, Any]:
    """Compute a metric, optionally broken down by a dimension.

    When a dimension is requested the overall value is computed separately and
    attached as `value` -- a breakdown row is a group, never the total.
    """
    if metric not in COMPUTERS:
        raise ValueError(f"unknown metric {metric!r}; available: {sorted(COMPUTERS)}")
    if dim and dim not in METRIC_META[metric]["dims"]:
        raise ValueError(
            f"metric {metric!r} does not support dimension {dim!r}; "
            f"choose from {METRIC_META[metric]['dims']}"
        )
    if dim:
        grouped = COMPUTERS[metric](w, start, end, dim)
        overall = COMPUTERS[metric](w, start, end, None)
        grouped["value"] = overall["value"]
        grouped["n"] = overall["n"]
        grouped["groups"] = len(grouped["breakdown"])
        return grouped
    return COMPUTERS[metric](w, start, end, None)
