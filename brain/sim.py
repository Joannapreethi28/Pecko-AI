"""Speech simulator: feeds a BrainStage the messages Ears would send while someone says `text`.
One `partial` per word (stable = all but the newest word, like two-partial agreement), a
`tentative_final` at speech end, a short silence, then `final`. Lets us test early prefill without Ears."""
from __future__ import annotations

import time

from brain.prompt import normalize
from common.clock import now


def speak(stage, turn: int, text: str, wps: float = 2.5, pause_ms: float = 300) -> float:
    """Feed `text` as speech. Returns the time (monotonic) at which `final` was fed."""
    words = text.split()
    for i in range(1, len(words) + 1):
        stage.feed({"type": "partial", "turn": turn, "text": " ".join(words[:i]),
                    "stable": " ".join(words[:i - 1]), "t": now()})
        time.sleep(1.0 / wps)
    t_eos = now()
    stage.feed({"type": "tentative_final", "turn": turn, "text": normalize(text), "t_eos": t_eos, "p_done": 0.8})
    time.sleep(pause_ms / 1000.0)
    t_final = now()
    stage.feed({"type": "final", "turn": turn, "text": text, "norm": normalize(text),
                "t_eos": t_eos, "t_endpoint": t_final})
    return t_final
