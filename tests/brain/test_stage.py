import time

import pytest

from brain.stage import FALLBACK_TEXT, BrainStage, coalesce, count_sentence_ends
from common.log import EventLog
from fakes import FakeClient, wait_until

LONG = [f" w{i}" for i in range(50)]


def make(tmp_path, client=None, **kw):
    out = []
    log = EventLog("brain", tmp_path / "ev.jsonl", keep=True)
    stage = BrainStage(out.append, log, client or FakeClient(), **kw)
    stage.start()
    return stage, out, log


def final(turn, text, norm=None):
    return {"type": "final", "turn": turn, "text": text,
            "norm": text.lower() if norm is None else norm, "t_eos": 0.0, "t_endpoint": 0.0}


def done(out, turn=None):
    return any(m.get("last") and (turn is None or m["turn"] == turn) for m in out)


def events(log, name, turn=None):
    return [r for r in log.records if r["event"] == name and (turn is None or r["turn"] == turn)]


def streams(client):
    return [p for kind, p in client.calls if kind == "stream"][1:]   # [0] is the warm-up


def test_final_streams_chunks_with_contract_fields(tmp_path):
    stage, out, log = make(tmp_path)
    stage.feed(final(1, "What is the capital of France?"))
    assert wait_until(lambda: done(out))
    stage.stop()
    assert [m["text"] for m in out] == ["Paris is the capital, ", "and its largest city. ", ""]
    assert [m["seq"] for m in out] == [0, 1, 2]
    assert {m["type"] for m in out} == {"chunk"} and {m["turn"] for m in out} == {1}
    assert len({m["gen"] for m in out}) == 1
    assert out[-1]["last"] is True and "last" not in out[0]


def test_required_events_logged_in_order(tmp_path):
    stage, out, log = make(tmp_path)
    stage.feed(final(1, "hi there"))
    assert wait_until(lambda: events(log, "gen_done", 1))
    stage.stop()
    names = [r["event"] for r in log.records if r["turn"] == 1]
    order = [names.index(n) for n in ("prompt_ready", "first_token", "first_chunk", "gen_done")]
    assert order == sorted(order)


def test_prompt_uses_norm_not_cased_text(tmp_path):
    client = FakeClient()
    stage, out, log = make(tmp_path, client)
    stage.feed({"type": "final", "turn": 1, "text": "What is the Capital of France?",
                "norm": "what is the capital of france"})
    assert wait_until(lambda: done(out))
    stage.stop()
    assert "<|im_start|>user\nwhat is the capital of france<|im_end|>" in streams(client)[0]


def test_second_turn_prompt_extends_first(tmp_path):
    client = FakeClient()
    stage, out, log = make(tmp_path, client)
    stage.feed(final(1, "first question"))
    assert wait_until(lambda: events(log, "gen_done", 1))
    stage.feed(final(2, "second question"))
    assert wait_until(lambda: events(log, "gen_done", 2))
    stage.stop()
    p1, p2 = streams(client)
    assert p2.startswith(p1 + "Paris is the capital, and its largest city.")


def test_barge_in_stops_within_one_piece(tmp_path):
    client = FakeClient(replies={"tell me a story": ["Okay", ","] + LONG + ["."]}, delay=0.02)
    stage, out, log = make(tmp_path, client)
    stage.feed(final(1, "tell me a story"))
    assert wait_until(lambda: len(out) >= 1)
    n = len(out)
    stage.feed({"type": "barge_in", "turn": 1, "t": 0.0})
    assert wait_until(lambda: events(log, "gen_done", 1))
    stage.stop()
    assert len(out) <= n + 1 and not done(out)
    assert events(log, "gen_cancelled", 1)


def test_new_final_cancels_running_reply(tmp_path):
    client = FakeClient(replies={"long one": LONG}, delay=0.02)
    stage, out, log = make(tmp_path, client)
    stage.feed(final(1, "long one"))
    time.sleep(0.1)
    stage.feed(final(2, "short one"))
    assert wait_until(lambda: done(out, turn=2))
    stage.stop()
    assert not done(out, turn=1)
    gens1 = [m["gen"] for m in out if m["turn"] == 1]
    assert min(m["gen"] for m in out if m["turn"] == 2) > max(gens1, default=0)


def test_voice_cancel_by_gen(tmp_path):
    client = FakeClient(replies={"long one": LONG}, delay=0.02)
    stage, out, log = make(tmp_path, client)
    stage.feed(final(1, "long one"))
    assert wait_until(lambda: out)
    stage.feed({"type": "cancel", "turn": 1, "gen": out[0]["gen"]})
    assert wait_until(lambda: events(log, "gen_cancelled", 1))
    stage.stop()
    assert not done(out)


def test_llm_failure_sends_fallback(tmp_path):
    client = FakeClient()
    stage, out, log = make(tmp_path, client)
    client.fail = True
    stage.feed(final(1, "anything"))
    assert wait_until(lambda: done(out))
    stage.stop()
    assert [m["text"] for m in out] == [FALLBACK_TEXT]
    assert events(log, "llm_error", 1)


def test_empty_final_sends_didnt_catch_without_llm(tmp_path):
    client = FakeClient()
    stage, out, log = make(tmp_path, client)
    stage.feed(final(1, "   ", norm=""))
    assert wait_until(lambda: done(out))
    stage.stop()
    assert out == [{"type": "cached", "turn": 1, "gen": out[0]["gen"], "clip": "didnt_catch", "last": True}]
    assert streams(client) == []


def test_sentence_limit_two(tmp_path):
    pieces = ["One", " two", ".", " Three", " four", ".", " Five", " six", "."]
    stage, out, log = make(tmp_path, FakeClient(replies={"three": pieces}))
    stage.feed(final(1, "say three sentences"))
    assert wait_until(lambda: done(out))
    stage.stop()
    assert "".join(m["text"] for m in out).strip() == "One two. Three four."


def test_unspeakable_never_reaches_voice(tmp_path):
    pieces = ["**Sure**", ",", " see", " https://x.y", " 🎉", "."]
    stage, out, log = make(tmp_path, FakeClient(replies={"emoji": pieces}))
    stage.feed(final(1, "emoji please"))
    assert wait_until(lambda: done(out))
    stage.stop()
    text = " ".join(m["text"] for m in out)
    assert "Sure" in text and "*" not in text and "http" not in text and "🎉" not in text


def test_tier3_answers_low_power_without_server(tmp_path):
    client = FakeClient()
    client.healthy = False
    stage, out, log = make(tmp_path, client, tier=3)
    stage.feed(final(1, "what is the capital of france"))
    assert wait_until(lambda: done(out))
    stage.stop()
    assert out[0]["type"] == "cached" and out[0]["clip"] == "low_power"
    assert client.calls == []


def test_start_fails_loudly_when_server_down(tmp_path):
    client = FakeClient()
    client.healthy = False
    with pytest.raises(RuntimeError):
        make(tmp_path, client)


def test_set_tier_waits_for_running_reply(tmp_path):
    client = FakeClient(replies={"long one": [f" w{i}" for i in range(30)] + ["."]}, delay=0.01)
    stage, out, log = make(tmp_path, client)
    stage.feed(final(1, "long one"))
    stage.set_tier(2)
    assert wait_until(lambda: events(log, "tier_switch"))
    stage.stop()
    gen_done, switch = events(log, "gen_done", 1)[0], events(log, "tier_switch")[0]
    assert gen_done["t"] <= switch["t"] and switch["extra"]["to"] == "T2"


def test_coalesce_keeps_only_last_useful_prefill():
    jobs = [("prefill", 1, "stable", "a b"), ("prefill", 1, "stable", "a b c"),
            ("tier", 1), ("prefill", 1, "tentative", "a b c d")]
    assert coalesce(jobs) == [("tier", 1), ("prefill", 1, "tentative", "a b c d")]
    assert coalesce([("prefill", 1, "stable", "a b"), ("generate", 1, 5, "a b c")]) == [("generate", 1, 5, "a b c")]


def test_count_sentence_ends():
    assert count_sentence_ends("Hi. Bye.") == 2
    assert count_sentence_ends("and its largest city.") == 1
    assert count_sentence_ends("It is 3.5 degrees") == 0


def test_router_hits_skip_the_llm_and_history(tmp_path):
    from datetime import datetime
    from brain.prompt import PromptBuilder
    from brain.router import Router
    client = FakeClient()
    router = Router.load(clock=lambda: datetime(2026, 10, 8, 15, 45))
    stage, out, log = make(tmp_path, client, router=router)
    stage.feed(final(1, "Hello Pecko!"))
    assert wait_until(lambda: done(out, turn=1))
    stage.feed(final(2, "what time is it"))
    assert wait_until(lambda: done(out, turn=2))
    stage.stop()
    assert out[0]["type"] == "cached" and out[0]["clip"] == "greeting"
    assert out[1]["type"] == "chunk" and out[1]["text"] == "It's three forty-five in the afternoon." and out[1]["last"]
    assert streams(client) == [] and stage.base_prompt() == PromptBuilder().base()
    assert [r["extra"]["kind"] for r in events(log, "route")] == ["cached", "composed"]
