"""Append-only blackboard.

Every write produces a new revision; nothing is ever mutated in place. That is
what makes "who changed this conclusion, and when" answerable after the fact.
"""

from __future__ import annotations

import threading
from typing import Any

from pydantic import BaseModel, Field

from .contracts import digest, now_iso


class Entry(BaseModel):
    key: str
    revision: int
    author: str
    value: Any
    ts: str = Field(default_factory=now_iso)
    digest: str


class Blackboard:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._entries: dict[str, list[Entry]] = {}
        self._lock = threading.RLock()

    def write(self, key: str, value: Any, author: str) -> Entry:
        with self._lock:
            rev = len(self._entries.get(key, [])) + 1
            entry = Entry(key=key, revision=rev, author=author, value=value, digest=digest(value))
            self._entries.setdefault(key, []).append(entry)
            return entry

    def append(self, key: str, item: Any, author: str) -> Entry:
        with self._lock:
            current = self.read(key, default=[])
            if not isinstance(current, list):
                raise TypeError(f"cannot append to non-list key {key!r}")
            return self.write(key, [*current, item], author)

    def read(self, key: str, default: Any = None) -> Any:
        with self._lock:
            versions = self._entries.get(key)
            return versions[-1].value if versions else default

    def read_list(self, key: str) -> list[Any]:
        value = self.read(key, default=[])
        return list(value) if isinstance(value, list) else []

    def history(self, key: str) -> list[Entry]:
        with self._lock:
            return list(self._entries.get(key, []))

    def revisions(self) -> dict[str, int]:
        with self._lock:
            return {k: len(v) for k, v in self._entries.items()}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {k: v[-1].value for k, v in self._entries.items() if v}
