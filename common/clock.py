<<<<<<< HEAD
"""One machine-wide monotonic timebase; never subtract a process-local epoch."""

from time import monotonic


def now() -> float:
    """Seconds on the host monotonic clock (not calendar time)."""
    return monotonic()
=======
"""Shared clock: every stage stamps events with this, so times compare across stages and processes."""
import time


def now() -> float:
    """time.monotonic() seconds; one origin for every process on this machine."""
    return time.monotonic()
>>>>>>> 3a2adf7ca39f96b880a25893e4fd995172134c07
