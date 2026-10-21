"""FastAPI wrapper with a server-sent-events stream.

The agent runs in a worker thread; the tracer fans events out to the event loop
so the browser can watch each step land in real time.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

from .orchestrator import Orchestrator, RunConfig

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "fixtures"
WEB = Path(__file__).parent / "web" / "index.html"
RUNS = ROOT / "runs" / "api"

app = FastAPI(title="membergraph", version="0.1.0", description="多智能体会员增长工作台")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return WEB.read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "data": str(DATA)}


@app.get("/api/run")
async def run(
    topic: str,
    provider: str = "fake",
    budget_cny: float = 30000,
    max_tool_calls: int = 30,
) -> StreamingResponse:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def sink(event: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def work() -> None:
        try:
            plan = Orchestrator(
                DATA,
                RunConfig(
                    topic=topic,
                    provider=provider,
                    out_dir=RUNS,
                    budget_cny=budget_cny,
                    max_tool_calls=max_tool_calls,
                ),
                tracer_sink=sink,
            ).run()
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "result", "plan": plan.model_dump()})
        except Exception as exc:  # noqa: BLE001 - surfaced to the browser
            loop.call_soon_threadsafe(
                queue.put_nowait, {"type": "error", "error": f"{type(exc).__name__}: {exc}"}
            )

    threading.Thread(target=work, daemon=True).start()

    async def generate():
        while True:
            event = await queue.get()
            yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            if event["type"] in {"result", "error"}:
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
