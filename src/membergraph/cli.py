"""Command line entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .observability.replay import render_trace
from .orchestrator import Orchestrator, RunConfig

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

app = typer.Typer(add_completion=False, help="membergraph · 会员增长多智能体工作台")
console = Console()

DEFAULT_DATA = Path(__file__).resolve().parents[2] / "data" / "fixtures"


def resolve_data(explicit: str = "") -> Path:
    """Find the fixtures directory, or explain how to fix it.

    `pip install -e .` puts the package next to `data/`, so the first candidate
    works. A plain `pip install .` copies only the package into site-packages,
    so fall back to the current working directory before giving up.
    """
    if explicit:
        path = Path(explicit)
        if (path / "members.parquet").exists():
            return path
        raise typer.BadParameter(f"{path} 下没有 fixtures（缺少 members.parquet）")

    candidates = [
        DEFAULT_DATA,
        Path.cwd() / "data" / "fixtures",
        Path.cwd() / "fixtures",
    ]
    for candidate in candidates:
        if (candidate / "members.parquet").exists():
            return candidate

    tried = "\n".join(f"    - {c}" for c in candidates)
    raise typer.BadParameter(
        "找不到本地 fixtures。已尝试：\n"
        f"{tried}\n"
        "  解决方式：\n"
        '    1) 在仓库根目录用 editable 安装：pip install -e ".[dev]"\n'
        "    2) 或在仓库根目录下运行（会自动探测 ./data/fixtures）\n"
        "    3) 或显式指定：--data <fixtures 目录>"
    )


@app.command()
def run(
    topic: str = typer.Argument(..., help="业务议题，例如：9月复购率环比下滑，给出30天挽回方案"),
    provider: str = typer.Option("fake", help="fake | deepseek"),
    as_of: str = typer.Option("2026-09-30", help="观察截止日 YYYY-MM-DD"),
    out: str = typer.Option("runs/demo", "-o", "--out", help="产物目录"),
    budget_usd: float = typer.Option(0.60, help="LLM 成本上限（美元）"),
    budget_cny: float = typer.Option(30_000, help="方案预算上限（元）"),
    max_tool_calls: int = typer.Option(30, help="工具调用次数上限"),
    data: str = typer.Option("", help="fixtures 目录，默认使用仓库内置数据"),
    model: str = typer.Option("", help="模型名，仅 provider=deepseek 时生效"),
) -> None:
    """运行一次多智能体协作。"""
    data_dir = resolve_data(data)
    cfg = RunConfig(
        topic=topic,
        provider=provider,
        as_of=as_of,
        out_dir=Path(out),
        budget_usd=budget_usd,
        budget_cny=budget_cny,
        max_tool_calls=max_tool_calls,
        model=model or None,
    )
    console.print(f"[dim]provider={provider} · as_of={as_of} · data={data_dir}[/dim]")
    plan = Orchestrator(data_dir, cfg).run()

    table = Table(title="运行结果", show_header=True, header_style="bold")
    table.add_column("项")
    table.add_column("值")
    table.add_row("结论 / 证据 / 动作", f"{len(plan.claims)} / {len(plan.evidence)} / {len(plan.actions)}")
    cost_note = "（模拟，未调用模型）" if provider == "fake" else ""
    table.add_row(
        "预算消耗",
        f"${plan.budget.get('spent_usd', 0):.4f}{cost_note} · 工具 {plan.budget.get('tool_calls', 0)} 次",
    )
    table.add_row("耗时", f"{plan.budget.get('elapsed_ms', 0) / 1000:.1f}s")
    table.add_row("降级", plan.degrade_reason or "否")
    table.add_row("合规阻断", str(sum(1 for i in plan.compliance if i.severity == "block")))
    console.print(table)

    for c in plan.claims:
        console.print(f"  · {c.text} [dim]\\[{','.join(c.evidence_ids)}][/dim]")
    for a in plan.actions:
        console.print(f"  → {a.segment} / {a.channel} / {a.offer} / ¥{a.budget_cny:,.0f}")

    console.print(
        Panel(
            f"产物：{out}/plan.md · plan.json · trace.jsonl\n"
            f"回放：python -m membergraph.cli replay {out}/trace.jsonl -o {out}/replay.html",
            title="下一步",
            border_style="dim",
        )
    )
    if plan.blocked:
        raise typer.Exit(code=2)


@app.command()
def replay(
    trace: str = typer.Argument(..., help="trace.jsonl 路径"),
    out: str = typer.Option("replay.html", "-o", "--out", help="输出 HTML"),
) -> None:
    """把 trace 渲染为单文件时间轴页面。"""
    path = render_trace(trace, out)
    console.print(f"[green]已生成[/green] {path.resolve()}")


@app.command()
def demo(
    out: str = typer.Option("runs/demo", "-o", "--out", help="产物目录"),
) -> None:
    """跑三个典型议题，验证链路。"""
    topics = [
        "9月复购率环比下滑，给出一个30天挽回方案",
        "近半年沉睡会员占比上升，如何召回",
        "客单价增长但连带率下降，问题出在哪",
    ]
    for i, topic in enumerate(topics, 1):
        sub = Path(out) / f"case{i}"
        console.print(f"\n[bold]== 案例 {i} ==[/bold] {topic}")
        plan = Orchestrator(resolve_data(), RunConfig(topic=topic, out_dir=sub)).run()
        console.print(
            f"  结论 {len(plan.claims)} · 证据 {len(plan.evidence)} · 动作 {len(plan.actions)}"
            f" · 降级 {plan.degraded} · 阻断 {sum(1 for x in plan.compliance if x.severity == 'block')}"
        )
        render_trace(sub / "trace.jsonl", sub / "replay.html")
    console.print(f"\n[green]全部完成[/green] 产物在 {Path(out).resolve()}")


if __name__ == "__main__":
    app()
