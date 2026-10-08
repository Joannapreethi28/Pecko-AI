"""ears/SPEC.md "Ears ablation rows": fixed 800ms vs fixed 400ms vs our
fusion endpointer (as shipped -- includes O1 speculative ASR finish + O2
real Smart Turn, since those run unconditionally in "fusion" mode; this
doesn't decompose into the spec's more granular D/E/F rows separately,
said plainly rather than claimed).

Time-boxed: Moonshine Small's decode cost (~300-450 CPU-s per 25s clip,
measured in scripts/measure.py) makes a full 33-clip x 3-mode ablation take
hours. This runs 3 clips, each trimmed to its first ~10s, so the comparison
is real and reproducible but deliberately small -- said plainly in the
printed report, not hidden.

Run: python scripts/ablation.py
"""
import csv
import io
import json
import pathlib
import statistics
import sys
import time

import jiwer
import numpy as np
import soundfile as sf

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from common.clock import VirtualClock
from ears.audio_io import WavFrameSource
from ears.normalize import ends_with_dangling_word
from ears.stage import Ears

CLIPS_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "clips"
TMP_DIR = CLIPS_DIR / "_ablation_tmp"
TRIM_SECONDS = 10.0
SAMPLE_CLIPS = ["hindi1.wav", "tamil1.wav", "telugu10.wav"]
MODES = ["fixed_800", "fixed_400", "fusion"]
REFERENCE_PREFIX = "please call stella ask her to bring these things with her from the store"


def make_trimmed_clips() -> list[pathlib.Path]:
    TMP_DIR.mkdir(exist_ok=True)
    out = []
    for name in SAMPLE_CLIPS:
        src = CLIPS_DIR / name
        data, sr = sf.read(src, dtype="float32")
        trimmed = data[: int(TRIM_SECONDS * sr)]
        dest = TMP_DIR / name
        sf.write(dest, trimmed, sr)
        out.append(dest)
    return out


def run_clip(wav_path: pathlib.Path, ears: Ears, clock: VirtualClock) -> list[dict]:
    buf = io.StringIO()
    ears.out_stream = buf
    ears.reset_session()
    ears.push_to_talk()
    source = WavFrameSource(str(wav_path), clock, realtime=False)
    for frame, t_cap in source.frames():
        ears.feed(frame, t_cap)
    return [json.loads(l) for l in buf.getvalue().splitlines() if l.strip().startswith('{"type"')]


def run_mode(mode: str, clips: list[pathlib.Path]) -> dict:
    clock = VirtualClock()
    ears = Ears(tier=0, clock=clock, endpointer_mode=mode)
    ears.start()

    delays_ms, wers, cutoffs, total = [], [], 0, 0
    t0 = time.perf_counter()
    for clip in clips:
        lines = run_clip(clip, ears, clock)
        finals = [l for l in lines if l["type"] == "final"]
        total += len(finals)
        for f in finals:
            delays_ms.append(1000 * (f["t_endpoint"] - f["t_eos"]))
            if ends_with_dangling_word(f["norm"]):
                cutoffs += 1
        hyp = " ".join(f["norm"] for f in finals)
        if hyp.strip():
            wers.append(jiwer.wer(REFERENCE_PREFIX, hyp))
    wall_s = time.perf_counter() - t0

    return {
        "mode": mode,
        "finals": total,
        "delay_p50": statistics.median(delays_ms) if delays_ms else None,
        "delay_p90": sorted(delays_ms)[int(0.9 * len(delays_ms)) - 1] if delays_ms else None,
        "suspected_cutoffs": cutoffs,
        "wer_mean": statistics.mean(wers) if wers else None,
        "wall_s": wall_s,
    }


def main() -> None:
    clips = make_trimmed_clips()
    print(f"ablation sample: {[c.name for c in clips]}, each trimmed to {TRIM_SECONDS}s", file=sys.stderr)

    results = []
    for mode in MODES:
        print(f"\n=== mode: {mode} ===", file=sys.stderr)
        r = run_mode(mode, clips)
        results.append(r)
        print(r, file=sys.stderr)

    print("\n=== ABLATION (scripts/ablation.py, 3 trimmed clips, real measurement) ===")
    print("| Config | `final`s | delay p50 (ms) | delay p90 (ms) | suspected cutoffs | WER mean | wall s |")
    print("|---|---|---|---|---|---|---|")
    for r in results:
        def fmt(x, nd=0):
            return f"{x:.{nd}f}" if x is not None else "n/a"
        print(f"| {r['mode']} | {r['finals']} | {fmt(r['delay_p50'])} | {fmt(r['delay_p90'])} | "
              f"{r['suspected_cutoffs']} | {fmt(r['wer_mean'], 3)} | {fmt(r['wall_s'], 1)} |")


if __name__ == "__main__":
    main()
