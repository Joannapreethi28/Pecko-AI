"""Noise floor estimation + the VAD threshold tier it drives
(ears/research/01_EARS_research_v2.md section 4: "threshold 0.5 (0.6 in
noise; 0.8 while Voice plays)"). We had the 0.5/0.8 pair wired (O9) but never
built the 0.6-in-noise tier -- this fills that gap.

Only updated while IDLE (no speech happening, VAD already says silence), so
an EWMA of frame RMS is a reasonable ambient-noise estimate without needing
a separate "is this frame speech" model. Starting threshold values, not
calibrated against a measured noisy-room recording -- said plainly, same
honesty rule as every other threshold in this codebase.
"""
import numpy as np

from ears.config import NOISE_EWMA_ALPHA, NOISE_RMS_THRESHOLD


class NoiseFloorEstimator:
    def __init__(self):
        self._floor = 0.0

    def update(self, frame: np.ndarray) -> None:
        """Call only on frames already known to be silence (VAD agrees)."""
        rms = float(np.sqrt(np.mean(np.square(frame))))
        self._floor = (1 - NOISE_EWMA_ALPHA) * self._floor + NOISE_EWMA_ALPHA * rms

    def floor_rms(self) -> float:
        return self._floor

    def is_noisy(self) -> bool:
        return self._floor > NOISE_RMS_THRESHOLD

    def reset(self) -> None:
        self._floor = 0.0
