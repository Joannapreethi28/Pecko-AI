"""Brain ablation: same model, same turns, same temperature (0); only the latency features change.

    python -m brain.ablate --label q4 [--port 8080] [--reps 3] [--configs no_cache,sys_cache,...]

Run it on the Ubuntu VM under the cgroup against a running llama-server (Q4, then again with the
Q8 model + a different --label). Windows runs are `windows-dev, not judged`."""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import platform
import time
from pathlib import Path
from typing import Optional

from brain.llama_client import LlamaClient
from brain.sim import speak
from brain.stage import BrainStage
from brain.tiers import TIERS
from common.log import EventLog

CONFIGS = ("no_cache", "sys_cache", "early_stable", "early_tentative", "router")
TURNS_PATH = Path(__file__).with_name("ablation_turns.jsonl")


def percentile(values: list[float], p: float) -> Optional[float]:
    """Nearest-rank percentile (p in 0..100); None for no data."""
    if not values:
        return None
    s = sorted(values)
    return s[max(1, math.ceil(p / 100.0 * len(s))) - 1]


def measure(records: list[dict], finals: dict[int, float], base_ns: dict[int, int]) -> dict:
    """Turn raw log records into one result row.

    records = EventLog records; finals = turn -> time `final` was fed; base_ns = turn -> tokens in the
    cached base prompt. Router-only turns have no first_token and are skipped for that column."""
    by_turn: dict[int, dict[str, dict]] = {}
    prefilled: dict[int, int] = {}
    for r in records:
        turn = r["turn"]
        if turn not in finals:
            continue
        if r["event"] == "prefill":
            prefilled[turn] = prefilled.get(turn, 0) + r["extra"].get("prompt_n", 0)
        else:
            by_turn.setdefault(turn, {}).setdefault(r["event"], r)   # first occurrence wins
    first_token, first_audio = [], []
    prefill_total, useful_total = 0, 0
    for turn, t_final in finals.items():
        ev = by_turn.get(turn, {})
        if "first_token" in ev:
            first_token.append((ev["first_token"]["t"] - t_final) * 1000)
        audio = ev.get("first_chunk") or ev.get("cache_hit")
        if audio:
            first_audio.append((audio["t"] - t_final) * 1000)
        done = ev.get("gen_done")
        prefill_total += prefilled.get(turn, 0)
        if done:
            useful_total += max(0, done["extra"].get("cache_n", 0) - base_ns.get(turn, 0))
    wasted = None
    if prefill_total > 0:
        wasted = round(100.0 * max(0, prefill_total - useful_total) / prefill_total, 1)
    return {"n": len(finals), "n_first_token": len(first_token),
            "first_token_p50": percentile(first_token, 50), "first_token_p90": percentile(first_token, 90),
            "first_audio_p50": percentile(first_audio, 50), "first_audio_p90": percentile(first_audio, 90),
            "prefill_tokens": prefill_total, "useful_tokens": useful_total, "wasted_prefill_pct": wasted}


def _fmt(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:.0f}"


def row(config: str, m: dict, label: str) -> str:
    wasted = "n/a" if m["wasted_prefill_pct"] is None else f"{m['wasted_prefill_pct']}%"
    return (f"| {config} | {_fmt(m['first_token_p50'])} / {_fmt(m['first_token_p90'])} | "
            f"{_fmt(m['first_audio_p50'])} / {_fmt(m['first_audio_p90'])} | {wasted} | {m['n']} | "
            f"{label}, {platform.system().lower()} |")


def load_turns(path: Path = TURNS_PATH) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_stage(config: str, client: LlamaClient, log: EventLog, emit) -> BrainStage:
    prefill = {"early_stable": "stable"}.get(config, "early")
    tiers = {0: dataclasses.replace(TIERS[0], prefill=prefill)}
    router = None
    if config == "router":
        from brain.router import Router   # lazy: only this config needs it
        router = Router.load()
    return BrainStage(emit, log, client, tier=0, tiers=tiers, router=router, temperature=0.0,
                      early_prefill=config not in ("no_cache", "sys_cache"),
                      cache_prompt=config != "no_cache")


def _wait_turn_done(log: EventLog, turn: int, timeout: float = 90.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if any(r["turn"] == turn and r["event"] in ("gen_done", "cache_hit") for r in list(log.records)):
            return
        time.sleep(0.05)


def run_config(config: str, client: LlamaClient, turns: list[dict], reps: int, out) -> dict:
    """Play every turn `reps` times (fresh stage per rep so history never leaks) and measure."""
    all_records: list[dict] = []
    finals: dict[int, float] = {}
    base_ns: dict[int, int] = {}
    for rep in range(reps):
        log = EventLog("brain", keep=True)
        stage = build_stage(config, client, log, lambda msg: None)
        stage.start()
        try:
            for i, spec in enumerate(turns):
                turn = rep * 1000 + i + 1            # unique across reps so records never collide
                base_ns[turn] = len(client.tokenize(stage.base_prompt()))   # outside the timed window
                finals[turn] = speak(stage, turn, spec["text"])
                _wait_turn_done(log, turn)
        finally:
            stage.stop()
        all_records += log.records
        for r in log.records:
            out.write(json.dumps({"config": config, "rep": rep, **r}) + "\n")
    return measure(all_records, finals, base_ns)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--label", required=True, help="e.g. q4 or q8")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--configs", default=",".join(CONFIGS))
    args = ap.parse_args()
    client, turns = LlamaClient(port=args.port), load_turns()
    out_path = Path(f"data/results/ablation_{args.label}.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with out_path.open("w", encoding="utf-8") as out:
        for config in args.configs.split(","):
            rows.append(row(config, run_config(config, client, turns, args.reps, out), args.label))
            print(rows[-1], flush=True)
    print("\n| config | first_token p50/p90 ms | first audio p50/p90 ms | wasted prefill | n | platform |")
    print("|---|---|---|---|---|---|")
    print("\n".join(rows))


if __name__ == "__main__":
    main()
