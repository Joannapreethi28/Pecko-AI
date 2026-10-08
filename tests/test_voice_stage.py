"""VoiceStage behaviour with a fake engine and NullPlayer: no models, no sound, fast."""
import time

import numpy as np
import pytest

import voice.cache as vcache
from voice.engine import OUT_SR
from voice.stage import VoiceStage


class FakeEngine:
    """Deterministic 'speech': 0.25 s of tone per word, ~5 ms of compute."""

    def __init__(self, pack, threads=1, warmup=0):
        self.pack = pack              # same name as the real voice: tests run in a tmp CACHE_DIR
        self.calls = []

    def synth(self, text):
        self.calls.append(text)
        time.sleep(0.005)
        n = max(1, len(text.split())) * int(0.25 * OUT_SR)
        return (0.5 * np.sin(np.arange(n) * 0.05)).astype(np.float32)


@pytest.fixture
def stage(tmp_path, monkeypatch):
    monkeypatch.setattr(vcache, "CACHE_DIR", tmp_path)
    import voice.vlog as vlog
    from common.log import EventLog
    monkeypatch.setattr(vlog, "_log", EventLog("voice", tmp_path / "voice.jsonl"))   # keep logs/voice.jsonl clean
    events = []
    s = VoiceStage(on_event=events.append, audio=False, engine_factory=FakeEngine)
    s.start()
    s.events = events
    yield s
    s.stop()


def summary(stage, turn, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        for e in stage.events:
            if e.get("type") == "turn_summary" and e["turn"] == turn:
                return e
        time.sleep(0.01)
    raise AssertionError(f"no turn_summary for turn {turn}")


def chunk(turn, seq, text, gen=1, **kw):
    return {"type": "chunk", "turn": turn, "gen": gen, "seq": seq, "text": text, **kw}


def test_held_audio_waits_for_commit(stage):
    stage.feed(chunk(1, 0, "Paris is the capital, ", held=True))
    stage.feed(chunk(1, 1, "", held=True, last=True))
    time.sleep(0.2)
    assert stage.player.written == 0                      # nothing audible before commit
    stage.feed({"type": "commit", "turn": 1, "gen": 1})
    s = summary(stage, 1)
    assert stage.player.written > 0 and s["t_first_audio"] >= s["t_commit"]


def test_cancel_drops_held_gen_and_new_gen_plays(stage):
    stage.feed(chunk(2, 0, "Wrong guess, never heard. ", held=True))
    time.sleep(0.15)
    stage.feed({"type": "cancel", "turn": 2})            # Ears: user kept talking
    stage.feed(chunk(2, 0, "Right answer.", gen=2, held=True, last=True))
    stage.feed({"type": "commit", "turn": 2, "gen": 2})
    s = summary(stage, 2)
    assert s["gens"] == 2 and s["t_first_audio"] is not None
    assert not any("wrong" in c.lower() for c in stage.engine.calls[-1:])


def test_commit_before_first_chunk_is_remembered(stage):
    stage.feed({"type": "commit", "turn": 3, "gen": 1})
    stage.feed(chunk(3, 0, "Sure thing, here it is.", held=True, last=True))
    assert summary(stage, 3)["t_first_audio"] is not None


def test_cached_intent_uses_l4_without_synthesis(stage):
    n = len(stage.engine.calls)
    stage.feed({"type": "cached", "turn": 4, "gen": 1, "clip": "who_are_you", "last": True})
    s = summary(stage, 4)
    assert s["first_layer"] == "L4" and len(stage.engine.calls) == n


def test_composed_time_uses_pieces(stage):
    n = len(stage.engine.calls)
    stage.feed(chunk(5, 0, "It's three forty-five in the afternoon.", last=True))
    s = summary(stage, 5)
    assert s["first_layer"] == "C" and len(stage.engine.calls) == n


def test_opener_l2_and_memo_l3(stage):
    stage.feed(chunk(6, 0, "Sure. ", last=False))
    stage.feed(chunk(6, 1, "The museum opens at nine.", last=True))
    s6 = summary(stage, 6)
    assert s6["first_layer"] == "L2"
    stage.feed(chunk(7, 0, "The museum opens at nine.", last=True))
    assert summary(stage, 7)["first_layer"] == "L3"


def test_out_of_order_seq_is_reordered(stage):
    stage.feed(chunk(8, 1, "second part.", last=True))
    stage.feed(chunk(8, 0, "First part, "))
    summary(stage, 8)
    assert stage.engine.calls[-2:] == ["First part,", "second part."]


def test_missing_seq_is_skipped_after_timeout(stage):
    stage.feed(chunk(9, 0, "Hello there, "))
    stage.feed(chunk(9, 2, "after the gap.", last=True))   # seq 1 never arrives
    s = summary(stage, 9, timeout=2.0)
    assert s["t_first_audio"] is not None


def test_barge_in_stops_and_drops_later_chunks(stage):
    stage.feed(chunk(10, 0, "This is a long answer, "))
    time.sleep(0.1)
    stage.feed({"type": "barge_in", "turn": 10})
    stage.feed(chunk(10, 1, "that nobody should hear.", last=True))
    s = summary(stage, 10)
    assert s["cancelled"] == "barge_in"
    assert "that nobody should hear." not in stage.engine.calls


def test_stale_turn_is_ignored(stage):
    stage.feed(chunk(12, 0, "Newer turn.", last=True))
    summary(stage, 12)
    n = len(stage.engine.calls)
    stage.feed(chunk(11, 0, "Older turn arriving late.", last=True))
    time.sleep(0.2)
    assert len(stage.engine.calls) == n
