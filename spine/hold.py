"""Bounded PCM hold/release helper for Voice adapters; no audio-device I/O.

Return values are authorized PCM blocks in sequence order. Voice must still
flush its device/ring buffer on cancel/barge-in and suppress old callbacks.
"""

from threading import Lock


class HoldBuffer:
    def __init__(self, max_bytes: int = 1_048_576):
        if max_bytes < 1:
            raise ValueError("max_bytes must be positive")
        self.max_bytes = max_bytes
        self._lock = Lock()
        self.key = (-1, -1)
        self.cancelled = False
        self.committed = False
        self.pending: dict[int, bytes] = {}
        self.size = 0
        self.next_seq = 0

    def _select(self, turn: int, gen: int) -> bool:
        if any(type(n) is not int or n < 0 for n in (turn, gen)):
            raise ValueError("turn/gen must be nonnegative integers")
        key = (turn, gen)
        if key < self.key:
            return False
        if key > self.key:
            self.key = key
            self.cancelled = self.committed = False
            self.pending.clear()
            self.size = self.next_seq = 0
        return not self.cancelled

    def _drain(self) -> list[bytes]:
        released = []
        while self.committed and self.next_seq in self.pending:
            pcm = self.pending.pop(self.next_seq)
            self.size -= len(pcm)
            self.next_seq += 1
            released.append(pcm)
        return released

    def ready(self, turn: int, gen: int, seq: int, pcm: bytes) -> list[bytes]:
        if type(seq) is not int or seq < 0 or not isinstance(pcm, bytes) or not pcm:
            raise ValueError("Expected nonnegative seq and nonempty PCM bytes")
        with self._lock:
            if not self._select(turn, gen):
                return []
            if seq < self.next_seq or seq in self.pending:
                return []
            if self.size + len(pcm) > self.max_bytes:
                raise BufferError("Held PCM budget exceeded")
            self.pending[seq] = pcm
            self.size += len(pcm)
            return self._drain()

    def commit(self, turn: int, gen: int) -> list[bytes]:
        with self._lock:
            if not self._select(turn, gen):
                return []
            self.committed = True
            return self._drain()

    def cancel(self, turn: int, gen: int) -> None:
        with self._lock:
            if self._select(turn, gen):
                self.cancelled = True
                self.committed = False
                self.pending.clear()
                self.size = 0
