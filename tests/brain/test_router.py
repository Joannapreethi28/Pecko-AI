import json
from datetime import datetime
from pathlib import Path

import yaml

from brain.eval_router import evaluate
from brain.prompt import normalize
from brain.router import INTENTS_PATH, Router, date_words, day_words, time_words

HELDOUT = Path(__file__).parent / "data" / "router_heldout.jsonl"
NOW = datetime(2026, 10, 8, 15, 45)  # a Thursday


def make():
    return Router.load(clock=lambda: NOW)


def test_intents_file_is_consistent():
    data = yaml.safe_load(Path(INTENTS_PATH).read_text(encoding="utf-8"))
    intents = data["intents"] if isinstance(data, dict) else data
    assert len(intents) == 30
    clips = [i["clip"] for i in intents]
    assert len(set(clips)) == len(clips)
    for i in intents:
        assert i["say"].strip()
        assert i["templates"]
        for t in i["templates"]:
            assert normalize(t) == t, t


def test_exact_hits():
    r = make()
    assert r.route("hello pecko").intent == "greeting"
    assert r.route("hello pecko").kind == "cached"
    assert r.route("thank you").intent == "thanks"


def test_empty_is_didnt_catch():
    r = make().route("")
    assert r.kind == "cached" and r.intent == "didnt_catch"


def test_fuzzy_with_filler():
    r = make().route("hello there pecko")
    assert r.kind == "cached" and r.intent == "greeting"


def test_entity_rejection():
    r = make()
    assert r.route("hello can you book a cab").kind == "llm"
    assert r.route("thanks but what is the capital of france").kind == "llm"


def test_composed_time_date_day_with_greeting_stripped():
    r = make()
    t = r.route("hi what time is it")
    assert t.kind == "composed" and t.intent == "time"
    assert t.text == "It's three forty-five in the afternoon."
    d = r.route("what is the date today")
    assert d.kind == "composed" and d.text == "Today is Thursday, October eighth."
    w = r.route("what day is it")
    assert w.kind == "composed" and w.text == "It's Thursday."


def test_time_words():
    assert time_words(datetime(2026, 10, 8, 15, 45)) == "It's three forty-five in the afternoon."
    assert time_words(datetime(2026, 10, 8, 0, 5)) == "It's twelve oh five at night."
    assert time_words(datetime(2026, 10, 8, 9, 0)) == "It's nine o'clock in the morning."


def test_date_and_day_words():
    assert date_words(datetime(2026, 10, 8)) == "Today is Thursday, October eighth."
    assert day_words(datetime(2026, 10, 8)) == "It's Thursday."


def test_unknown_goes_to_llm():
    assert make().route("what is the capital of france").kind == "llm"


def test_heldout_zero_wrong_zero_false_hits():
    rows = [json.loads(l) for l in HELDOUT.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) >= 30
    assert any(r["expect"] is None for r in rows) and any(r["expect"] for r in rows)
    res = evaluate(make(), rows)
    assert res["wrong"] == 0, res
    assert res["false_hits"] == 0, res
    assert 0.0 <= res["hit_rate"] <= 1.0
