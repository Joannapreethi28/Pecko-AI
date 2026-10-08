"""Standalone Voice mock (no Ears/Brain/Spine needed).

    python -m voice --mock voice/sentences.txt               # A/B: v2.1 hold-and-release vs plain v2
    python -m voice --mock voice/sentences.txt --mode hold   # only one mode
    options: --ttft-ms 250 --word-ms 60 --commit-ms 400 --no-extras --tier 1 --barge-in off (half-duplex)

Timeline per turn, t0 = "user stopped talking" (acoustic end):
  hold   (v2.1): Brain streams held chunks from t0+ttft; Spine sends `commit` at t0+commit_ms (= C).
  nohold (v2)  : Brain only starts after C, chunks are played as they arrive.
Extras: an Ears `cancel` + new gen turn (held gen 1 must never be heard) and a barge-in turn.
Reports per turn, relative to t0: C, R (first clause PCM ready), first audio, chunk->sound, gaps.
"""
import argparse
import json
import statistics
import threading
import time
from pathlib import Path

from .stage import VoiceStage
from .vlog import now

ROOT = Path(__file__).resolve().parent.parent


class MockBrainSpine:
    """Streams one reply the way Brain will (first chunk at first punctuation >= 2 words or 6 words)."""

    def __init__(self, feed, ttft, word_s):
        self.feed, self.ttft, self.word_s = feed, ttft, word_s

    def stream(self, turn, gen, text, start_at, held, stop_evt=None):
        while now() < start_at:
            time.sleep(min(0.005, max(0.0, start_at - now())))
        time.sleep(self.ttft)
        words, buf, seq = text.split(), [], 0
        for i, w in enumerate(words):
            if stop_evt is not None and stop_evt.is_set():
                return
            if i:
                time.sleep(self.word_s)
            buf.append(w)
            last = i == len(words) - 1
            if last or (w[-1] in ",.?!;:" and len(buf) >= 2) or (seq == 0 and len(buf) >= 6):
                msg = {"type": "chunk", "turn": turn, "gen": gen, "seq": seq, "text": " ".join(buf) + " "}
                if held:
                    msg["held"] = True
                if last:
                    msg["last"] = True
                self.feed(msg)
                seq, buf = seq + 1, []

    def commit_at(self, turn, gen, t):
        while now() < t:
            time.sleep(min(0.005, max(0.0, t - now())))
        self.feed({"type": "commit", "turn": turn, "gen": gen, "t": now()})


def run(args):
    replies = [l.strip() for l in Path(args.mock).read_text(encoding="utf-8").splitlines() if l.strip()]
    done = {}

    def on_event(m):
        if m["type"] == "turn_summary" and m["turn"] in done:
            done[m["turn"]]["summary"] = m
            done[m["turn"]]["evt"].set()

    v = VoiceStage(on_event=on_event, tier=args.tier, barge_in=args.barge_in == "on")
    info = v.start()
    print(f"Voice ready: {info}")
    bs = MockBrainSpine(v.feed, args.ttft_ms / 1000, args.word_ms / 1000)
    commit_s = args.commit_ms / 1000
    rows, turn = [], 0

    def one(text, mode, scenario="normal"):
        nonlocal turn
        turn += 1
        t = turn
        done[t] = {"evt": threading.Event()}
        t0 = now() + 0.05
        C = t0 + commit_s
        threads = []
        if scenario == "cancel":
            stop1 = threading.Event()
            threads.append(threading.Thread(target=bs.stream, args=(t, 1, "Wrong guess, this must never be heard.", t0, True, stop1)))
            threads[-1].start()
            time.sleep(max(0.0, t0 + bs.ttft + 0.35 - now()))   # gen 1's first clause is synthesized and held
            stop1.set()
            v.feed({"type": "cancel", "turn": t, "t": now()})       # Ears: user kept talking
            C = now() + commit_s
            threads.append(threading.Thread(target=bs.stream, args=(t, 2, text, now(), True)))
            threads.append(threading.Thread(target=bs.commit_at, args=(t, 2, C)))
        elif mode == "hold":
            threads.append(threading.Thread(target=bs.stream, args=(t, 1, text, t0, True)))
            threads.append(threading.Thread(target=bs.commit_at, args=(t, 1, C)))
        else:
            threads.append(threading.Thread(target=bs.stream, args=(t, 1, text, C, False)))
        for th in threads:
            if not th.is_alive() and th.ident is None:
                th.start()
        if scenario == "barge":
            while v.stats.get(t, {}).get("t_first_audio") is None and not done[t]["evt"].is_set():
                time.sleep(0.01)
            time.sleep(1.2)
            v.feed({"type": "barge_in", "turn": t, "t": now()})
        done[t]["evt"].wait(30)
        time.sleep(0.25)
        s = done[t].get("summary", {})
        ms = lambda x: None if x is None else round((x - t0) * 1000)
        row = {"turn": t, "mode": mode, "scenario": scenario, "text": text[:40],
               "C_ms": ms(C), "R_ms": ms(s.get("t_pcm_ready")), "first_audio_ms": ms(s.get("t_first_audio")),
               "chunk_to_sound_ms": None if not s.get("t_first_audio") or not s.get("t_first_chunk")
               else round((s["t_first_audio"] - s["t_first_chunk"]) * 1000),
               "first_synth_ms": s.get("first_synth_ms"), "gaps": len(s.get("gaps_ms", [])),
               "gap_ms": round(sum(s.get("gaps_ms", [])), 1), "barge_stop_ms": s.get("barge_stop_ms"),
               "phrases": s.get("phrases"), "gens": s.get("gens"), "cancelled": s.get("cancelled")}
        rows.append(row)
        print(f"  t{t:<2} {mode:6} {scenario:6} C {row['C_ms']}  R {row['R_ms']}  first audio {row['first_audio_ms']} ms  "
              f"chunk->sound {row['chunk_to_sound_ms']}  gaps {row['gaps']} ({row['gap_ms']} ms)"
              + (f"  barge stop {row['barge_stop_ms']} ms" if row["barge_stop_ms"] is not None else ""))

    modes = ["hold", "nohold"] if args.mode == "both" else [args.mode]
    for mode in modes:
        print(f"\n== mode {mode} ==")
        for text in replies:
            one(text, mode)
    if not args.no_extras:
        print("\n== extras ==")
        one(replies[0], "hold", "cancel")
        one(replies[5 % len(replies)], "hold", "barge")
    v.stop()

    print("\n== summary (ms after t0 = acoustic end; Windows numbers include the device buffer "
          f"{info['out_latency_ms']} ms) ==")
    for mode in modes:
        r = [x for x in rows if x["mode"] == mode and x["scenario"] == "normal" and x["first_audio_ms"] is not None]
        if not r:
            continue
        fa = sorted(x["first_audio_ms"] for x in r)
        cs = sorted(x["chunk_to_sound_ms"] for x in r)
        p = lambda v, q: v[min(len(v) - 1, int(round(q * (len(v) - 1))))]
        print(f"  {mode:6}  first audio p50 {statistics.median(fa):.0f} / p90 {p(fa, .9)}  ·  chunk->sound p50 "
              f"{statistics.median(cs):.0f} / p90 {p(cs, .9)}  ·  turns with gaps {sum(1 for x in r if x['gaps'])}/{len(r)}"
              f"  ·  total gap {sum(x['gap_ms'] for x in r):.0f} ms  ·  R<=C on {sum(1 for x in r if x['R_ms'] <= x['C_ms'])}/{len(r)}")
    out = ROOT / "data" / "results" / "voice_p1_mock.json"
    out.write_text(json.dumps({"info": info, "args": vars(args), "rows": rows}, indent=1), encoding="utf-8")
    print(f"\nrows saved to {out.relative_to(ROOT)}  ·  event log: logs/voice.jsonl")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="python -m voice")
    ap.add_argument("--mock", required=True, help="text file, one reply per line")
    ap.add_argument("--mode", choices=["both", "hold", "nohold"], default="both")
    ap.add_argument("--ttft-ms", type=float, default=250)
    ap.add_argument("--word-ms", type=float, default=60)
    ap.add_argument("--commit-ms", type=float, default=400)
    ap.add_argument("--tier", type=int, default=0)
    ap.add_argument("--no-extras", action="store_true")
    ap.add_argument("--barge-in", choices=["on", "off"], default="on", help="off = half-duplex (ignore barge_in)")
    run(ap.parse_args())
