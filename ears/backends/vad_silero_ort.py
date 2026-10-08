"""Silero VAD on plain ONNX Runtime + numpy -- no torch.

Same model file (silero_vad.onnx from the silero_vad package) and the same
decision logic as silero_vad's OnnxWrapper + VADIterator, re-written with
numpy. Why: `import torch` alone costs ~128 MiB of anonymous RAM inside the
2 GB cap (measured with the cgroup's memory.stat, see spine commit notes),
and torch is used for nothing else in Pecko. Event-for-event equality with
`vad_silero.SileroVAD` is checked by tests/test_vad_silero_ort.py.

Interface matches `vad_silero.SileroVAD`: process(frame) -> {'start': n} |
{'end': n} | None, set_threshold(), reset(), and `_iterator.current_sample`
(Ears' t_eos uses it).
"""
import importlib.util
from pathlib import Path

import numpy as np
import onnxruntime as ort

SAMPLE_RATE = 16000
WINDOW = 512          # samples per call at 16 kHz (32 ms)
CONTEXT = 64          # samples of the previous window prepended (Silero v5)


def _model_path() -> str:
    # find_spec does NOT execute silero_vad/__init__.py (which imports torch)
    spec = importlib.util.find_spec("silero_vad")
    if spec is None or not spec.submodule_search_locations:
        raise FileNotFoundError("silero_vad package not installed (needed for its silero_vad.onnx)")
    return str(Path(list(spec.submodule_search_locations)[0]) / "data" / "silero_vad.onnx")


class _Model:
    """numpy port of silero_vad.utils_vad.OnnxWrapper for 16 kHz, batch 1."""

    def __init__(self, path: str):
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        so.add_session_config_entry("session.inter_op.allow_spinning", "0")
        self.session = ort.InferenceSession(path, sess_options=so, providers=["CPUExecutionProvider"])
        self._sr = np.array(SAMPLE_RATE, dtype=np.int64)
        self.reset_states()

    def reset_states(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT), dtype=np.float32)

    def __call__(self, x: np.ndarray) -> float:
        x = np.asarray(x, dtype=np.float32).reshape(1, -1)
        if x.shape[1] != WINDOW:
            raise ValueError(f"Provided number of samples is {x.shape[1]} (Supported: {WINDOW} at 16 kHz)")
        inp = np.concatenate([self._context, x], axis=1)
        out, self._state = self.session.run(None, {"input": inp, "state": self._state, "sr": self._sr})
        self._context = inp[:, -CONTEXT:]
        return float(np.asarray(out).reshape(-1)[0])


class _Iterator:
    """numpy port of silero_vad.utils_vad.VADIterator (sample units, 16 kHz)."""

    def __init__(self, model: _Model, threshold: float, min_silence_duration_ms: int, speech_pad_ms: int = 30):
        self.model = model
        self.threshold = threshold
        self.min_silence_samples = SAMPLE_RATE * min_silence_duration_ms / 1000
        self.speech_pad_samples = SAMPLE_RATE * speech_pad_ms / 1000
        self.reset_states()

    def reset_states(self) -> None:
        self.model.reset_states()
        self.triggered = False
        self.temp_end = 0
        self.current_sample = 0

    def __call__(self, x: np.ndarray) -> dict | None:
        n = len(x)
        self.current_sample += n
        p = self.model(x)
        if p >= self.threshold and self.temp_end:
            self.temp_end = 0
        if p >= self.threshold and not self.triggered:
            self.triggered = True
            return {"start": int(max(0, self.current_sample - self.speech_pad_samples - n))}
        if p < self.threshold - 0.15 and self.triggered:
            if not self.temp_end:
                self.temp_end = self.current_sample
            if self.current_sample - self.temp_end < self.min_silence_samples:
                return None
            end = self.temp_end + self.speech_pad_samples - n
            self.temp_end = 0
            self.triggered = False
            return {"end": int(end)}
        return None


class SileroVADOrt:
    def __init__(self, threshold: float = 0.5, min_silence_ms: int = 200):
        self._model = _Model(_model_path())
        self._threshold = threshold
        self._min_silence_ms = min_silence_ms
        self._iterator = self._make_iterator()

    def _make_iterator(self) -> _Iterator:
        # like the torch version: a new iterator also resets the model state
        return _Iterator(self._model, self._threshold, self._min_silence_ms)

    def set_threshold(self, threshold: float) -> None:
        """O9: raise to 0.8 while Voice is playing (echo-safe barge-in)."""
        self._threshold = threshold
        self._iterator = self._make_iterator()

    def process(self, frame: np.ndarray) -> dict | None:
        return self._iterator(frame)

    def reset(self) -> None:
        self._iterator.reset_states()
