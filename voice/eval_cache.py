"""Cache ablation for Voice (solution.md §7 row A7, voice/SPEC.md "Voice ablation rows"). No audio is played.

    python -m voice.eval_cache                # 4 configs × 2 passes over the session, ~1–2 min
    python -m voice.eval_cache --tag ubuntu-cap

Session = the 36 held-out phrasings in tests/brain/data/router_heldout.jsonl routed by Brain's REAL router
(cached → `cached` msg, composed → time/date/day sentence, llm → a Brain-style reply from POOL), plus
time/date/day questions. Each config runs the session twice (pass 2 shows the L3 runtime memo filling).
Measures Voice's share of R: first chunk received → first PCM ready (`pcm_ready`), plus hit rate,
synthesis calls and CPU-seconds. Uses NullPlayer, so the numbers exclude the audio device.
"""
import argparse
import json
import platform
import statistics
import time
from pathlib import Path

import psutil

from brain.prompt import normalize as brain_norm
from brain.router import Router
from .stage import VoiceStage

ROOT = Path(__file__).resolve().parent.parent
HELDOUT = ROOT / "tests" / "brain" / "data" / "router_heldout.jsonl"
EXTRA = ["What time is it?", "What's the date today?", "What day is it today?"]
POOL = [  # 18 DISTINCT Brain-style replies (no repeats inside a pass); half start with a stock opener
    "Sure. Paris is the capital of France.",
    "The Eiffel Tower is about three hundred metres tall.",
    "Sorry, I can't check that because I work offline.",
    "Water boils at one hundred degrees at sea level.",
    "I'm not sure. It depends on how much memory you have.",
    "A basic Raspberry Pi costs around ₹4,500.",
    "Yes, the moon orbits the earth about once a month.",
    "Coimbatore is in Tamil Nadu, in the south of India.",
    "No, I can't browse the internet.",
    "The meeting starts at ten in room four.",
    "Okay, a light year is the distance light travels in a year.",
    "Photosynthesis lets plants turn sunlight into food.",
    "Well, most adults need seven to nine hours of sleep.",
    "The Pacific is the largest ocean on earth.",
    "Good question. Bananas are technically berries.",
    "Mount Everest is the highest mountain above sea level.",
    "Of course. Two plus two is four.",
    "The human heart beats around one hundred thousand times a day.",
]
CONFIGS = {"no cache": (), "L2": ("L2",), "L2+L3": ("L2", "L3"), "L2+L3+L4+C (full)": ("L2", "L3", "L4", "C")}


def brain_chunks(text):
    """Brain's rule: first chunk at the first , . ? ! ; : after >= 2 words (or 6 words), then the rest."""
    words = text.split()
    for i, w in enumerate(words):
        if (w[-1] in ",.?!;:" and i >= 1) or i == 5:
            head, tail = " ".join(words[:i + 1]), " ".join(words[i + 1:])
            return [head + " ", tail] if tail else [head]
    return [text]


def session():
    router = Router.load()
    rows = [json.loads(l) for l in HELDOUT.read_text(encoding="utf-8").splitlines() if l.strip()]
    turns, llm_i = [], 0
    for text in [r["text"] for r in rows] + EXTRA:
        r = router.route(brain_norm(text))
        if r.kind == "cached":
            turns.append(("cached", r.clip))
        elif r.kind == "composed":
            turns.append(("composed", r.text))
        else:
            turns.append(("llm", POOL[llm_i % len(POOL)]))   # 18 LLM turns per pass -> each reply once
            llm_i += 1
    false_hits = sum(1 for row in rows if row["expect"] is None and router.route(brain_norm(row["text"])).kind != "llm")
    should_miss = sum(1 for row in rows if row["expect"] is None)
    return turns, {"false_hits": false_hits, "should_miss": should_miss}


def run_config(layers, turns, passes=2):
    done = {}
    v = VoiceStage(on_event=lambda m: m.get("type") == "turn_summary" and done.__setitem__(m["turn"], m),
                   audio=False, cache_layers=layers)
    v.start()
    proc = psutil.Process()
    c0 = sum(proc.cpu_times()[:2])
    out, t = [], 0
    for p in range(passes):
        for kind, payload in turns:
            t += 1
            if kind == "cached":
                v.feed({"type": "cached", "turn": t, "gen": 1, "clip": payload, "last": True})
            else:
                parts = brain_chunks(payload) if kind == "llm" else [payload]
                for i, part in enumerate(parts):
                    v.feed({"type": "chunk", "turn": t, "gen": 1, "seq": i, "text": part,
                            **({"last": True} if i == len(parts) - 1 else {})})
            end = time.perf_counter() + 10
            while t not in done and time.perf_counter() < end:
                time.sleep(0.002)
            s = done.get(t, {})
            r_ms = (s["t_pcm_ready"] - s["t_first_chunk"]) * 1000 if s.get("t_pcm_ready") and s.get("t_first_chunk") else None
            out.append({"pass": p + 1, "kind": kind, "R_ms": r_ms, "first_layer": s.get("first_layer"),
                        "synth_calls": len(s.get("synth_ms", [])), "hits": sum(s.get("hits", {}).values())})
    cpu = sum(proc.cpu_times()[:2]) - c0
    v.stop()
    return out, cpu


def summarize(rows, cpu):
    r = sorted(x["R_ms"] for x in rows if x["R_ms"] is not None)
    p = lambda q: r[min(len(r) - 1, int(round(q * (len(r) - 1))))]
    first_hit = sum(1 for x in rows if x["first_layer"] not in (None, "synth"))
    return {"turns": len(rows), "R_p50_ms": round(statistics.median(r), 1), "R_p90_ms": round(p(0.9), 1),
            "first_pcm_from_cache": f"{first_hit}/{len(rows)}", "synth_calls": sum(x["synth_calls"] for x in rows),
            "cpu_s": round(cpu, 2), "cpu_ms_per_turn": round(cpu * 1000 / len(rows), 1)}


def main():
    ap = argparse.ArgumentParser(prog="python -m voice.eval_cache")
    ap.add_argument("--tag", default=f"{platform.system().lower()}-dev")
    a = ap.parse_args()
    turns, router = session()
    kinds = {k: sum(1 for t in turns if t[0] == k) for k in ("cached", "composed", "llm")}
    print(f"Session: {len(turns)} turns/pass {kinds} · router false hits {router['false_hits']}/{router['should_miss']}")
    results = {}
    for name, layers in CONFIGS.items():
        rows, cpu = run_config(layers, turns)
        results[name] = {"all": summarize(rows, cpu),
                         "pass1": summarize([x for x in rows if x["pass"] == 1], cpu / 2),
                         "pass2": summarize([x for x in rows if x["pass"] == 2], cpu / 2),
                         "by_kind": {k: summarize([x for x in rows if x["kind"] == k], 0)
                                     for k in kinds if any(x["kind"] == k for x in rows)}}
        s = results[name]["pass1"]
        print(f"  {name:20s} pass1 R p50 {s['R_p50_ms']:6.1f} / p90 {s['R_p90_ms']:6.1f} ms · first PCM from cache "
              f"{s['first_pcm_from_cache']:>6} · synth calls {s['synth_calls']:3d} · CPU {s['cpu_ms_per_turn']:.0f} ms/turn")
    out = ROOT / "data" / "results" / f"voice_cache_{a.tag}.json"
    out.write_text(json.dumps({"tag": a.tag, "session": kinds, "router": router, "results": results}, indent=1),
                   encoding="utf-8")
    md = [f"## Cache ablation · {a.tag} · {time.strftime('%Y-%m-%d %H:%M')}",
          f"Session per pass: {len(turns)} turns ({kinds['cached']} cached intents, {kinds['composed']} composed time/date/day, "
          f"{kinds['llm']} LLM-style replies) from Brain's real router on the held-out phrasings; 2 passes. "
          f"R = first chunk received → first PCM ready (Voice share of R, NullPlayer, no device latency). "
          f"Router false hits on should-go-to-LLM rows: **{router['false_hits']}/{router['should_miss']}**.", "",
          "Headline = **pass 1** (every question unseen). Pass 2 repeats the session (user asks the same things again), "
          "which is the only place the L3 runtime memo can help.", "",
          "| Config | pass 1 R p50 / p90 ms | pass 1 first PCM from cache | pass 1 synth calls | pass 1 CPU ms/turn | pass 2 R p50 / p90 ms | pass 2 from cache |",
          "|---|---|---|---|---|---|---|"]
    for name, r in results.items():
        s, s2 = r["pass1"], r["pass2"]
        md.append(f"| {name} | **{s['R_p50_ms']:.0f}** / {s['R_p90_ms']:.0f} | {s['first_pcm_from_cache']} | {s['synth_calls']} | "
                  f"{s['cpu_ms_per_turn']:.0f} | {s2['R_p50_ms']:.0f} / {s2['R_p90_ms']:.0f} | {s2['first_pcm_from_cache']} |")
    rows_full = results["L2+L3+L4+C (full)"]["by_kind"]
    md += ["", "Full cache, both passes, by turn kind (R p50 / p90 ms): "
           + " · ".join(f"{k} {v['R_p50_ms']:.0f} / {v['R_p90_ms']:.0f}" for k, v in rows_full.items()), ""]
    res = ROOT / "voice" / "RESULTS.md"
    txt = res.read_text(encoding="utf-8") if res.exists() else "# VOICE results\n\n"
    res.write_text(txt.rstrip() + "\n\n" + "\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
