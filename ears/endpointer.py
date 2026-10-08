"""Fusion endpointer: v2 "calibrated context thresholds" design from
ears/SPEC.md -- evidence bins map to a silence-threshold lookup table instead
of one fixed timer. Smart Turn's p_done is wired as an input with a neutral
default (NEUTRAL_P_DONE) so Phase 5 can drop the real model in without
touching this file. O6: per-speaker adaptive pause cap. Pure logic, no
threads, so it is unit-testable (tests/test_ears_contract.py) -- stage.py
owns the actual timer and re-arms it on new evidence.
"""
import statistics

from ears.config import (
    ADAPTIVE_CAP_MULTIPLIER,
    NEUTRAL_P_DONE,
    SILENCE_THRESHOLDS_MS,
)
from ears.normalize import ends_with_dangling_word, looks_sentence_complete


FIXED_MODE_MS = {"fixed_800": 800.0, "fixed_400": 400.0}


class Endpointer:
    def __init__(self, mode: str = "fusion"):
        """`mode="fusion"` is the real calibrated-threshold design (default,
        what ships). `mode="fixed_800"`/`"fixed_400"` are the spec's own
        ablation baselines (SPEC.md "Ears ablation rows" A/B) -- a silence
        timer with no evidence bins and no speculative tentative_final, for
        `scripts/ablation.py` to compare against."""
        if mode not in ("fusion", *FIXED_MODE_MS):
            raise ValueError(f"unknown endpointer mode: {mode!r}")
        self.mode = mode
        self._mid_sentence_pauses_s: list[float] = []

    def reset_session(self) -> None:
        """Called on a fresh wake word -- a new speaker, start the adaptive
        cap over again (O6)."""
        self._mid_sentence_pauses_s.clear()

    def record_mid_sentence_pause(self, duration_s: float) -> None:
        """Feed O6's running median: a pause that speech resumed after (so it
        was not the end of the turn)."""
        self._mid_sentence_pauses_s.append(duration_s)

    def adaptive_cap_ms(self) -> float:
        lo = SILENCE_THRESHOLDS_MS["low_or_dangling_cap_min_ms"]
        hi = SILENCE_THRESHOLDS_MS["low_or_dangling_cap_max_ms"]
        if not self._mid_sentence_pauses_s:
            return hi  # no history yet: be patient, not trigger-happy
        median_s = statistics.median(self._mid_sentence_pauses_s)
        cap_ms = median_s * 1000 * ADAPTIVE_CAP_MULTIPLIER
        return max(lo, min(hi, cap_ms))

    def evidence_bin(self, text: str, p_done: float = NEUTRAL_P_DONE) -> str:
        dangling = ends_with_dangling_word(text)
        if p_done >= 0.7 and not dangling:
            return "confident_done"
        if 0.4 <= p_done < 0.7 and not dangling:
            return "mid"
        return "low_or_dangling"

    def threshold_ms(self, text: str, p_done: float = NEUTRAL_P_DONE) -> float:
        """How long to wait, from the first silent frame, before firing
        `final` -- the calibrated-context-threshold lookup, v1 starting
        values (replaced by Phase-4 measurements)."""
        if self.mode in FIXED_MODE_MS:
            return FIXED_MODE_MS[self.mode]
        bin_ = self.evidence_bin(text, p_done)
        if bin_ == "confident_done":
            return SILENCE_THRESHOLDS_MS["confident_done"]
        if bin_ == "mid":
            return SILENCE_THRESHOLDS_MS["mid"]
        return self.adaptive_cap_ms()

    def should_send_tentative_final(self, text: str, p_done: float = NEUTRAL_P_DONE) -> bool:
        """SPEC.md: "At p >= 0.6 also send tentative_final earlier." Fixed-
        timer ablation modes never speculate -- that's the point of the
        comparison."""
        if self.mode in FIXED_MODE_MS:
            return False
        return p_done >= 0.6 and looks_sentence_complete(text)
