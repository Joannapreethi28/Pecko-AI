"""Thread-safe contract event log: one JSON object per line, {"stage","event","turn","t","extra"}.

Two ways to build it, both write the same line format (docs/CONTRACT.md):
  Spine:  EventLog(stream)                        -> log.emit("ears", "asr_final", 7, t=12.5, text=...)
  Brain:  EventLog("brain", path=None, keep=False) -> log.event("first_token", 7, gen=2)
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, Optional, TextIO, Union

from common.clock import now


class EventLog:
    def __init__(self, stream_or_stage: Union[TextIO, str], path: Optional[Path] = None, keep: bool = False):
        self.records: list[dict] = []
        self._keep = keep
        self._lock = threading.Lock()
        self._owns = False
        if isinstance(stream_or_stage, str):          # Brain style: bound to one stage
            self.stage: Optional[str] = stream_or_stage
            if path is not None:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                self.stream: TextIO = open(path, "a", encoding="utf-8", buffering=1)
                self._owns = True
            else:
                self.stream = sys.stdout
        else:                                         # Spine style: caller owns the stream
            self.stage = None
            self.stream = stream_or_stage

    def emit(self, stage: str, event: str, turn: Optional[int] = None,
             *, t: Optional[float] = None, **extra: Any) -> dict:
        rec = {"stage": stage, "event": event, "turn": turn,
               "t": now() if t is None else t, "extra": extra}
        line = json.dumps(rec, allow_nan=False, ensure_ascii=False)
        with self._lock:
            self.stream.write(line + "\n")
            self.stream.flush()
            if self._keep:
                self.records.append(rec)
        return rec

    def event(self, event: str, turn: int, t: Optional[float] = None, **extra: Any) -> dict:
        if self.stage is None:
            raise TypeError("event() needs EventLog(stage, ...); use emit(stage, ...) with a stream log")
        return self.emit(self.stage, event, turn, t=t, **extra)

    def close(self) -> None:
        if self._owns:
            self.stream.close()
