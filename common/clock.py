"""One machine-wide monotonic timebase; never subtract a process-local epoch."""

from time import monotonic


def now() -> float:
    """Seconds on the host monotonic clock (not calendar time)."""
    return monotonic()
