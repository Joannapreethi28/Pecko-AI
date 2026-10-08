"""Thread-safe contract event logging. The caller owns the output stream."""

import json
from threading import Lock
from typing import TextIO

from common.clock import now


class EventLog:
    def __init__(self, stream: TextIO):
        self.stream = stream
        self._lock = Lock()

    def emit(self, stage: str, event: str, turn: int | None = None,
             *, t: float | None = None, **extra) -> None:
        line = json.dumps({"stage": stage, "event": event, "turn": turn,
                           "t": now() if t is None else t, "extra": extra},
                          allow_nan=False, ensure_ascii=False)
        with self._lock:
            self.stream.write(line + "\n")
            self.stream.flush()
