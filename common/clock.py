"""Shared monotonic clock. Every stage stamps times with the same clock type
so Ears/Brain/Voice/Spine timestamps are directly comparable (docs/CONTRACT.md)."""
import time


class Clock:
    def now(self) -> float:
        return time.monotonic()


class VirtualClock(Clock):
    """Advances only when told to. Used by fast WAV mocks/bake-offs so relative
    timing math (t_endpoint - t_eos) stays correct without sleeping wall-clock time."""

    def __init__(self, t0: float = 0.0):
        self._t = t0

    def advance(self, dt: float) -> None:
        self._t += dt

    def now(self) -> float:
        return self._t
