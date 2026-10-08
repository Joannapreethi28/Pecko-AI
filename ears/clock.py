"""Ears-local clock abstraction. common/clock.py (the team's shared module)
only exposes a bare now() -> float; Ears' WAV mocks and bake-off scripts
need a swappable virtual clock for fast (non-realtime) iteration, so that
lives here instead of in common/."""
from common.clock import now as _shared_now


class Clock:
    def now(self) -> float:
        return _shared_now()


class VirtualClock(Clock):
    def __init__(self, t0: float = 0.0):
        self._t = t0

    def advance(self, dt: float) -> None:
        self._t += dt

    def now(self) -> float:
        return self._t
