"""Builders for every Ears message in docs/CONTRACT.md, so the JSON shape
can't drift from the frozen contract. Callers pass these dicts to
common/jsonl.emit()."""


def partial(turn: int, text: str, stable: str, t: float) -> dict:
    return {"type": "partial", "turn": turn, "text": text, "stable": stable, "t": t}


def tentative_final(turn: int, text: str, t_eos: float, p_done: float) -> dict:
    return {"type": "tentative_final", "turn": turn, "text": text, "t_eos": t_eos, "p_done": p_done}


def final(turn: int, text: str, norm: str, t_eos: float, t_endpoint: float) -> dict:
    return {
        "type": "final", "turn": turn, "text": text, "norm": norm,
        "t_eos": t_eos, "t_endpoint": t_endpoint,
    }


def cancel(turn: int, t: float) -> dict:
    return {"type": "cancel", "turn": turn, "t": t}


def barge_in(turn: int, t: float) -> dict:
    return {"type": "barge_in", "turn": turn, "t": t}


def intent_hint(turn: int, intent: str, t: float) -> dict:
    return {"type": "intent_hint", "turn": turn, "intent": intent, "t": t}
