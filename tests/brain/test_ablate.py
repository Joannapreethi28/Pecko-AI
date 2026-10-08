from brain.ablate import load_turns, measure, percentile, row


def rec(event, turn, t, **extra):
    return {"stage": "brain", "event": event, "turn": turn, "t": t, "extra": extra}


def test_percentile_nearest_rank():
    v = list(range(1, 11))   # 1..10
    assert percentile(v, 50) == 5
    assert percentile(v, 90) == 9
    assert percentile([], 50) is None


def test_measure_p50_p90_and_wasted():
    finals = {1: 10.0, 2: 20.0}
    base = {1: 100, 2: 100}
    records = [
        rec("prefill", 1, 9.0, prompt_n=20, cache_n=100),
        rec("first_token", 1, 10.2), rec("first_chunk", 1, 10.3),
        rec("gen_done", 1, 11.0, cache_n=115, prompt_n=5),      # 15 of 20 prefilled tokens were useful
        rec("prefill", 2, 19.0, prompt_n=10, cache_n=100),
        rec("first_token", 2, 20.4), rec("first_chunk", 2, 20.5),
        rec("gen_done", 2, 21.0, cache_n=100, prompt_n=15),     # none useful
        rec("prefill", -1, 1.0, prompt_n=999),                  # not a measured turn: ignored
    ]
    m = measure(records, finals, base)
    assert m["n"] == 2
    assert round(m["first_token_p50"]) == 200 and round(m["first_token_p90"]) == 400
    assert round(m["first_audio_p50"]) == 300 and round(m["first_audio_p90"]) == 500
    assert m["prefill_tokens"] == 30 and m["useful_tokens"] == 15
    assert m["wasted_prefill_pct"] == 50.0


def test_router_only_turns_do_not_crash():
    finals = {1: 5.0, 2: 6.0}
    records = [rec("cache_hit", 1, 5.01, clip="greeting"), rec("cache_hit", 2, 6.02, clip="thanks")]
    m = measure(records, finals, {1: 100, 2: 100})
    assert m["n_first_token"] == 0 and m["first_token_p50"] is None
    assert round(m["first_audio_p50"]) == 10
    assert m["wasted_prefill_pct"] is None
    assert "n/a" in row("router", m, "q4")


def test_turn_without_gen_done_counts_no_useful_tokens():
    m = measure([rec("prefill", 1, 1.0, prompt_n=8)], {1: 2.0}, {1: 50})
    assert m["wasted_prefill_pct"] == 100.0


def test_base_warm_up_is_not_wasted_prefill():
    records = [rec("prefill", 1, 1.0, kind="base", prompt_n=30), rec("prefill", 1, 1.5, kind="stable", prompt_n=8)]
    m = measure(records, {1: 2.0}, {1: 50})
    assert m["warm_tokens"] == 30 and m["prefill_tokens"] == 8


def test_ablation_turns_file():
    turns = load_turns()
    kinds = [t["kind"] for t in turns]
    assert len(turns) == 12
    assert kinds.count("hesitation") == 3 and kinds.count("correction") == 2 and kinds.count("router") == 2
