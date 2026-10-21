"""Trace replay: turn a JSONL event log into a single self-contained HTML page."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

COLORS = {
    "run_start": "#6366f1",
    "plan": "#0ea5e9",
    "llm_call": "#3b82f6",
    "tool_call": "#10b981",
    "diagnose": "#8b5cf6",
    "strategize": "#f59e0b",
    "critique": "#f97316",
    "compliance": "#ec4899",
    "degrade": "#ef4444",
    "run_error": "#dc2626",
    "run_end": "#0f766e",
    "critique_exhausted": "#b45309",
}


def render_trace(trace_path: str | Path, out_path: str | Path) -> Path:
    events: list[dict[str, Any]] = []
    for line in Path(trace_path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))

    run_id = events[0].get("run_id", "unknown") if events else "unknown"
    topic = next((e.get("topic") for e in events if e.get("type") == "run_start"), "")
    total_ms = max((e.get("offset_ms", 0) for e in events), default=1) or 1
    agents = sorted({e.get("agent") or "orchestrator" for e in events})

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>membergraph trace · {run_id}</title>
<style>
  :root {{
    --bg:#f8fafc; --card:#ffffff; --ink:#0f172a; --muted:#64748b;
    --line:#e2e8f0; --accent:#4f46e5;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:32px 20px 64px; }}
  h1 {{ font-size:22px; margin:0 0 6px; font-weight:650; }}
  .sub {{ color:var(--muted); font-size:13px; font-family:ui-monospace,Menlo,Consolas,monospace; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:12px; margin:22px 0 26px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }}
  .card .k {{ font-size:11px; color:var(--muted); letter-spacing:.04em; text-transform:uppercase; }}
  .card .v {{ font-size:20px; font-weight:650; margin-top:4px; }}
  .board {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:18px 18px 8px; }}
  .lane {{ display:grid; grid-template-columns:130px 1fr; align-items:center; gap:10px; margin-bottom:12px; }}
  .lane-name {{ font-size:12px; font-family:ui-monospace,Menlo,Consolas,monospace; color:var(--muted); text-align:right; }}
  .track {{ position:relative; height:26px; background:#f1f5f9; border-radius:6px; }}
  .ev {{ position:absolute; top:9px; width:9px; height:9px; border-radius:50%; transform:translateX(-50%);
    cursor:pointer; border:2px solid #fff; box-shadow:0 0 0 1px rgba(15,23,42,.08); }}
  .ev:hover {{ transform:translateX(-50%) scale(1.5); }}
  .axis {{ display:flex; justify-content:space-between; color:var(--muted); font-size:11px; margin:2px 0 0 140px; }}
  .detail {{ margin-top:18px; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 18px; }}
  .detail h2 {{ font-size:13px; margin:0 0 10px; color:var(--muted); font-weight:600; letter-spacing:.04em; text-transform:uppercase; }}
  pre {{ margin:0; white-space:pre-wrap; word-break:break-word; font-size:12.5px; line-height:1.6;
    font-family:ui-monospace,Menlo,Consolas,monospace; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:14px; margin:0 0 18px; font-size:12px; color:var(--muted); }}
  .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:5px; }}
  .hint {{ color:var(--muted); font-size:12px; margin-top:10px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{_esc(topic) or "membergraph run"}</h1>
  <div class="sub">{_esc(run_id)} · {len(events)} events · {total_ms/1000:.1f}s</div>

  <div class="cards" id="cards"></div>
  <div class="legend" id="legend"></div>

  <div class="board">
    <div id="lanes"></div>
    <div class="axis"><span>0s</span><span>{total_ms/2000:.1f}s</span><span>{total_ms/1000:.1f}s</span></div>
  </div>

  <div class="detail">
    <h2>Event detail</h2>
    <pre id="detail">点击时间轴上的圆点查看事件详情</pre>
  </div>
  <div class="hint">单文件离线页面，事件数据内嵌，无外部依赖。</div>
</div>

<script>
const EVENTS = {json.dumps(events, ensure_ascii=False)};
const COLORS = {json.dumps(COLORS, ensure_ascii=False)};
const TOTAL = {total_ms};

const lanes = document.getElementById('lanes');
const agents = [...new Set(EVENTS.map(e => e.agent || 'orchestrator'))];
agents.forEach(name => {{
  const lane = document.createElement('div');
  lane.className = 'lane';
  const label = document.createElement('div');
  label.className = 'lane-name';
  label.textContent = name;
  const track = document.createElement('div');
  track.className = 'track';
  EVENTS.filter(e => (e.agent || 'orchestrator') === name).forEach(e => {{
    const dot = document.createElement('div');
    dot.className = 'ev';
    dot.style.left = Math.min(99.5, (e.offset_ms / TOTAL) * 100) + '%';
    dot.style.background = COLORS[e.type] || '#94a3b8';
    dot.title = e.type + ' · ' + (e.offset_ms/1000).toFixed(2) + 's';
    dot.onclick = () => {{
      const copy = {{...e}};
      document.getElementById('detail').textContent = JSON.stringify(copy, null, 2);
    }};
    track.appendChild(dot);
  }});
  lane.appendChild(label);
  lane.appendChild(track);
  lanes.appendChild(lane);
}});

const counts = {{}};
EVENTS.forEach(e => counts[e.type] = (counts[e.type] || 0) + 1);
const cards = document.getElementById('cards');
const summary = [
  ['llm calls', counts.llm_call || 0],
  ['tool calls', counts.tool_call || 0],
  ['claims', EVENTS.filter(e => e.type === 'diagnose').reduce((a,e) => a + (e.claims || 0), 0)],
  ['critiques', counts.critique || 0],
  ['degraded', counts.degrade || 0],
];
summary.forEach(([k,v]) => {{
  const d = document.createElement('div');
  d.className = 'card';
  d.innerHTML = '<div class="k"></div><div class="v"></div>';
  d.querySelector('.k').textContent = k;
  d.querySelector('.v').textContent = v;
  cards.appendChild(d);
}});

const legend = document.getElementById('legend');
Object.entries(COLORS).filter(([k]) => counts[k]).forEach(([k, c]) => {{
  const s = document.createElement('span');
  s.innerHTML = '<span class="dot"></span><span></span>';
  s.querySelector('.dot').style.background = c;
  s.querySelector('span:last-child').textContent = k;
  legend.appendChild(s);
}});
</script>
</body>
</html>"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
