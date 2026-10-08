"""Typed-text mock for Brain: type a line, see the chunks Voice would receive, with timings.

    python -m brain.mock_cli [--port 8080] [--tier 0] [--speak]

--speak: instead of one instant `final`, simulate speech (partials, tentative_final, pause, final)
so early prefill can be seen working. Start llama-server first (brain/SPEC.md)."""
from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path

from brain.llama_client import LlamaClient
from brain.prompt import normalize
from brain.sim import speak
from brain.stage import BrainStage
from common.clock import now
from common.log import EventLog


def turn_summary(records: list[dict], turn: int, t_final: float) -> str:
    """One line from this turn's log records (first_token / first_chunk / gen_done)."""
    mine = [r for r in records if r["turn"] == turn]
    first = {r["event"]: r for r in mine}.get
    done = first("gen_done")
    parts = []
    for ev in ("first_token", "first_chunk"):
        r = first(ev)
        parts.append(f"{ev} {(r['t'] - t_final) * 1000:.0f} ms" if r else f"{ev} n/a")
    if done:
        x = done["extra"]
        parts.append(f"prompt tokens computed {x['prompt_n']}, reused from cache {x['cache_n']}")
        parts.append(f"decode {x['decode_tps']} tok/s")
    return " | ".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--tier", type=int, default=0)
    ap.add_argument("--speak", action="store_true", help="simulate speech so early prefill runs")
    args = ap.parse_args()

    events = Path("data/results/brain_mock_events.jsonl")
    events.parent.mkdir(parents=True, exist_ok=True)
    log = EventLog("brain", events, keep=True)
    done = threading.Event()
    t_final = [0.0]

    def emit(msg: dict) -> None:
        print(f"+{(now() - t_final[0]) * 1000:7.0f} ms  {msg}")
        if msg.get("last"):
            done.set()

    stage = BrainStage(emit, log, LlamaClient(port=args.port), tier=args.tier)
    stage.start()
    print("Brain ready. Type a line (empty line or Ctrl-D to quit).")
    turn = 0
    try:
        while True:
            try:
                line = input("you> ").strip()
            except EOFError:
                break
            if not line:
                break
            turn += 1
            done.clear()
            if args.speak:
                t_final[0] = now()   # emit() uses it; speak() returns the real value just before final
                t_final[0] = speak(stage, turn, line)
            else:
                t_final[0] = now()
                stage.feed({"type": "final", "turn": turn, "text": line, "norm": normalize(line),
                            "t_eos": t_final[0], "t_endpoint": t_final[0]})
            if not done.wait(timeout=120):
                print("(timed out waiting for the last chunk)")
                continue
            time.sleep(0.2)   # gen_done is logged just after the last chunk
            print(turn_summary(log.records, turn, t_final[0]))
    finally:
        stage.stop()
        log.close()


if __name__ == "__main__":
    main()
