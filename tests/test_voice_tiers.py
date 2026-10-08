"""Phase 4: voice ladder, lazy tier switching, per-phrase fallback, half-duplex. Fake engines, NullPlayer."""
import time

import numpy as np
import pytest

import voice.cache as vcache
from voice.engine import OUT_SR, TIERS
from voice.stage import VoiceStage

LOADS = []


class FakeEngine:
    def __init__(self, name, threads=1, warmup=0):
        if name == "broken":
            raise FileNotFoundError("no model")
        self.pack = name
        LOADS.append(name)

    def synth(self, text):
        if "BOOM" in text:
            raise RuntimeError("onnx exploded")
        n = max(1, len(text.split())) * int(0.2 * OUT_SR)
        return (0.5 * np.sin(np.arange(n) * 0.05)).astype(np.float32)


class Fallback:
    """Emergency engine: always works (like espeak-ng)."""

    def __init__(self):
        self.pack = "fallback"

    def synth(self, text):
        return (0.3 * np.sin(np.arange(int(0.5 * OUT_SR)) * 0.07)).astype(np.float32)


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.setattr(vcache, "CACHE_DIR", tmp_path)
    import voice.vlog as vlog
    from common.log import EventLog
    monkeypatch.setattr(vlog, "_log", EventLog("voice", tmp_path / "voice.jsonl"))
    LOADS.clear()
    made = []

    def _make(**kw):
        ev = []
        s = VoiceStage(on_event=ev.append, audio=False, engine_factory=FakeEngine,
                       fallback_factory=Fallback, **kw)
        s.ev = ev
        s.start()
        made.append(s)
        return s
    yield _make
    for s in made:
        s.stop()


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def say(s, turn, text):
    s.feed({"type": "chunk", "turn": turn, "gen": 1, "seq": 0, "text": text, "last": True})
    assert wait_for(lambda: any(e.get("type") == "turn_summary" and e["turn"] == turn for e in s.ev))


def test_ladder_shape():
    assert TIERS[0]["engine"] != TIERS[1]["engine"]
    assert TIERS[1]["engine"] == TIERS[2]["engine"]          # T2 = low + cache, no reload
    assert TIERS[3]["engine"] == "espeak-ng"                 # T3 = no neural voice
    assert all(TIERS[n]["cache"].startswith("vits-piper") for n in TIERS)


def test_switch_between_turns_and_t1_t2_no_reload(make):
    s = make()
    say(s, 1, "First reply here.")
    s.set_tier(1)
    assert wait_for(lambda: s.tier == 1)
    loads_after_t1 = len(LOADS)
    s.set_tier(2)
    assert wait_for(lambda: s.tier == 2)
    assert len(LOADS) == loads_after_t1                      # same engine: no reload
    sw = [e for e in s.ev if e.get("type") == "tier_switch"]
    assert [e["to"] for e in sw] == [1, 2] and sw[0]["reloaded"] and not sw[1]["reloaded"]


def test_switch_requested_mid_turn_waits_for_turn_end(make):
    s = make()
    s.feed({"type": "chunk", "turn": 1, "gen": 1, "seq": 0, "text": "Part one, ", "held": True})
    time.sleep(0.1)
    s.set_tier(1)
    time.sleep(0.2)
    assert s.tier == 0                                       # never mid-reply
    s.feed({"type": "chunk", "turn": 1, "gen": 1, "seq": 1, "text": "part two.", "held": True, "last": True})
    s.feed({"type": "commit", "turn": 1, "gen": 1})
    say(s, 2, "Next turn uses the new voice.")
    assert s.tier == 1


def test_broken_tier_falls_down_the_ladder(make, monkeypatch):
    monkeypatch.setitem(TIERS, 1, {"engine": "broken", "cache": TIERS[1]["cache"], "note": "x"})
    s = make()
    s.set_tier(1)
    assert wait_for(lambda: s.tier == 2)                     # T1 failed to load -> T2


def test_failing_phrase_uses_fallback_engine(make):
    s = make()
    say(s, 1, "This BOOM phrase breaks the main voice.")
    summ = next(e for e in s.ev if e.get("type") == "turn_summary" and e["turn"] == 1)
    assert summ["t_first_audio"] is not None                 # still audible
    assert s.fallback is not None and s.fallback.pack == "fallback"


def test_half_duplex_ignores_barge_in(make):
    s = make(barge_in=False)
    s.feed({"type": "chunk", "turn": 1, "gen": 1, "seq": 0, "text": "Keep talking please, "})
    time.sleep(0.05)
    s.feed({"type": "barge_in", "turn": 1})
    s.feed({"type": "chunk", "turn": 1, "gen": 1, "seq": 1, "text": "even after the barge in.", "last": True})
    assert wait_for(lambda: any(e.get("type") == "turn_summary" and e["turn"] == 1 for e in s.ev))
    summ = next(e for e in s.ev if e.get("type") == "turn_summary")
    assert summ["cancelled"] is None and summ["phrases"] == 2


def test_t3_plays_cached_clips_without_making_new_ones(make):
    s = make()
    s.set_tier(1)                                            # builds lessac-low clips with the low engine
    assert wait_for(lambda: s.tier == 1)
    s.set_tier(3)
    assert wait_for(lambda: s.tier == 3)
    sw = [e for e in s.ev if e.get("type") == "tier_switch"][-1]
    assert sw["engine"] == "espeak-ng" and sw["cache_synthesized"] == 0
    s.feed({"type": "cached", "turn": 5, "gen": 1, "clip": "greeting", "last": True})
    assert wait_for(lambda: any(e.get("type") == "turn_summary" and e["turn"] == 5 for e in s.ev))
    summ = next(e for e in s.ev if e.get("type") == "turn_summary" and e["turn"] == 5)
    assert summ["first_layer"] == "L4"


def test_unloadable_survival_tier_recovers_previous_voice(make, monkeypatch):
    monkeypatch.setitem(TIERS, 3, {"engine": "broken", "cache": TIERS[3]["cache"], "note": "espeak missing"})
    s = make()
    s.set_tier(3)
    time.sleep(0.3)
    assert s.tier == 0 and s.engine is not None             # back on the previous voice, not silent
    say(s, 1, "Still speaking after a failed switch.")
