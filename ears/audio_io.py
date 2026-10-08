"""Audio input: pre-roll ring buffer, WAV frame source (mock), mic stream.
Frames are 32 ms (FRAME_MS) of float32 mono @16 kHz, matching ears/config.py
and the clips converted by scripts/convert_clips_to_wav.py.
"""
from collections import deque

import numpy as np
import soundfile as sf

from common.clock import Clock
from ears.config import FRAME_MS, PREROLL_MS

SAMPLE_RATE = 16000
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)


class PreRollBuffer:
    """Keeps the last `ms` milliseconds of frames so ASR can see the audio
    that arrived just before VAD/KWS armed the pipeline."""

    def __init__(self, ms: int = PREROLL_MS, frame_samples: int = FRAME_SAMPLES):
        self._maxlen = max(1, ms // FRAME_MS)
        self._buf: deque = deque(maxlen=self._maxlen)
        self.frame_samples = frame_samples

    def push(self, frame: np.ndarray) -> None:
        self._buf.append(frame)

    def drain(self) -> np.ndarray:
        if not self._buf:
            return np.zeros(0, dtype=np.float32)
        out = np.concatenate(list(self._buf))
        self._buf.clear()
        return out


class WavFrameSource:
    """Feeds a WAV file as 32 ms frames, either at real-time pace (true
    latency behaviour) or as fast as possible against a VirtualClock (quick
    iteration / bake-off runs). Matches the contract rule "Ears runs
    standalone with a mock... WAV at real-time speed" for --realtime mode.
    """

    def __init__(self, path: str, clock: Clock, realtime: bool = True):
        data, sr = sf.read(path, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != SAMPLE_RATE:
            raise ValueError(f"{path}: expected {SAMPLE_RATE} Hz, got {sr}. Run scripts/convert_clips_to_wav.py first.")
        self._data = data
        self.clock = clock
        self.realtime = realtime

    def frames(self):
        """Yield (frame: np.ndarray[float32], t_capture: float)."""
        import time as _time

        n = len(self._data)
        pos = 0
        while pos < n:
            end = min(pos + FRAME_SAMPLES, n)
            frame = self._data[pos:end]
            if len(frame) < FRAME_SAMPLES:
                frame = np.pad(frame, (0, FRAME_SAMPLES - len(frame)))
            if self.realtime:
                _time.sleep(FRAME_MS / 1000)
            else:
                self.clock.advance(FRAME_MS / 1000)
            yield frame, self.clock.now()
            pos = end


def open_mic_stream(callback, clock: Clock):
    """Open a live mic stream; `callback(frame, t_capture)` runs on the audio
    thread and must only copy + stamp (O5) -- no model work here.
    """
    import sounddevice as sd

    def _sd_callback(indata, frames, time_info, status):
        frame = indata[:, 0].copy().astype(np.float32)
        callback(frame, clock.now())

    return sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        blocksize=FRAME_SAMPLES,
        dtype="float32",
        latency="low",
        callback=_sd_callback,
    )
