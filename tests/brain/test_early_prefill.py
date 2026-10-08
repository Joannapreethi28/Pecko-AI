from brain.prompt import PromptBuilder
from common.log import EventLog
from fakes import FakeClient, wait_until
from test_stage import done, events, final, make


def partial(turn, stable):
    return {"type": "partial", "turn": turn, "text": stable + " x", "stable": stable, "t": 0.0}


def prefills(client):
    return [p for kind, p in client.calls if kind == "prefill"][1:]   # [0] is the warm-up


def test_stable_prefill_is_prefix_of_final_prompt(tmp_path):
    client = FakeClient()
    stage, out, log = make(tmp_path, client)
    stage.feed(partial(1, "what is the capital"))
    assert wait_until(lambda: events(log, "prefill", 1))
    stage.feed(final(1, "what is the capital of france"))
    assert wait_until(lambda: done(out))
    stage.stop()
    pre, = prefills(client)
    assert pre == PromptBuilder().partial("what is the capital")
    final_prompt = [p for kind, p in client.calls if kind == "stream"][-1]
    assert final_prompt.startswith(pre)


def test_unchanged_or_one_word_stable_does_not_prefill(tmp_path):
    client = FakeClient()
    stage, out, log = make(tmp_path, client)
    stage.feed(partial(1, "what"))
    stage.feed(partial(1, "what is"))
    stage.feed(partial(1, "what is"))
    assert wait_until(lambda: events(log, "prefill", 1))
    stage.stop()
    assert prefills(client) == [PromptBuilder().partial("what is")]


def test_tentative_then_same_final_reuses_exact_prompt(tmp_path):
    client = FakeClient()
    stage, out, log = make(tmp_path, client)
    stage.feed({"type": "tentative_final", "turn": 1, "text": "what is the capital of france", "t_eos": 0, "p_done": 0.8})
    assert wait_until(lambda: events(log, "prefill", 1))
    stage.feed(final(1, "What is the capital of France?", norm="what is the capital of france"))
    assert wait_until(lambda: done(out))
    stage.stop()
    stream_prompt = [p for kind, p in client.calls if kind == "stream"][-1]
    assert prefills(client) == [stream_prompt]


def test_tier_prefill_modes(tmp_path):
    for tier, want_stable, want_tentative in ((1, True, False), (2, False, False)):
        client = FakeClient()
        stage, out, log = make(tmp_path / str(tier), client, tier=tier)
        stage.feed(partial(1, "what is the capital"))
        # real speech leaves time between words; without it coalesce() rightly drops the stale prefill
        wait_until(lambda: events(log, "prefill", 1), timeout=0.3)
        stage.feed({"type": "tentative_final", "turn": 1, "text": "what is the capital of france", "t_eos": 0, "p_done": 0.8})
        wait_until(lambda: len(events(log, "prefill", 1)) >= 2, timeout=0.3)
        stage.feed(final(1, "what is the capital of france"))
        assert wait_until(lambda: done(out))
        stage.stop()
        kinds = [r["extra"]["kind"] for r in events(log, "prefill", 1)]
        assert ("stable" in kinds or not want_stable) and ("tentative" in kinds) == want_tentative
        if not want_stable:
            assert kinds == []


def test_early_prefill_off(tmp_path):
    client = FakeClient()
    stage, out, log = make(tmp_path, client, early_prefill=False)
    stage.feed(partial(1, "what is the capital"))
    stage.feed(final(1, "what is the capital of france"))
    assert wait_until(lambda: done(out))
    stage.stop()
    assert prefills(client) == []


def test_ears_cancel_allows_same_stable_again(tmp_path):
    client = FakeClient()
    stage, out, log = make(tmp_path, client)
    stage.feed(partial(1, "what is the"))
    assert wait_until(lambda: len(prefills(client)) == 1)
    stage.feed({"type": "cancel", "turn": 1, "t": 0.0})
    stage.feed(partial(1, "what is the"))
    assert wait_until(lambda: len(prefills(client)) == 2)
    stage.stop()
    assert events(log, "spec_cancel", 1)
