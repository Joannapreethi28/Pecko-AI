"""One-JSON-object-per-line diagnostic logger (docs/CONTRACT.md log line format).
Writes to stderr so a stage's stdout can stay a clean contract-message stream."""
import json
import sys
import time


def log(stage: str, event: str, turn: int | None = None, t: float | None = None, **extra) -> None:
    line = {"stage": stage, "event": event, "t": t if t is not None else time.monotonic()}
    if turn is not None:
        line["turn"] = turn
    if extra:
        line["extra"] = extra
    print(json.dumps(line), file=sys.stderr, flush=True)
