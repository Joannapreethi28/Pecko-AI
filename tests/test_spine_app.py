"""spine/app.py routing with a real BrainStage (fake llama client) and fake Ears/Voice."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "brain"))   # tests/brain/fakes.py

from brain.stage import BrainStage
from common.log import EventLog
from fakes import FakeClient, wait_until
from spine.app import LineSink, Pecko, StageLog


class FakeVoice:
    def __init__(self):
        self.got, self.tiers = [], []

    def feed(self, msg):
        self.got.append(msg)

    def set_tier(self, n):
        self.tiers.append(n)


class FakeEars:
    def __init__(self):
        self.playing, self.tiers = [], []

    def on_playback_state(self, playing):
        self.playing.append(playing)

    def set_tier(self, n):
        self.tiers.append(n)


def make(hold=True):
    shared = EventLog(io.StringIO())
    app = Pecko(shared)
    app.voice, app.ears = FakeVoice(), FakeEars()
    app.brain = BrainStage(app.from_brain, StageLog("brain", shared, app.on_brain_log), FakeClient(),
                           hold_release=hold)
    app.brain.start()
    return app


def final(turn, text):
    return {"type": "final", "turn": turn, "text": text, "norm": text, "t_eos": 0.0, "t_endpoint": 0.0}


def test_matching_final_commits_the_held_gen():
    app = make()
    app.from_ears({"type": "tentative_final", "turn": 1, "text": "what is the capital of france",
                   "t_eos": 0.0, "p_done": 0.9})
    assert wait_until(lambda: any(m.get("held") for m in app.voice.got))
    held = next(m for m in app.voice.got if m.get("held"))
    assert not any(m["type"] == "commit" for m in app.voice.got)   # nothing released before C
    app.from_ears(final(1, "what is the capital of france"))
    assert wait_until(lambda: any(m.get("last") for m in app.voice.got))
    commits = [m for m in app.voice.got if m["type"] == "commit"]
    assert len(commits) == 1 and commits[0]["gen"] == held["gen"] and commits[0]["turn"] == 1
    assert app.voice.got.index(commits[0]) > app.voice.got.index(held)
    assert_commit_before_audible(app.voice.got)
    app.brain.stop()


def test_mismatching_final_cancels_held_and_commits_only_the_fresh_gen():
    app = make()
    app.from_ears({"type": "tentative_final", "turn": 1, "text": "what is the capital of spain",
                   "t_eos": 0.0, "p_done": 0.9})
    assert wait_until(lambda: any(m.get("held") for m in app.voice.got))
    held_gen = next(m for m in app.voice.got if m.get("held"))["gen"]
    app.from_ears(final(1, "what is the capital of italy"))
    assert wait_until(lambda: any(m.get("last") for m in app.voice.got))
    commits = [m for m in app.voice.got if m["type"] == "commit"]
    assert len(commits) == 1 and commits[0]["gen"] != held_gen
    assert any(m["type"] == "cancel" for m in app.voice.got)
    assert_commit_before_audible(app.voice.got)
    app.brain.stop()


def assert_commit_before_audible(got):
    """Every non-held chunk/cached of a gen arrives after that gen's commit (nothing audible before C)."""
    committed = set()
    for m in got:
        if m["type"] == "commit":
            committed.add((m["turn"], m["gen"]))
        elif m["type"] in ("chunk", "cached") and not m.get("held"):
            assert (m["turn"], m["gen"]) in committed, m


def test_plain_llm_turn_commits_before_first_chunk():
    app = make()
    app.from_ears(final(1, "who wrote romeo and juliet"))
    assert wait_until(lambda: any(m.get("last") for m in app.voice.got))
    assert app.voice.got[0]["type"] == "commit"
    assert_commit_before_audible(app.voice.got)
    app.brain.stop()


def test_cached_turn_commits_before_clip():
    from brain.router import Router
    app = make()
    app.brain._router = Router.load()
    app.from_ears(final(1, "thank you"))
    assert wait_until(lambda: any(m.get("last") for m in app.voice.got))
    assert app.voice.got[0]["type"] == "commit"
    assert any(m["type"] == "cached" for m in app.voice.got)
    assert_commit_before_audible(app.voice.got)
    app.brain.stop()


def test_no_hold_plays_without_commit():
    app = make(hold=False)
    app.from_ears(final(1, "hello there"))
    assert wait_until(lambda: any(m.get("last") for m in app.voice.got))
    assert not any(m.get("held") for m in app.voice.got)
    app.brain.stop()


def test_playback_state_reaches_ears_and_marks_turn_done():
    app = make()
    app.from_voice({"type": "playback_state", "turn": 3, "playing": True, "t": 1.0})
    app.from_voice({"type": "playback_state", "turn": 3, "playing": False, "t": 2.0})
    assert app.ears.playing == [True, False]
    assert app.wait_turn(3, timeout=0.1)
    app.brain.stop()


def test_barge_in_goes_to_voice_and_brain():
    app = make()
    app.from_ears({"type": "barge_in", "turn": 2, "t": 1.0})
    assert {"type": "barge_in", "turn": 2, "t": 1.0} in app.voice.got
    app.brain.stop()


def test_set_tier_reaches_every_stage():
    app = make()
    app.set_tier(2)
    assert app.ears.tiers == [2] and app.voice.tiers == [2]
    app.brain.stop()


def test_line_sink_routes_each_json_line():
    got = []
    sink = LineSink(got.append)
    sink.write('{"type":"partial","turn":1}\n{"type":"fin')
    sink.write('al","turn":1}\n')
    assert [m["type"] for m in got] == ["partial", "final"]
