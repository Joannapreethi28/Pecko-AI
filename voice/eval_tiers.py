"""Voice ladder measurement (CONTRACT tier table; Spine's transition check). No audio is played.

    python -m voice.eval_tiers              # walks T0 -> T1 -> T2 -> T3 -> T0 with the real engines
    python -m voice.eval_tiers --tag ubuntu-cap

Per tier: switch time, process RSS before/after (memory transition), uncached 8-word phrase
(first chunk -> first PCM), and a cached intent (must stay L4 on every tier).
"""
import argparse
import json
import platform
import time
from pathlib import Path

import psutil

from .engine import TIERS
from .stage import VoiceStage

ROOT = Path(__file__).resolve().parent.parent
PHRASES = ["The library closes at six on weekdays.", "Trains to Chennai leave every two hours.",
           "Green tea has less caffeine than coffee.", "The river floods almost every monsoon."]


def main():
    ap = argparse.ArgumentParser(prog="python -m voice.eval_tiers")
    ap.add_argument("--tag", default=f"{platform.system().lower()}-dev")
    a = ap.parse_args()
    ev, done = [], {}

    def on_event(m):
        ev.append(m)
        if m.get("type") == "turn_summary":
            done[m["turn"]] = m

    v = VoiceStage(on_event=on_event, audio=False)
    info = v.start()
    proc = psutil.Process()
    rows, turn = [], 0

    def run_turn(msg_fn):
        nonlocal turn
        turn += 1
        msg_fn(turn)
        end = time.perf_counter() + 15
        while turn not in done and time.perf_counter() < end:
            time.sleep(0.002)
        return done.get(turn, {})

    for i, n in enumerate([0, 1, 2, 3, 0]):
        sw = {}
        if i:
            k = len(ev)
            v.set_tier(n)
            end = time.perf_counter() + 30
            while not any(e.get("type") == "tier_switch" for e in ev[k:]) and time.perf_counter() < end:
                if v.tier == n and any(e.get("type") == "tier_switch" for e in ev[k:]):
                    break
                time.sleep(0.005)
            sw = next((e for e in ev[k:] if e.get("type") == "tier_switch"), {})
        phrase = PHRASES[i % len(PHRASES)] if i < len(PHRASES) else PHRASES[0] + " Again."
        s = run_turn(lambda t: v.feed({"type": "chunk", "turn": t, "gen": 1, "seq": 0, "text": phrase, "last": True}))
        r_ms = (s["t_pcm_ready"] - s["t_first_chunk"]) * 1000 if s.get("t_pcm_ready") else None
        c = run_turn(lambda t: v.feed({"type": "cached", "turn": t, "gen": 1, "clip": "who_are_you", "last": True}))
        row = {"tier": v.tier, "engine": v.engine.pack, "cache_voice": TIERS[v.tier]["cache"],
               "switch_ms": sw.get("switch_ms"), "reloaded": sw.get("reloaded"),
               "rss_before_mb": sw.get("rss_before_mb"), "rss_after_mb": sw.get("rss_after_mb") or round(proc.memory_info().rss / 1e6),
               "uncached_8w_ms": round(r_ms, 1) if r_ms is not None else None,
               "cached_layer": c.get("first_layer"), "cache_missing": sw.get("cache_missing")}
        rows.append(row)
        print(f"  T{row['tier']} {row['engine']:32s} switch {row['switch_ms']} ms · RSS {row['rss_before_mb']} → "
              f"{row['rss_after_mb']} MB · uncached 8w {row['uncached_8w_ms']} ms · cached intent {row['cached_layer']}")
    v.stop()
    out = ROOT / "data" / "results" / f"voice_tiers_{a.tag}.json"
    out.write_text(json.dumps({"tag": a.tag, "start": info, "rows": rows}, indent=1), encoding="utf-8")
    md = [f"## Voice ladder · {a.tag} · {time.strftime('%Y-%m-%d %H:%M')}",
          "Walk T0 → T1 → T2 → T3 → T0, switches between turns, old voice unloaded before the new one loads. "
          "NullPlayer (no device). RSS = whole Python process.", "",
          "| Tier | engine | cached clips from | switch ms | reload | RSS before → after MB | uncached 8-word phrase ms | cached intent |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| T{r['tier']} | {r['engine'].replace('vits-piper-en_US-', '')} | {r['cache_voice'].replace('vits-piper-en_US-', '')} | "
                  f"{r['switch_ms'] if r['switch_ms'] is not None else 'start'} | {r['reloaded'] if r['reloaded'] is not None else '-'} | "
                  f"{r['rss_before_mb'] or '-'} → {r['rss_after_mb']} | {r['uncached_8w_ms']} | {r['cached_layer']} |")
    res = ROOT / "voice" / "RESULTS.md"
    txt = res.read_text(encoding="utf-8")
    i = txt.find("## Voice ladder")
    txt = txt[:i].rstrip() + "\n" if i >= 0 else txt.rstrip() + "\n"
    res.write_text(txt + "\n" + "\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
