"""JSONL event trace.

One line per event, flush on every write, so a crashed run still leaves a
readable trail. Digest fields keep payloads addressable without inlining huge
blobs twice.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..contracts import digest, now_iso


class Tracer:
    def __init__(self, path: str | Path, run_id: str, sink: Any = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.sink = sink
        self.seq = 0
        self._started = time.perf_counter()
        self._fh = self.path.open("w", encoding="utf-8")

    def emit(self, event_type: str, agent: str = "", **fields: Any) -> dict[str, Any]:
        self.seq += 1
        event = {
            "seq": self.seq,
            "ts": now_iso(),
            "offset_ms": round((time.perf_counter() - self._started) * 1000, 1),
            "run_id": self.run_id,
            "type": event_type,
            "agent": agent,
            **fields,
        }
        self._fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
        self._fh.flush()
        if self.sink is not None:
            try:
                self.sink(event)
            except Exception:  # a broken sink must never kill the run
                pass
        return event

    def payload_digest(self, obj: Any) -> str:
        return digest(obj)

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.close()

    def __enter__(self) -> Tracer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
