"""Portable, bounded real-time WAV ingress for the same path as microphone PCM."""

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
from threading import Event, Thread
import wave

from common.clock import now


@dataclass(frozen=True)
class AudioFrame:
    turn: int
    pcm: bytes
    sample_rate: int
    offset_frames: int
    t_capture: float  # Timestamp of first sample, not callback delivery time.


def inspect_wav(path: Path, eos_offset_s: float) -> dict:
    if isinstance(eos_offset_s, bool) or not isinstance(eos_offset_s, (int, float)) or not math.isfinite(eos_offset_s):
        raise ValueError("Labelled EOS must be finite seconds")
    with wave.open(str(path), "rb") as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (1, 2, 16000, "NONE"):
            raise ValueError("WAV ingress requires mono 16 kHz signed 16-bit PCM")
        frames = stream.getnframes()
        duration = frames / 16000
        if not frames or not 0 <= eos_offset_s <= duration:
            raise ValueError("Labelled EOS must lie inside a nonempty WAV")
        pcm_digest = hashlib.sha256()
        payload_bytes = 0
        for pcm in iter(lambda: stream.readframes(32768), b""):
            payload_bytes += len(pcm)
            pcm_digest.update(pcm)
        if payload_bytes != frames * 2:
            raise ValueError("Truncated WAV payload")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(65536), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest(),
            "frames": frames, "duration_s": duration, "sample_rate": 16000,
            "eos_offset_s": eos_offset_s, "pcm_sha256": pcm_digest.hexdigest()}


class WavReplayer:
    def __init__(self, feed_audio, end_audio, fail, *, frame_ms=20, max_late_s=0.25):
        if type(frame_ms) is not int or not 1 <= frame_ms <= 1000:
            raise ValueError("frame_ms must be an integer in 1..1000")
        if not math.isfinite(max_late_s) or max_late_s <= 0:
            raise ValueError("max_late_s must be positive and finite")
        self.feed_audio, self.end_audio, self.fail = feed_audio, end_audio, fail
        self.frame_samples = frame_ms * 16
        self.max_late_s = max_late_s
        self.shutdown = Event()
        self.worker = None
        self.stats = {"frames_delivered": 0, "samples_delivered": 0, "max_late_s": 0.0,
                      "completed": False, "cancelled": False, "error": None}

    def start(self, path: Path, turn: int, metadata: dict, *, capture_start=None) -> float:
        if self.worker is not None:
            raise RuntimeError("A replayer handles one clip; create a new instance")
        if type(turn) is not int or turn < 0:
            raise ValueError("turn must be a nonnegative integer")
        start = now() if capture_start is None else capture_start
        if not math.isfinite(start) or start < 0:
            raise ValueError("Capture start must be nonnegative and finite")
        def replay():
            try:
                with wave.open(str(path), "rb") as source:
                    if (source.getframerate(), source.getnchannels(), source.getsampwidth(), source.getnframes()) != (
                            16000, 1, 2, metadata["frames"]):
                        raise ValueError("WAV changed after inspection")
                    offset = 0
                    digest = hashlib.sha256()
                    while offset < metadata["frames"]:
                        pcm = source.readframes(self.frame_samples)
                        samples = len(pcm) // 2
                        if not samples or len(pcm) % 2:
                            raise ValueError("Truncated PCM payload")
                        # Mic callbacks receive a frame after its final sample.
                        due = start + (offset + samples) / 16000
                        if self.shutdown.wait(max(0, due - now())):
                            self.stats["cancelled"] = True
                            return
                        late = max(0, now() - due)
                        self.stats["max_late_s"] = max(self.stats["max_late_s"], late)
                        if late > self.max_late_s:
                            raise TimeoutError("Audio ingress fell behind real-time budget")
                        self.feed_audio(AudioFrame(turn, pcm, 16000, offset, start + offset / 16000))
                        digest.update(pcm)
                        offset += samples
                        self.stats["frames_delivered"] += 1
                        self.stats["samples_delivered"] = offset
                if digest.hexdigest() != metadata["pcm_sha256"]:
                    raise ValueError("WAV PCM changed after inspection")
                self.end_audio(turn)
                self.stats["completed"] = True
            except Exception as exc:
                self.stats["error"] = repr(exc)
                self.fail(str(exc))
        self.worker = Thread(target=replay, name="pecko-wav-input")
        self.worker.start()
        return start + metadata["eos_offset_s"]

    def stop(self):
        self.shutdown.set()
        if self.worker:
            self.worker.join(timeout=2)
            if self.worker.is_alive():
                raise RuntimeError("WAV ingress worker did not stop")
