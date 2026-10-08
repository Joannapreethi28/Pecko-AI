"""Standalone Ears mock: `python -m ears.mock <wav_path> [--mic] [--fast]
[--push-to-talk]`. stdout = pure contract JSONL (pipeable into Brain's own
mock); stderr = diagnostic log lines (common/log.py). Satisfies the
cross-role rule "each stage runs standalone with a mock" (docs/CONTRACT.md).
"""
import argparse
import sys

from common.clock import Clock, VirtualClock
from ears.audio_io import WavFrameSource, open_mic_stream
from ears.config import WAKE_PHRASE
from ears.stage import Ears


def run_wav(path: str, tier: int, realtime: bool, push_to_talk: bool) -> None:
    clock = Clock() if realtime else VirtualClock()
    ears = Ears(tier=tier, clock=clock, out_stream=sys.stdout)
    ears.start()
    if push_to_talk:
        ears.push_to_talk()
    else:
        print(f"(no --push-to-talk: say '{WAKE_PHRASE}' in the clip to arm)", file=sys.stderr)
    source = WavFrameSource(path, clock, realtime=realtime)
    for frame, t_cap in source.frames():
        ears.feed(frame, t_cap)
    ears.stop()


def run_mic(tier: int, push_to_talk: bool) -> None:
    import time

    clock = Clock()
    ears = Ears(tier=tier, clock=clock, out_stream=sys.stdout)
    ears.start()
    if push_to_talk:
        ears.push_to_talk()
    stream = open_mic_stream(ears.feed, clock)
    with stream:
        print("listening on mic, Ctrl+C to stop...", file=sys.stderr)
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
    ears.stop()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("wav", nargs="?", help="WAV file (16 kHz mono); omit with --mic")
    p.add_argument("--mic", action="store_true", help="use the live microphone instead of a WAV file")
    p.add_argument("--fast", action="store_true", help="virtual-clock pacing instead of real-time sleep")
    p.add_argument("--push-to-talk", action="store_true", help="force-arm immediately, skip the wake-phrase check")
    p.add_argument("--tier", type=int, default=0)
    args = p.parse_args()

    if args.mic:
        run_mic(args.tier, args.push_to_talk)
    else:
        if not args.wav:
            p.error("a WAV path is required unless --mic is given")
        run_wav(args.wav, args.tier, realtime=not args.fast, push_to_talk=args.push_to_talk)


if __name__ == "__main__":
    main()
