"""Deterministic pressure hysteresis. Threshold calibration belongs to profiling.

This is the required reactive comparator, not the advanced latency controller.
Unknown evidence never counts as a healthy sample. Returned tier is a request;
Spine applies it at an explicit safe boundary, after transition-memory checks.
"""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class PressureSample:
    t: float
    regime: tuple
    risk: bool | None
    minimum_tier: int = 0


class TierLadder:
    def __init__(self, tier: int = 0, down_readings: int = 3,
                 up_readings: int = 10, dwell_s: float = 2):
        if type(tier) is not int or not 0 <= tier <= 3:
            raise ValueError("Tier must be 0..3")
        if down_readings < 1 or up_readings < 1 or not math.isfinite(dwell_s) or dwell_s < 0:
            raise ValueError("Invalid hysteresis settings")
        self.tier = tier
        self.down_readings, self.up_readings, self.dwell_s = down_readings, up_readings, dwell_s
        self.regime = None
        self.last_t = None
        self.last_switch_t = None
        self.bad = self.good = 0

    def observe(self, sample: PressureSample) -> int:
        if not math.isfinite(sample.t) or (self.last_t is not None and sample.t <= self.last_t):
            raise ValueError("Pressure timestamps must increase")
        if type(sample.minimum_tier) is not int or not 0 <= sample.minimum_tier <= 3:
            raise ValueError("minimum_tier must be 0..3")
        if sample.risk is not None and type(sample.risk) is not bool:
            raise ValueError("risk must be bool or None")
        self.last_t = sample.t
        if sample.regime != self.regime:
            self.regime = sample.regime
            self.bad = self.good = 0
            self.last_switch_t = sample.t
        if self.tier < sample.minimum_tier:
            self.tier = sample.minimum_tier
            self.bad = self.good = 0
            self.last_switch_t = sample.t
            return self.tier
        if sample.risk is None:
            self.bad = self.good = 0
            return self.tier
        self.bad = self.bad + 1 if sample.risk else 0
        self.good = 0 if sample.risk else self.good + 1
        if self.bad >= self.down_readings and self.tier < 3:
            self.tier += 1
        elif (self.good >= self.up_readings and self.tier > sample.minimum_tier
              and self.last_switch_t is not None
              and sample.t - self.last_switch_t >= self.dwell_s):
            self.tier -= 1
        else:
            return self.tier
        self.bad = self.good = 0
        self.last_switch_t = sample.t
        return self.tier

    def acknowledge(self, applied_tier: int, t: float) -> None:
        """Synchronize after the supervisor applies/rejects a requested transition."""
        if type(applied_tier) is not int or not 0 <= applied_tier <= 3 or not math.isfinite(t):
            raise ValueError("Invalid applied tier/time")
        if self.last_t is not None and t < self.last_t:
            raise ValueError("Acknowledgement predates latest sample")
        self.tier = applied_tier
        self.bad = self.good = 0
        self.last_switch_t = t
