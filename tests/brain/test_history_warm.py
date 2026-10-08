from brain.stage import BrainStage
from common.log import EventLog
from fakes import FakeClient, wait_until


def make(tmp_path, client=None, **kw):
    out = []
    log = EventLog("brain", tmp_path / "ev.jsonl", keep=True)
    stage = BrainStage(out.append, log, client or FakeClient(), **kw)
    stage.start()
    return stage, out, log


def final(turn, text):
    return {"type": "final", "turn": turn, "text": text, "norm": text.lower(),
            "t_eos": 0.0, "t_endpoint": 0.0}


def done(out, turn):
    return any(m.get("last") and m["turn"] == turn for m in out)


def events(log, name, turn=None):
    return [r for r in log.records if r["event"] == name and (turn is None or r["turn"] == turn)]


def streams(client):
    return [p for kind, p in client.calls if kind == "stream"][1:]   # [0] is the warm-up


def run_turns(stage, out, log, first, last):
    for t in range(first, last + 1):
        stage.feed(final(t, f"question number {t}"))
        assert wait_until(lambda t=t: done(out, t))
        assert wait_until(lambda t=t: events(log, "gen_done", t))


def test_trim_logged_only_on_overflow_and_base_prefilled(tmp_path):
    client = FakeClient()
    stage, out, log = make(tmp_path, client)
    run_turns(stage, out, log, 1, 3)
    assert not events(log, "history_trim")
    run_turns(stage, out, log, 4, 4)
    trims = events(log, "history_trim")
    assert len(trims) == 1 and trims[0]["turn"] == 4 and trims[0]["extra"]["kept"] == 1
    assert wait_until(lambda: client.calls[-1] == ("prefill", stage.base_prompt()))
    assert any(r["extra"].get("kind") == "base" for r in events(log, "prefill", 4))
    stage.stop()


def test_no_further_trim_on_turns_5_and_6(tmp_path):
    stage, out, log = make(tmp_path)
    run_turns(stage, out, log, 1, 6)
    stage.stop()
    assert len(events(log, "history_trim")) == 1


def test_no_base_prefill_when_cache_prompt_off(tmp_path):
    client = FakeClient()
    stage, out, log = make(tmp_path, client)
    stage.cache_prompt = False
    run_turns(stage, out, log, 1, 4)
    assert len(events(log, "history_trim")) == 1
    assert not wait_until(lambda: client.calls[-1] == ("prefill", stage.base_prompt()), timeout=0.3)
    assert not any(r["extra"].get("kind") == "base" for r in events(log, "prefill"))
    stage.stop()


def test_prompt_extends_between_trims(tmp_path):
    client = FakeClient()
    stage, out, log = make(tmp_path, client)
    run_turns(stage, out, log, 1, 2)
    stage.stop()
    p1, p2 = streams(client)[:2]
    assert p2.startswith(p1)
