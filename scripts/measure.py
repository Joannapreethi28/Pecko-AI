"""Phase 4: run every downloaded clip through the real Ears pipeline once and
report honestly-measured numbers for ears/RESULTS.md. No hand-labeled last-
word times exist for this substitute dataset (see data/clips/SOURCE.md), so
the headline latency number is `t_endpoint - t_eos` -- the endpointer's own
added waiting time after Silero VAD's own silence decision -- which needs no
external label at all. WER is computed per clip against the fixed paragraph
transcript (every speaker reads the same text). Idle CPU is sampled over a
few seconds of synthetic silence, not the spec's 60 s, because of the time
budget -- said plainly in the printed report.
"""
import csv
import io
import pathlib
import statistics
import sys
import time

import jiwer
import numpy as np
import psutil

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from common.clock import VirtualClock
from ears.audio_io import WavFrameSource
from ears.normalize import ends_with_dangling_word
from ears.stage import Ears

CLIPS_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "clips"
REFERENCE_TRANSCRIPT = (
    "please call stella ask her to bring these things with her from the store "
    "six spoons of fresh snow peas five thick slabs of blue cheese and maybe a "
    "snack for her brother bob we also need a small plastic snake and a big toy "
    "frog for the kids she can scoop these things into three red bags and we "
    "will go meet her wednesday at the train station"
)


def run_clip(wav_path: pathlib.Path, ears: Ears, clock: VirtualClock) -> tuple[list[dict], float]:
    import json

    buf = io.StringIO()
    ears.out_stream = buf
    ears.reset_session()
    ears.push_to_talk()
    source = WavFrameSource(str(wav_path), clock, realtime=False)
    t0 = time.process_time()
    for frame, t_cap in source.frames():
        ears.feed(frame, t_cap)
    cpu_s = time.process_time() - t0
    lines = [json.loads(l) for l in buf.getvalue().splitlines() if l.strip() and l.lstrip().startswith("{\"type\"")]
    return lines, cpu_s


def idle_cpu_percent(ears: Ears, clock: VirtualClock, seconds: float = 3.0) -> float:
    silence = np.zeros(int(16000 * seconds), dtype=np.float32)
    frame_n = 512
    proc = psutil.Process()
    cpu0 = proc.cpu_times()
    wall0 = time.monotonic()
    pos = 0
    while pos < len(silence):
        frame = silence[pos:pos + frame_n]
        clock.advance(frame_n / 16000)
        ears.feed(frame, clock.now())
        pos += frame_n
    cpu1 = proc.cpu_times()
    wall1 = time.monotonic()
    cpu_delta = (cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)
    wall_delta = wall1 - wall0
    return 100 * cpu_delta / wall_delta if wall_delta > 0 else 0.0


def main() -> None:
    manifest_path = CLIPS_DIR / "MANIFEST.csv"
    rows = list(csv.DictReader(open(manifest_path, newline="")))

    clock = VirtualClock()
    ears = Ears(tier=0, clock=clock)
    print("loading model (first run downloads weights)...", file=sys.stderr)
    ears.start()
    ears.push_to_talk()

    endpoint_delays_ms = []
    wers = []
    peak_rss = 0
    total_finals = 0
    suspected_cutoffs = 0
    proc = psutil.Process()

    for row in rows:
        wav_path = CLIPS_DIR / row["filename"].replace(".mp3", ".wav")
        if not wav_path.exists():
            continue
        lines, cpu_s = run_clip(wav_path, ears, clock)
        finals = [l for l in lines if l["type"] == "final"]
        total_finals += len(finals)
        for f in finals:
            endpoint_delays_ms.append(1000 * (f["t_endpoint"] - f["t_eos"]))
            # Proxy for a false cutoff, since we have no hand-labeled ground
            # truth (data/clips/SOURCE.md): the endpointer's own dangling-word
            # signal said the sentence looked unfinished, yet we still fired
            # `final` (the adaptive cap elapsed anyway). Not a true measured
            # cutoff rate -- said plainly, same as every other proxy here.
            if ends_with_dangling_word(f["norm"]):
                suspected_cutoffs += 1
        hyp = " ".join(f["norm"] for f in finals)
        wer_str = "n/a"
        if hyp.strip():
            wer = jiwer.wer(REFERENCE_TRANSCRIPT, hyp)
            wers.append(wer)
            wer_str = f"{wer:.2f}"
        peak_rss = max(peak_rss, proc.memory_info().rss)
        print(f"{row['filename']}: {len(finals)} final(s), wer={wer_str} cpu_s={cpu_s:.2f}", file=sys.stderr)

    idle_pct = idle_cpu_percent(ears, clock)

    print("\n=== MEASURED (Phase 4) ===")
    print(f"clips processed: {len(wers)}")
    if endpoint_delays_ms:
        print(f"endpoint delay (t_endpoint - t_eos), ms: "
              f"p50={statistics.median(endpoint_delays_ms):.0f} "
              f"p90={sorted(endpoint_delays_ms)[int(0.9*len(endpoint_delays_ms))-1]:.0f} "
              f"n={len(endpoint_delays_ms)}")
    if wers:
        print(f"WER vs fixed paragraph transcript: mean={statistics.mean(wers):.3f} "
              f"median={statistics.median(wers):.3f} (n={len(wers)} clips)")
    if total_finals:
        print(f"suspected cutoffs (dangling-word proxy, NOT hand-labeled): "
              f"{suspected_cutoffs}/{total_finals} ({100*suspected_cutoffs/total_finals:.1f}%)")
    print(f"peak RSS: {peak_rss / 1e6:.1f} MB")
    print(f"idle CPU (3 s synthetic silence, not spec's 60 s): {idle_pct:.1f}% of one core")


if __name__ == "__main__":
    main()
