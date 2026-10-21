"""Offline evaluation harness.

Runs every case against the real warehouse with the deterministic provider and
writes evals/report.md. All numbers in the report come from this run -- nothing
is hand-written.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from membergraph.orchestrator import Orchestrator, RunConfig  # noqa: E402

DATA = ROOT / "data" / "fixtures"


def check(plan, expect: dict) -> list[str]:
    failures = []
    if len(plan.evidence) < expect.get("min_evidence", 0):
        failures.append(f"evidence {len(plan.evidence)} < {expect['min_evidence']}")
    if len(plan.claims) < expect.get("min_claims", 0):
        failures.append(f"claims {len(plan.claims)} < {expect['min_claims']}")
    if len(plan.actions) < expect.get("min_actions", 0):
        failures.append(f"actions {len(plan.actions)} < {expect['min_actions']}")
    blocking = sum(1 for i in plan.compliance if i.severity == "block")
    if blocking > expect.get("max_blocking", 0):
        failures.append(f"blocking issues {blocking} > {expect['max_blocking']}")
    if plan.orphan_claims():
        failures.append(f"orphan claims: {plan.orphan_claims()}")
    if plan.degraded != expect.get("degraded", False):
        failures.append(f"degraded={plan.degraded} expected {expect.get('degraded')}")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "evals" / "runs"))
    ap.add_argument("--only", default="", help="run a single case id")
    args = ap.parse_args()

    spec = yaml.safe_load((ROOT / "evals" / "cases.yaml").read_text(encoding="utf-8"))
    cases = spec["cases"]
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]

    results = []
    started = time.perf_counter()

    for case in cases:
        out = Path(args.out) / case["id"]
        cfg = RunConfig(
            topic=case["topic"],
            provider="fake",
            out_dir=out,
            budget_cny=float(case.get("budget_cny", 30000)),
            max_tool_calls=int(case.get("max_tool_calls", 30)),
        )
        t0 = time.perf_counter()
        plan = Orchestrator(DATA, cfg).run()
        elapsed = time.perf_counter() - t0
        failures = check(plan, case.get("expect", {}))
        results.append(
            {
                "id": case["id"],
                "topic": case["topic"],
                "passed": not failures,
                "failures": failures,
                "evidence": len(plan.evidence),
                "claims": len(plan.claims),
                "actions": len(plan.actions),
                "critiques": len(plan.critiques),
                "blocking": sum(1 for i in plan.compliance if i.severity == "block"),
                "warnings": sum(1 for i in plan.compliance if i.severity == "warn"),
                "degraded": plan.degraded,
                "degrade_reason": plan.degrade_reason,
                "elapsed_s": round(elapsed, 3),
                "cost_usd": plan.budget.get("spent_usd", 0),
                "tool_calls": plan.budget.get("tool_calls", 0),
                "orphan": len(plan.orphan_claims()),
            }
        )

    total_s = time.perf_counter() - started
    passed = sum(1 for r in results if r["passed"])

    lines = [
        "# membergraph 离线评测报告",
        "",
        f"> 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"> 数据：`data/fixtures`（seed 20261021）· provider：`fake`（确定性规则引擎）",
        f"> 用例：{len(results)} · 通过：{passed}/{len(results)} · 总耗时：{total_s:.1f}s",
        "",
        "## 结果",
        "",
        "| case | 议题 | 证据 | 结论 | 动作 | 阻断 | 降级 | 耗时 | 结果 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        mark = "✅" if r["passed"] else "❌"
        lines.append(
            f"| `{r['id']}` | {r['topic']} | {r['evidence']} | {r['claims']} | {r['actions']} | "
            f"{r['blocking']} | {r['degraded']} | {r['elapsed_s']}s | {mark} |"
        )

    failures = [r for r in results if not r["passed"]]
    lines += ["", "## 失败明细", ""]
    if failures:
        for r in failures:
            lines.append(f"- `{r['id']}`：{'；'.join(r['failures'])}")
    else:
        lines.append("无。")

    lines += [
        "",
        "## 聚合指标",
        "",
        f"- 证据覆盖率：{sum(1 for r in results if r['orphan'] == 0)}/{len(results)} 个用例无孤儿结论",
        f"- 平均单例耗时：{sum(r['elapsed_s'] for r in results) / len(results):.3f}s",
        f"- 平均工具调用：{sum(r['tool_calls'] for r in results) / len(results):.1f} 次",
        f"- LLM 成本：${sum(r['cost_usd'] for r in results):.4f}（fake provider 固定费率，仅用于验证计费链路）",
        "",
        "## 关于 provider=fake",
        "",
        "本报告验证的是**编排、证据账本、预算降级、合规闸门**这些确定性机制，",
        "不评估任何真实模型的推理质量。fake provider 的数字全部来自真实查询，",
        "只有“决策”（问哪些子问题、归因到哪个维度、选哪个打法）由规则替代。",
        "",
    ]

    (ROOT / "evals" / "report.md").write_text("\n".join(lines), encoding="utf-8")
    (ROOT / "evals" / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n".join(lines[:14]))
    print(f"\nwritten: evals/report.md  ({passed}/{len(results)} passed)")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
