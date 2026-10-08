"""Phase 4 (Spine's "transition check", docs/CONTRACT.md's last line): measure
model-load time + peak RSS at T0, then the T0->T1 tier-switch time + peak RSS
during the switch, via `Ears.set_tier()` -> `MoonshineASR.set_tier()` (which
currently reloads lazily by calling `start()` again -- see
ears/backends/asr_moonshine.py). Also sanity-checks both tiers can actually
transcribe a real clip, so a model-swap bug doesn't hide behind a clean timer.

Run: python scripts/test_tier_switch.py [path/to/clip.wav]
Defaults to the first clip found in data/clips/ if none is given.

Numbers printed under "=== MEASURED ===" are real measurements on this
machine, this run -- not vendor numbers, not estimates.
"""
import pathlib
import sys
import time

import psutil

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ears.clock import VirtualClock
from ears.audio_io import WavFrameSource
from ears.stage import Ears

CLIPS_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "clips"


def transcribe_clip(ears: Ears, clock: VirtualClock, wav_path: pathlib.Path) -> str:
    """Feed one WAV through Ears (push-to-talk, since these clips never say
    the wake phrase) and return whatever text came out of a `final` message."""
    import io
    import json

    buf = io.StringIO()
    ears.out_stream = buf
    ears.reset_session()
    ears.push_to_talk()
    source = WavFrameSource(str(wav_path), clock, realtime=False)
    for frame, t_cap in source.frames():
        ears.feed(frame, t_cap)
    lines = [json.loads(l) for l in buf.getvalue().splitlines() if l.strip().startswith("{")]
    finals = [l for l in lines if l.get("type") == "final"]
    return " ".join(f["text"] for f in finals)


def peak_rss_during(fn):
    """Run fn() while polling this process's RSS; return (result, peak_rss_bytes).
    Polling (not a profiler hook) because the model load/reload happens inside
    a third-party native library call we don't control -- same approach as
    scripts/measure.py's peak-RSS tracking."""
    import threading

    proc = psutil.Process()
    peak = [proc.memory_info().rss]
    stop = threading.Event()

    def _poll():
        while not stop.is_set():
            peak[0] = max(peak[0], proc.memory_info().rss)
            time.sleep(0.01)

    t = threading.Thread(target=_poll)
    t.start()
    try:
        result = fn()
    finally:
        stop.set()
        t.join()
    peak[0] = max(peak[0], proc.memory_info().rss)
    return result, peak[0]


def main() -> None:
    clip_arg = sys.argv[1] if len(sys.argv) > 1 else None
    if clip_arg:
        wav_path = pathlib.Path(clip_arg)
    else:
        candidates = sorted(CLIPS_DIR.glob("*.wav"))
        if not candidates:
            print(f"no .wav clips found in {CLIPS_DIR}", file=sys.stderr)
            sys.exit(1)
        wav_path = candidates[0]
    print(f"using clip: {wav_path}", file=sys.stderr)

    clock = VirtualClock()
    ears = Ears(tier=0, clock=clock)

    proc = psutil.Process()
    rss_before_load = proc.memory_info().rss

    t0 = time.perf_counter()
    _, peak_rss_load = peak_rss_during(ears.start)
    load_time_s = time.perf_counter() - t0

    text_t0 = transcribe_clip(ears, clock, wav_path)

    rss_before_switch = proc.memory_info().rss
    t1 = time.perf_counter()
    _, peak_rss_switch = peak_rss_during(lambda: ears.set_tier(1))
    switch_time_s = time.perf_counter() - t1

    text_t1 = transcribe_clip(ears, clock, wav_path)

    print("\n=== MEASURED (scripts/test_tier_switch.py, this machine, this run) ===")
    print(f"clip: {wav_path.name}")
    print(f"T0 (moonshine-small) load time: {load_time_s:.3f} s")
    print(f"T0 RSS before load: {rss_before_load / 1e6:.1f} MB")
    print(f"T0 peak RSS during load: {peak_rss_load / 1e6:.1f} MB")
    print(f"T0 transcript: {text_t0!r}")
    print(f"T0->T1 (moonshine-tiny) switch time (unload+reload via set_tier): {switch_time_s:.3f} s")
    print(f"RSS right before switch: {rss_before_switch / 1e6:.1f} MB")
    print(f"peak RSS during switch: {peak_rss_switch / 1e6:.1f} MB")
    print(f"T1 transcript: {text_t1!r}")
    print(f"T0 transcribed non-empty: {bool(text_t0.strip())}")
    print(f"T1 transcribed non-empty: {bool(text_t1.strip())}")


if __name__ == "__main__":
    main()
