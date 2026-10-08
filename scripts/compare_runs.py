"""Paired Pecko vs B0 comparison on the same WAVs (same turn order).

    python scripts/compare_runs.py data/results/run-loop5-zip data/results/baseline-loop5-b0

first audio = first_audio_out - t_eos, with t_eos = endpoint.t - endpoint.delay_s in BOTH runs (the same
Silero end-sample definition). Turns are paired by turn number (turn k = k-th WAV). A turn with no
first_audio_out is a FAILURE: it is printed and counted, never dropped. Percentiles: nearest-rank over the
successful turns only, so read them next to n and the failure count.
CPU-s/turn: cgroup CPU integrated from the 0.5 s `resources` samples between `ready` and the last
first_audio_out, divided by the number of turns (whole scope incl. llama-server; same method both runs).
Peak RAM: cgroup memory.peak (high-water mark of the whole run, including model loading); also the max
memory.current between ready and the last first audio (runtime footprint, 0.5 s sampling).
J/turn: RAPL package energy over the same window if the run logged it, else n/a (never estimated).
"""
import json
import math
import sys
from pathlib import Path


def load(run: Path) -> dict:
    ev = [json.loads(line) for line in open(run / "events.jsonl") if line.strip()]
    turns: dict = {}
    for r in ev:
        if isinstance(r.get("turn"), int) and r["turn"] > 0:
            turns.setdefault(r["turn"], {}).setdefault(r["event"], r)
    ready = next((r["t"] for r in ev if r["event"] == "ready" and r["stage"] in ("spine", "baseline")), None)
    res = [r for r in ev if r["event"] == "resources"]
    energy = [r for r in ev if r["event"] == "energy"]
    text = {}
    bus = run / "bus.jsonl"
    if bus.exists():   # Pecko's spoken text lives on the bus
        for line in open(bus):
            m = json.loads(line)["msg"]
            piece = m.get("text") if m.get("type") == "chunk" else \
                f"[cached:{m.get('clip')}]" if m.get("type") == "cached" else None
            if piece:
                text[m["turn"]] = text.get(m["turn"], "") + piece
    for t, e in turns.items():
        if "llm_done" in e:
            text[t] = e["llm_done"]["extra"].get("reply", "")
    return {"turns": turns, "ready": ready, "res": res, "energy": energy, "text": text, "name": run.name}


def first_audio_ms(e: dict):
    ep, fa = e.get("endpoint"), e.get("first_audio_out")
    if not ep or not fa:
        return None
    return (fa["t"] - (ep["t"] - ep["extra"]["delay_s"])) * 1000


def pct(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    return s[max(0, math.ceil(p / 100 * len(s)) - 1)]


def window_stats(run: dict) -> dict:
    fas = [e["first_audio_out"]["t"] for e in run["turns"].values() if "first_audio_out" in e]
    n = len(run["turns"])
    out = {"cpu_s_turn": None, "peak_mib": None, "steady_mib": None, "j_turn": None, "cpu_max": None, "mem_max": None, "oom": None}
    if run["res"]:
        last = run["res"][-1]["extra"]
        out.update(peak_mib=max(r["extra"]["memory_peak"] or 0 for r in run["res"]) / 2**20,
                   cpu_max=last["cpu_max"], mem_max=last["memory_max"], oom=last["oom_kill"])
    if run["ready"] is None or not fas or not n:
        return out
    t0, t1 = run["ready"], max(fas)
    prev, cpu = None, 0.0
    for r in run["res"]:
        if prev is not None and t0 <= r["t"] <= t1 + 0.5:   # sample r covers (prev, r]
            cpu += (r["extra"]["mean_cores"] or 0) * (r["t"] - prev)
        prev = r["t"]
    out["cpu_s_turn"] = cpu / n
    cur = [r["extra"]["memory_current"] for r in run["res"] if t0 <= r["t"] <= t1 and r["extra"]["memory_current"]]
    out["steady_mib"] = max(cur) / 2**20 if cur else None
    en = [r for r in run["energy"] if t0 <= r["t"] <= t1 + 0.5 and r["extra"].get("gross_j") is not None]
    if len(en) >= 2:
        out["j_turn"] = (en[-1]["extra"]["gross_j"] - en[0]["extra"]["gross_j"]) / n
    return out


def fmt(x, nd=0, unit=""):
    return "n/a" if x is None else f"{x:.{nd}f}{unit}"


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    p, b = load(Path(sys.argv[1])), load(Path(sys.argv[2]))
    print(f"Pecko: {p['name']}   B0: {b['name']}   (ms after end of speech t_eos)")
    print(f"{'turn':>4} | {'P C/endp':>8} {'Pecko 1st':>9} | {'B0 endpt':>8} {'B0 1st':>7} | {'B0-Pecko':>8} | transcript (Pecko / B0) -> answer")
    pf, bf, diffs, fails = [], [], [], []
    for t in sorted(set(p["turns"]) | set(b["turns"])):
        pe, be = p["turns"].get(t, {}), b["turns"].get(t, {})
        pa, ba = first_audio_ms(pe), first_audio_ms(be)
        c = None
        if pe.get("commit") and pe.get("endpoint"):
            c = (pe["commit"]["t"] - (pe["endpoint"]["t"] - pe["endpoint"]["extra"]["delay_s"])) * 1000
        elif pe.get("endpoint"):
            c = pe["endpoint"]["extra"]["delay_s"] * 1000
        bep = be["endpoint"]["extra"]["delay_s"] * 1000 if be.get("endpoint") else None
        if pa is None:
            fails.append(f"Pecko turn {t}")
        else:
            pf.append(pa)
        if ba is None:
            fails.append(f"B0 turn {t}")
        else:
            bf.append(ba)
        d = None if pa is None or ba is None else ba - pa
        if d is not None:
            diffs.append(d)
        ptx = pe.get("asr_final", {}).get("extra", {}).get("text")
        btx = be.get("asr_final", {}).get("extra", {}).get("text")
        cached = " [Pecko cached]" if pe.get("cache_hit") else ""
        print(f"{t:>4} | {fmt(c):>8} {fmt(pa):>9} | {fmt(bep):>8} {fmt(ba):>7} | {fmt(d):>8} | "
              f"{ptx!r} / {btx!r}{cached}")
        print(f"{'':>4}   Pecko: {p['text'].get(t, '')!r}   B0: {b['text'].get(t, '')!r}")
    print()
    print(f"first audio  Pecko: n={len(pf)} p50 {fmt(pct(pf, 50))} ms  p90 {fmt(pct(pf, 90))} ms  max {fmt(max(pf) if pf else None)} ms")
    print(f"first audio  B0   : n={len(bf)} p50 {fmt(pct(bf, 50))} ms  p90 {fmt(pct(bf, 90))} ms  max {fmt(max(bf) if bf else None)} ms")
    print(f"paired gap (B0 - Pecko): n={len(diffs)} p50 {fmt(pct(diffs, 50))} ms  p90 {fmt(pct(diffs, 90))} ms  "
          f"min {fmt(min(diffs) if diffs else None)} ms   Pecko faster in {sum(d > 0 for d in diffs)}/{len(diffs)} pairs")
    print(f"failures (no first audio, kept in n): {fails or 'none'}")
    ps, bs = window_stats(p), window_stats(b)
    for name, s in (("Pecko", ps), ("B0   ", bs)):
        print(f"{name}: CPU-s/turn {fmt(s['cpu_s_turn'], 2)} | peak RAM {fmt(s['peak_mib'])} MiB (incl. load) | "
              f"max RAM during turns {fmt(s['steady_mib'])} MiB | "
              f"J/turn {fmt(s['j_turn'], 1)} | cap cpu.max {s['cpu_max']} memory.max {s['mem_max']} | oom_kill {s['oom']}")
    if any(t.get("cpu_s") is not None for t in (e.get("turn_done", {}).get("extra", {}) for e in b["turns"].values())):
        per = [e["turn_done"]["extra"]["cpu_s"] for e in b["turns"].values() if "turn_done" in e]
        print(f"B0 exact cpu.stat per turn (speech start -> first audio): {per}")
    if len(pf) < 20:
        print(f"note: n={min(len(pf), len(bf))} turns; p90 of so few turns is close to the max, not a stable estimate")


if __name__ == "__main__":
    main()
