"""Budget accounting.

A production agent has to fail gracefully. When the budget is exhausted the
orchestrator does not crash and does not silently keep spending: it degrades
(cuts branches, skips optional critique rounds) and marks the output as
degraded, with a reason.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


class BudgetExceeded(RuntimeError):
    def __init__(self, kind: str, limit: float, used: float) -> None:
        super().__init__(f"budget exceeded: {kind} limit={limit} used={used:.4f}")
        self.kind = kind
        self.limit = limit
        self.used = used


@dataclass
class Budget:
    max_usd: float = 0.60
    max_tool_calls: int = 30
    max_wall_ms: int = 120_000

    spent_usd: float = 0.0
    tool_calls: int = 0
    tokens: int = 0
    _started: float = field(default_factory=time.perf_counter, repr=False)

    # -- charges ---------------------------------------------------------
    def charge_llm(self, cost_usd: float, tokens: int) -> None:
        if self.spent_usd + cost_usd > self.max_usd:
            raise BudgetExceeded("usd", self.max_usd, self.spent_usd + cost_usd)
        self.spent_usd += cost_usd
        self.tokens += tokens

    def charge_tool(self) -> None:
        if self.tool_calls + 1 > self.max_tool_calls:
            raise BudgetExceeded("tool_calls", self.max_tool_calls, self.tool_calls + 1)
        self.tool_calls += 1

    # -- state -----------------------------------------------------------
    @property
    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self._started) * 1000

    def check_wall(self) -> None:
        if self.elapsed_ms > self.max_wall_ms:
            raise BudgetExceeded("wall_ms", self.max_wall_ms, self.elapsed_ms)

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.max_usd - self.spent_usd)

    def level(self) -> int:
        """0 = healthy, 1 = above 80%, 2 = exhausted."""
        if self.spent_usd >= self.max_usd or self.tool_calls >= self.max_tool_calls:
            return 2
        if self.spent_usd / self.max_usd >= 0.8 or self.elapsed_ms >= self.max_wall_ms * 0.8:
            return 1
        return 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "spent_usd": round(self.spent_usd, 6),
            "max_usd": self.max_usd,
            "tool_calls": self.tool_calls,
            "max_tool_calls": self.max_tool_calls,
            "tokens": self.tokens,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "max_wall_ms": self.max_wall_ms,
            "level": self.level(),
        }
