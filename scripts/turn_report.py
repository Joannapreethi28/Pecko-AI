"""Per-turn latency report for one run: python scripts/turn_report.py data/results/run-<time>
Times are ms after end of speech (t_eos as stamped by Ears). C = commit, R = first clause PCM ready."""
import json
import sys
from pathlib import Path

run = Path(sys.argv[1])
ev = [json.loads(line) for line in open(run / "events.jsonl")]
by = {}
for r in ev:
    if isinstance(r.get("turn"), int) and r["turn"] > 0:
        by.setdefault(r["turn"], {}).setdefault(r["event"], r)
first_audio = []
for t, e in sorted(by.items()):
    ep = e.get("endpoint")
    if not ep:
        print(f"turn {t}: no endpoint (dropped or unfinished)")
        continue
    t0 = ep["t"] - ep["extra"]["delay_s"]
    ms = lambda name: None if name not in e else round((e[name]["t"] - t0) * 1000)
    text = e.get("asr_final", {}).get("extra", {}).get("text")
    fa = ms("first_audio_out")
    if fa is not None:
        first_audio.append(fa)
    print(f"turn {t}: {text!r} | endpoint {ms('endpoint')} | C {ms('commit')} | R {ms('pcm_ready')} | "
          f"first audio {fa} ms | held match {e.get('held_valid', {}).get('extra', {}).get('match')}")
res = [r["extra"] for r in ev if r["event"] == "resources"]
if res:
    print(f"cgroup: cpu.max {res[-1]['cpu_max']} | memory.max {res[-1]['memory_max']} | "
          f"peak {max(r['memory_peak'] or 0 for r in res) / 2**20:.0f} MiB | oom_kill {res[-1]['oom_kill']}")
if first_audio:
    s = sorted(first_audio)
    print(f"first audio after EOS: n={len(s)} median {s[len(s) // 2]} ms, max {s[-1]} ms")
bus = run / "bus.jsonl"
if bus.exists():
    for line in open(bus):
        m = json.loads(line)["msg"]
        if m["type"] in ("chunk", "cached") and (m.get("text") or m.get("clip")):
            print("   ", m["turn"], m.get("text") or f"[cached:{m['clip']}]")
