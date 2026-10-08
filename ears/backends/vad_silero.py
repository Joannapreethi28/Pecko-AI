"""Silero VAD backend (picked directly from ears/SPEC.md's option table over
TEN VAD -- TEN needs a git+https install and we had no time for the VAD
bake-off under the 2-hour deadline. Documented as picked, not
bake-off-verified.) O3: onnx=True keeps this on an ONNX Runtime session
instead of torch, so idle-CPU behaviour matches the rest of the pipeline.
"""
import numpy as np
import torch

from silero_vad import VADIterator, load_silero_vad

SAMPLE_RATE = 16000


class SileroVAD:
    def __init__(self, threshold: float = 0.5, min_silence_ms: int = 200):
        self._model = load_silero_vad(onnx=True)
        self._threshold = threshold
        self._min_silence_ms = min_silence_ms
        self._iterator = self._make_iterator()

    def _make_iterator(self) -> VADIterator:
        return VADIterator(
            self._model,
            threshold=self._threshold,
            sampling_rate=SAMPLE_RATE,
            min_silence_duration_ms=self._min_silence_ms,
        )

    def set_threshold(self, threshold: float) -> None:
        """O9: raise to 0.8 while Voice is playing (echo-safe barge-in)."""
        self._threshold = threshold
        self._iterator = self._make_iterator()

    def process(self, frame: np.ndarray) -> dict | None:
        """Returns {'start': sample} or {'end': sample} on a transition,
        None on every other frame (most frames)."""
        x = torch.from_numpy(frame)
        return self._iterator(x, return_seconds=False)

    def reset(self) -> None:
        self._iterator.reset_states()
