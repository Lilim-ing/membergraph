"""Small shared helpers."""

from __future__ import annotations

from datetime import date, timedelta


def month_window(as_of: str) -> tuple[dict[str, str], dict[str, str]]:
    """Return (current_month, previous_month) windows ending at as_of."""
    d = date.fromisoformat(as_of)
    cur_start = d.replace(day=1)
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    return (
        {"start": cur_start.isoformat(), "end": d.isoformat()},
        {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
    )


def fmt_value(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "%":
        return f"{value * 100:.2f}%"
    if unit == "元":
        return f"{value:,.0f}元"
    return f"{value:.2f}"


def fmt_delta(delta: float | None, unit: str) -> str:
    if delta is None:
        return "n/a"
    if unit == "%":
        return f"{delta * 100:+.2f}pct"
    if unit == "元":
        return f"{delta:+,.0f}元"
    return f"{delta:+.2f}"
