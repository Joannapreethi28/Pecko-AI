"""Event log: one JSON object per line, {"stage","event","turn","t","extra"} (docs/CONTRACT.md)."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from common.clock import now


class EventLog:
    def __init__(self, stage: str, path: Optional[Path] = None, keep: bool = False):
        self.stage = stage
        self.records: list[dict] = []
        self._keep = keep
        self._lock = threading.Lock()
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._fp = open(path, "a", encoding="utf-8", buffering=1)
        else:
            self._fp = sys.stdout
        self._owns = path is not None

    def event(self, event: str, turn: int, t: Optional[float] = None, **extra: Any) -> dict:
        rec = {"stage": self.stage, "event": event, "turn": turn,
               "t": now() if t is None else t, "extra": extra}
        line = json.dumps(rec, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            self._fp.write(line + "\n")
            if self._keep:
                self.records.append(rec)
        return rec

    def close(self) -> None:
        if self._owns:
            self._fp.close()
