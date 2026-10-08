"""Voice benchmark grid + quantization A/B (voice/SPEC.md "First task", solution.md §2 Quant 15%).

    python -m voice.bench                    # full grid, ~5 min, no audio is played
    python -m voice.bench --quick            # medium + low only, 1 thread, 3 reps
    python -m voice.bench --tag ubuntu-cap   # label for the results file (default: <os>-dev)

Grid: lessac {low, medium, high} × {fp32, fp16, int8} × threads {1, 2} × condition {solo, corun}
      × text {3, 8, 20 words}, `--reps` timed runs each after warm-up.
corun = a 1-thread CPU hog (simulates Brain decoding) pinned to the SAME two cores as the benchmark,
        which is what Voice faces inside the 2-CPU cap while Brain is generating.
Each (pack, threads, condition) runs in a fresh process so load time and peak RAM are clean.
Timing uses time.perf_counter() (QueryPerformanceCounter on Windows; monotonic() is 15.6 ms there on
Python < 3.13, see brain/gotcha.md G8).

Outputs: data/results/voice_bench_<tag>.json, data/results/voice_samples/<pack>.wav (ear A/B),
         voice/RESULTS.md section for <tag> with the decision rules applied.
"""
import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np
import psutil

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "results"
SAMPLES = OUT / "voice_samples"
SIZES = ["low", "medium", "high"]
PRECS = ["fp32", "fp16", "int8"]
TEXTS = {
    3: "Sure, no problem.",
    8: "The meeting starts at ten in room four.",
    20: "Water boils at one hundred degrees at sea level, but on a high mountain it boils a little earlier than that.",
}
SAMPLE_TEXT = "Paris is the capital of France, and it is also the largest city in the country."
FIRST_PHRASE_BUDGET_MS = 150   # SPEC: first phrase synth target
INT8_MIN_GAIN = 0.15           # SPEC: quantized must be >= 15% faster or we ship fp32
HOG = ("import os\nos.environ['OMP_NUM_THREADS']='1'\nimport numpy as np\n"
       "a=np.random.rand(384,384).astype(np.float32)\nwhile True:\n    a=(a@a)*1e-3+0.5\n")


def pack_name(size, prec):
    return f"vits-piper-en_US-lessac-{size}" + ("" if prec == "fp32" else f"-{prec}")


CORES_OVERRIDE = None


def bench_cores():
    """Two logical CPUs on two DIFFERENT physical cores, preferring performance cores.
    Hyperthread siblings (e.g. 2,3 on Intel Windows numbering) share one core and would fake a 2-CPU cap."""
    if CORES_OVERRIDE:
        return CORES_OVERRIDE
    n = psutil.cpu_count(logical=True) or 1
    if n < 2:
        return [0]
    if sys.platform.startswith("linux"):
        try:
            base = Path("/sys/devices/system/cpu")
            freq = lambda c: int((base / f"cpu{c}/cpufreq/cpuinfo_max_freq").read_text())
            sib = lambda c: (base / f"cpu{c}/topology/thread_siblings_list").read_text().strip()
            cpus = sorted(range(n), key=lambda c: -freq(c))       # P-cores first on hybrid CPUs
            pick, seen = [], set()
            for c in cpus:
                if sib(c) not in seen:
                    seen.add(sib(c)); pick.append(c)
                if len(pick) == 2:
                    return sorted(pick)
        except Exception:
            pass
        return [0, 1]
    phys = psutil.cpu_count(logical=False) or n
    return [0, 2] if n > phys else [0, 1]   # Windows lists sibling pairs first (0,1 | 2,3 ...)


def peak_rss_mb(proc):
    mi = proc.memory_info()
    if hasattr(mi, "peak_wset"):           # Windows
        return mi.peak_wset / 1e6
    try:
        import resource                      # Linux: ru_maxrss is KiB
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except Exception:
        return mi.rss / 1e6


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


# ------------------------------------------------------------------ child: one config, fresh process
def child(pack, threads, cond, reps, save_sample):
    proc = psutil.Process()
    cores = bench_cores()
    hog = None
    try:
        proc.cpu_affinity(cores)
    except Exception:
        pass
    if cond == "corun":
        hog = subprocess.Popen([sys.executable, "-c", HOG], env=dict(os.environ, OMP_NUM_THREADS="1",
                               OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1"))
        try:
            psutil.Process(hog.pid).cpu_affinity(cores)
        except Exception:
            pass
        time.sleep(0.5)
    try:
        sys.path.insert(0, str(ROOT))
        from voice.engine import TTSEngine, OUT_SR
        rss0 = proc.memory_info().rss / 1e6
        t = time.perf_counter()
        try:
            eng = TTSEngine(pack, threads=threads, warmup=0)
        except Exception as e:
            print("RESULT " + json.dumps({"pack": pack, "threads": threads, "cond": cond, "error": str(e)[:300]}))
            return
        load_ms = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        eng.synth(TEXTS[8])
        cold_ms = (time.perf_counter() - t) * 1000
        eng.synth(TEXTS[3])                              # second warm-up
        res = {"pack": pack, "threads": threads, "cond": cond, "cores": cores, "load_ms": round(load_ms, 1),
               "cold_8w_ms": round(cold_ms, 1), "native_sr": eng.native_sr, "rss_loaded_mb": None, "by_len": {}}
        res["rss_loaded_mb"] = round(proc.memory_info().rss / 1e6 - rss0, 1)
        for n, text in TEXTS.items():
            ms, cpu_s, dur = [], [], 0.0
            for _ in range(reps):
                c0 = sum(proc.cpu_times()[:2])
                t = time.perf_counter()
                x = eng.synth(text)
                wall = time.perf_counter() - t
                ms.append(wall * 1000)
                cpu_s.append(sum(proc.cpu_times()[:2]) - c0)
                dur = len(x) / OUT_SR
            res["by_len"][n] = {"p50_ms": round(statistics.median(ms), 1), "p90_ms": round(pct(ms, 0.9), 1),
                                "min_ms": round(min(ms), 1), "audio_s": round(dur, 2),
                                "rtf": round(statistics.median(ms) / 1000 / dur, 3),
                                "cores_used": round(statistics.median(cpu_s) / (statistics.median(ms) / 1000), 2)}
        res["peak_rss_mb"] = round(peak_rss_mb(proc), 1)
        if save_sample:
            SAMPLES.mkdir(parents=True, exist_ok=True)
            x = eng.synth(SAMPLE_TEXT)
            with wave.open(str(SAMPLES / f"{pack}.wav"), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(OUT_SR)
                w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
        print("RESULT " + json.dumps(res), flush=True)
    finally:
        if hog is not None:
            hog.kill()


# ------------------------------------------------------------------ parent: grid, decisions, report
def machine_info(tag):
    import sherpa_onnx
    cpu = platform.processor()
    try:
        if sys.platform.startswith("linux"):
            cpu = next(l.split(":", 1)[1].strip() for l in open("/proc/cpuinfo") if l.startswith("model name"))
    except Exception:
        pass
    return {"tag": tag, "os": f"{platform.system()} {platform.release()}", "cpu": cpu,
            "logical_cpus": psutil.cpu_count(), "ram_gb": round(psutil.virtual_memory().total / 1e9, 1),
            "python": platform.python_version(), "sherpa_onnx": sherpa_onnx.__version__,
            "bench_cores": bench_cores(), "when": time.strftime("%Y-%m-%d %H:%M"), "power": power_state()}


def power_state():
    try:
        b = psutil.sensors_battery()
        return "no battery" if b is None else ("plugged in" if b.power_plugged else f"ON BATTERY ({b.percent:.0f}%)")
    except Exception:
        return "unknown"


def get(rows, size, prec, threads, cond):
    p = pack_name(size, prec)
    return next((r for r in rows if r["pack"] == p and r["threads"] == threads and r["cond"] == cond
                 and "error" not in r), None)


def decide(rows, cond):
    """Apply the SPEC rules. Returns (decisions dict, notes list)."""
    notes, best_prec = [], {}
    for s in SIZES:
        base = get(rows, s, "fp32", 1, cond)
        if not base:
            continue
        b = base["by_len"]["8"]["p50_ms"]
        choice, gain_best = "fp32", 0.0
        for q in ("fp16", "int8"):
            r = get(rows, s, q, 1, cond)
            if not r:
                continue
            g = (b - r["by_len"]["8"]["p50_ms"]) / b
            notes.append(f"{s}: {q} vs fp32 at 1 thread ({cond}, 8 words): {b:.0f} → {r['by_len']['8']['p50_ms']:.0f} ms "
                         f"= {g * 100:+.0f}% {'faster' if g > 0 else 'slower'}")
            if g >= INT8_MIN_GAIN and g > gain_best:
                choice, gain_best = q, g
        best_prec[s] = choice
    t0 = None
    for s in reversed(SIZES):                     # best quality first
        r = get(rows, s, best_prec.get(s, "fp32"), 1, cond)
        if r and r["by_len"]["8"]["p50_ms"] <= FIRST_PHRASE_BUDGET_MS:
            t0 = (s, best_prec[s])
            break
    order = [s for s in SIZES[::-1] if s in best_prec]
    t1 = None
    if t0:
        lighter = order[order.index(t0[0]) + 1:] if t0[0] in order else []
        t1 = (lighter[0], best_prec[lighter[0]]) if lighter else None
    thr = []
    for s in SIZES:
        a, b2 = get(rows, s, best_prec.get(s, "fp32"), 1, cond), get(rows, s, best_prec.get(s, "fp32"), 2, cond)
        if a and b2:
            g = (a["by_len"]["8"]["p50_ms"] - b2["by_len"]["8"]["p50_ms"]) / a["by_len"]["8"]["p50_ms"]
            thr.append(f"{s}: 2 threads vs 1 ({cond}, 8 words): {g * 100:+.0f}% "
                       f"({a['by_len']['8']['p50_ms']:.0f} → {b2['by_len']['8']['p50_ms']:.0f} ms)")
    return {"precision": best_prec, "T0": t0, "T1": t1}, notes, thr


def report(info, rows):
    lines = [f"## {info['tag']} · {info['when']}",
             f"Machine: {info['cpu']} · {info['logical_cpus']} logical CPUs · {info['ram_gb']} GB · {info['os']} · "
             f"Python {info['python']} · sherpa-onnx {info['sherpa_onnx']} · pinned to logical CPUs {info['bench_cores']} "
             f"(two different physical cores) · power: {info['power']}",
             "" if not info["tag"].endswith("-dev") else
             "> **`" + info["tag"] + "`, not judged.** Judged numbers come from Ubuntu under Spine's 2 CPU / 2 GB cgroup.", ""]
    for cond in ("corun", "solo"):
        rs = [r for r in rows if r["cond"] == cond]
        if not rs:
            continue
        lines += [f"### Synthesis time ({cond}{', 1-thread CPU hog on the same 2 cores = Brain decoding' if cond == 'corun' else ''})",
                  "| Pack | Thr | 3 w p50/p90 ms | 8 w p50/p90 ms | 20 w p50/p90 ms | RTF (8 w) | cores used | load ms | cold 1st ms | peak RAM MB |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for s in SIZES:
            for q in PRECS:
                for th in (1, 2):
                    r = get(rows, s, q, th, cond)
                    if not r:
                        continue
                    L = r["by_len"]
                    lines.append(f"| {s} {q} | {th} | {L['3']['p50_ms']:.0f} / {L['3']['p90_ms']:.0f} | "
                                 f"**{L['8']['p50_ms']:.0f}** / {L['8']['p90_ms']:.0f} | {L['20']['p50_ms']:.0f} / {L['20']['p90_ms']:.0f} | "
                                 f"{L['8']['rtf']:.3f} | {L['8']['cores_used']:.2f} | {r['load_ms']:.0f} | {r['cold_8w_ms']:.0f} | {r['peak_rss_mb']:.0f} |")
        lines.append("")
    errs = sorted({r["pack"] for r in rows if "error" in r})
    if errs:
        lines += ["### Packs that failed to load", *[f"- `{p}`: {next(r['error'] for r in rows if r['pack'] == p)[:160]}"
                                                    for p in errs], ""]
    cond = "corun" if any(r["cond"] == "corun" for r in rows) else "solo"
    dec, notes, thr = decide(rows, cond)
    lines += [f"### Decisions (rules from voice/SPEC.md, applied to the **{cond}** numbers)",
              f"- Quantization rule: a quantized pack is used only if it is ≥ {INT8_MIN_GAIN * 100:.0f}% faster than fp32."]
    lines += [f"  - {n}" for n in notes]
    lines.append(f"  - → precision per size: {dec['precision']}")
    lines.append(f"- Threads: " + ("; ".join(thr) if thr else "n/a"))
    t0, t1 = dec["T0"], dec["T1"]
    lines.append(f"- **T0 voice** = best quality whose 8-word first phrase p50 ≤ {FIRST_PHRASE_BUDGET_MS} ms: "
                 + (f"**lessac-{t0[0]} {t0[1]}**" if t0 else "**none passed; keep lessac-medium fp32 and flag it**"))
    lines.append(f"- **T1 voice** (next lighter, same speaker): " + (f"**lessac-{t1[0]} {t1[1]}**" if t1 else "n/a"))
    lines.append(f"- Ear check: compare `data/results/voice_samples/*.wav` (same sentence, every pack) before trusting a quantized pack.")
    return "\n".join(lines) + "\n", dec


def main():
    ap = argparse.ArgumentParser(prog="python -m voice.bench")
    ap.add_argument("--child", nargs=3, metavar=("PACK", "THREADS", "COND"))
    ap.add_argument("--reps", type=int, default=7)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-corun", action="store_true")
    ap.add_argument("--tag", default=f"{platform.system().lower()}-dev")
    ap.add_argument("--cores", help="comma list of logical CPUs to pin to, e.g. 0,2")
    a = ap.parse_args()
    global CORES_OVERRIDE
    if a.cores:
        CORES_OVERRIDE = [int(c) for c in a.cores.split(",")]
    if a.child:
        pack, th, cond = a.child
        child(pack, int(th), cond, a.reps, save_sample=(int(th) == 1 and cond == "solo"))
        return
    sizes, precs, threads = (["low", "medium"], PRECS, [1]) if a.quick else (SIZES, PRECS, [1, 2])
    reps = 3 if a.quick else a.reps
    conds = ["solo"] + ([] if a.no_corun else ["corun"])
    info = machine_info(a.tag)
    print(f"Voice bench · {info['cpu']} · cores {info['bench_cores']} · reps {reps} · no audio is played")
    rows = []
    jobs = [(pack_name(s, q), th, c) for c in conds for s in sizes for q in precs for th in threads]
    for i, (pack, th, cond) in enumerate(jobs, 1):
        if not (ROOT / "models" / pack).is_dir():
            print(f"  [{i}/{len(jobs)}] skip {pack} (not downloaded)")
            continue
        p = subprocess.run([sys.executable, "-m", "voice.bench", "--child", pack, str(th), cond, "--reps", str(reps)]
                           + (["--cores", a.cores] if a.cores else []),
                           cwd=ROOT, capture_output=True, text=True)
        line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT ")), None)
        if not line:
            print(f"  [{i}/{len(jobs)}] FAILED {pack} t{th} {cond}: {p.stderr.strip()[-300:]}")
            continue
        r = json.loads(line[7:])
        rows.append(r)
        if "error" in r:
            print(f"  [{i}/{len(jobs)}] LOAD FAILED {pack} t{th}: {r['error'][:120]}")
            continue
        r["by_len"] = {str(k): v for k, v in r["by_len"].items()}
        print(f"  [{i}/{len(jobs)}] {pack:38s} t{th} {cond:5s}  8w p50 {r['by_len']['8']['p50_ms']:6.1f} ms  "
              f"RTF {r['by_len']['8']['rtf']:.3f}  peak {r['peak_rss_mb']:.0f} MB", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    md, dec = report(info, rows)
    (OUT / f"voice_bench_{a.tag}.json").write_text(json.dumps({"info": info, "rows": rows, "decision": dec}, indent=1),
                                                   encoding="utf-8")
    res = ROOT / "voice" / "RESULTS.md"
    head = "# VOICE results\nGenerated by `python -m voice.bench`. One section per machine/tag; newest replaces same tag.\n\n"
    old = res.read_text(encoding="utf-8") if res.exists() else head
    parts = [p for p in old.split("\n## ") if p and not p.startswith("# VOICE") and not p.startswith(f"{a.tag} ")]
    res.write_text(head + "".join("## " + p.rstrip() + "\n\n" for p in parts) + md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
