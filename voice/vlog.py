"""Voice clock + JSONL log. Uses the team's common/clock.py (now) and common/log.py (EventLog), so Voice lines
match every other stage: {"stage":"voice","event",...,"turn","t","extra"} in logs/voice.jsonl.
Never call log() from the audio callback.
"""
import threading
from pathlib import Path

from common.clock import now  # noqa: F401  (re-exported for the rest of voice/)
from common.log import EventLog

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "voice.jsonl"
_lock = threading.Lock()
_log = None
_sinks = []  # extra in-memory listeners (bench / tests)


def add_sink(fn) -> None:
    _sinks.append(fn)


def log(event: str, turn=None, t: float = None, **extra) -> dict:
    global _log
    if _log is None:
        with _lock:
            if _log is None:
                _log = EventLog("voice", LOG_PATH)
    rec = _log.event(event, turn, t=t, **extra)
    for fn in _sinks:
        fn(rec)
    return rec


def remove_sink(fn) -> None:
    if fn in _sinks:
        _sinks.remove(fn)
