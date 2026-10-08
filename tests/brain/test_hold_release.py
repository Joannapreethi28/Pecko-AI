from brain.prompt import PromptBuilder
from fakes import FakeClient, wait_until
from test_stage import done, events, final, make

Q = "what is the capital of france"


def tentative(turn, text):
    return {"type": "tentative_final", "turn": turn, "text": text, "t_eos": 0.0, "p_done": 0.8}


def held_chunks(out):
    return [m for m in out if m.get("held")]


def streams(client):
    return [p for kind, p in client.calls if kind == "stream"][1:]   # [0] is the warm-up


def test_matching_final_releases_and_continues_same_gen(tmp_path):
    client = FakeClient()
    stage, out, log = make(tmp_path, client, hold_release=True)
    stage.feed(tentative(1, Q))
    assert wait_until(lambda: held_chunks(out))
    stage.feed(final(1, "What is the capital of France?", norm=Q))
    assert wait_until(lambda: done(out))
    stage.stop()
    first = out[0]
    assert first["held"] is True and first["seq"] == 0 and first["text"] == "Paris is the capital, "
    rest = out[1:]
    assert all(m["gen"] == first["gen"] and "held" not in m for m in rest)
    assert [m["seq"] for m in out] == list(range(len(out)))
    held_prompt, cont_prompt = streams(client)
    assert held_prompt == PromptBuilder().final(Q)
    assert cont_prompt == PromptBuilder().final(Q) + "Paris is the capital,"
    assert events(log, "held_valid", 1)[0]["extra"]["match"] is True
    assert not [m for m in out if m["type"] == "cancel"]


def test_final_right_after_tentative_still_matches(tmp_path):
    stage, out, log = make(tmp_path, FakeClient(), hold_release=True)
    stage.feed(tentative(1, Q))
    stage.feed(final(1, Q))
    assert wait_until(lambda: done(out))
    stage.stop()
    assert events(log, "held_valid", 1)[0]["extra"]["match"] is True
    assert len({m["gen"] for m in out}) == 1


def test_mismatching_final_cancels_held_and_answers_with_new_gen(tmp_path):
    stage, out, log = make(tmp_path, FakeClient(), hold_release=True)
    stage.feed(tentative(1, Q))
    assert wait_until(lambda: held_chunks(out))
    held_gen = held_chunks(out)[0]["gen"]
    stage.feed(final(1, "what is the capital of spain"))
    assert wait_until(lambda: done(out))
    stage.stop()
    assert {"type": "cancel", "turn": 1, "gen": held_gen} in out
    answer = [m for m in out if m["type"] == "chunk" and m["gen"] != held_gen]
    assert answer and answer[-1]["last"] and min(m["gen"] for m in answer) > held_gen
    assert not any(m.get("held") for m in answer)
    assert events(log, "held_valid", 1)[0]["extra"]["match"] is False


def test_ears_cancel_drops_held_clause(tmp_path):
    stage, out, log = make(tmp_path, FakeClient(), hold_release=True)
    stage.feed(tentative(1, Q))
    assert wait_until(lambda: held_chunks(out))
    held_gen = held_chunks(out)[0]["gen"]
    stage.feed({"type": "cancel", "turn": 1, "t": 0.0})
    assert wait_until(lambda: {"type": "cancel", "turn": 1, "gen": held_gen} in out)
    stage.stop()
    assert not done(out)


def test_router_hit_drops_held_clause(tmp_path):
    from brain.router import Router
    stage, out, log = make(tmp_path, FakeClient(), hold_release=True, router=Router.load())
    stage.feed(tentative(1, "hello pecko"))
    assert wait_until(lambda: held_chunks(out))
    held_gen = held_chunks(out)[0]["gen"]
    stage.feed(final(1, "hello pecko"))
    assert wait_until(lambda: done(out))
    stage.stop()
    assert {"type": "cancel", "turn": 1, "gen": held_gen} in out
    assert out[-1]["type"] == "cached" and out[-1]["clip"] == "greeting"


def test_hold_release_off_keeps_plain_prefill(tmp_path):
    client = FakeClient()
    stage, out, log = make(tmp_path, client)
    stage.feed(tentative(1, Q))
    assert wait_until(lambda: events(log, "prefill", 1))
    stage.stop()
    assert not held_chunks(out) and streams(client) == []


def test_text_read_past_the_held_chunk_is_still_spoken(tmp_path):
    """Regression (first real loop run): the held stream stops after the first chunk, but the chunker had
    already read " Paris"; the continuation prompt contains it, so it must reach Voice too."""
    pieces = ["The", " capital", " of", " France", " is", " Paris", "."]
    client = FakeClient(replies={"Paris": ["."], "france": pieces})   # continuation sees "Paris" already
    stage, out, log = make(tmp_path, client, hold_release=True)
    stage.feed(tentative(1, Q))
    assert wait_until(lambda: held_chunks(out))
    stage.feed(final(1, "What is the capital of France?", norm=Q))
    assert wait_until(lambda: done(out))
    stage.stop()
    spoken = "".join(m["text"] for m in out if m["type"] == "chunk")
    assert "Paris" in spoken, spoken
