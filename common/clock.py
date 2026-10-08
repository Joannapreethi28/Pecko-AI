"""Shared clock: every stage stamps events with this, so times compare across stages and processes."""
import time


def now() -> float:
    """time.monotonic() seconds; one origin for every process on this machine."""
    return time.monotonic()
