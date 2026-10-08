"""Low-latency player: one always-open output stream fed from a preallocated ring buffer.

The audio callback only copies samples and puts small tuples on an event queue; it never logs,
never allocates big buffers and holds the lock only for the copy. A consumer thread blocks on
`events.get()` (event-driven, no polling) and turns them into log lines.

Events (tuples): ("first_audio", turn, t_dac) · ("gap", turn, t_start, dur_s) ·
                 ("drained", turn, t) · ("stopped", turn, t_req, t_done)
"""
import queue
import threading
import time

import numpy as np
import sounddevice as sd

from .engine import OUT_SR

BLOCK = 512                 # ~23 ms at 22.05 kHz
CAPACITY_S = 60             # one reply never exceeds this; 60 s float32 = 5.3 MB, allocated once
SILENT = 0.01


class Player:
    def __init__(self, device=None):
        self.cap = int(CAPACITY_S * OUT_SR)
        self.ring = np.zeros(self.cap, dtype=np.float32)
        self.r = self.w = self.count = 0
        self.lock = threading.Lock()
        self.events = queue.SimpleQueue()
        self.turn = None
        self.ended = False          # no more PCM will be written for this turn
        self.active = False         # first sample played, not yet drained/stopped
        self.got_first = False
        self.in_gap = False
        self.gap_t0 = 0.0
        self.stop_req = None
        self.overflow = 0
        self.stream = sd.OutputStream(samplerate=OUT_SR, channels=1, dtype="float32", blocksize=BLOCK,
                                      latency="low", device=device, callback=self._cb)
        self.out_latency = 0.0

    def start(self):
        self.stream.start()
        self.out_latency = float(self.stream.latency)

    def close(self):
        self.stream.stop()
        self.stream.close()

    # ---- producer side (synth worker / stage) -------------------------------------
    def new_turn(self, turn):
        with self.lock:
            self.r = self.w = self.count = 0
            self.turn, self.ended = turn, False
            self.active = self.got_first = self.in_gap = False
            self.stop_req = None

    def write(self, x: np.ndarray) -> int:
        with self.lock:
            n = min(len(x), self.cap - self.count)
            if n < len(x):
                self.overflow += len(x) - n
            first = min(n, self.cap - self.w)
            self.ring[self.w:self.w + first] = x[:first]
            if n > first:
                self.ring[:n - first] = x[first:n]
            self.w = (self.w + n) % self.cap
            self.count += n
            return n

    def end_turn(self):
        with self.lock:
            self.ended = True
            if self.count == 0 and self.active:   # already played everything
                self.active = False
                self.events.put(("drained", self.turn, time.monotonic()))

    def stop_now(self):
        """Barge-in / cancel: the next callback fades out the current block and drops the rest."""
        with self.lock:
            if self.stop_req is None:
                self.stop_req = time.monotonic()
            self.ended = True

    def buffered_ms(self) -> float:
        return self.count * 1000.0 / OUT_SR

    def is_playing(self) -> bool:
        return self.active or self.count > 0

    # ---- audio thread ----------------------------------------------------------------
    def _read(self, out, frames) -> int:
        n = min(frames, self.count)
        first = min(n, self.cap - self.r)
        out[:first] = self.ring[self.r:self.r + first]
        if n > first:
            out[first:n] = self.ring[:n - first]
        self.r = (self.r + n) % self.cap
        self.count -= n
        return n

    def _cb(self, outdata, frames, time_info, status):
        out = outdata[:, 0]
        now = time.monotonic()
        with self.lock:
            n = self._read(out, frames)
            out[n:] = 0.0
            if self.stop_req is not None:  # barge-in: fade this block to zero, drop everything queued
                if n:
                    out[:n] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
                self.r = self.w = self.count = 0
                self.active = self.in_gap = False
                self.events.put(("stopped", self.turn, self.stop_req, now))
                self.stop_req = None
                return
            if n and not self.got_first:
                nz = np.flatnonzero(np.abs(out[:n]) > SILENT)
                if len(nz):
                    dac, cur = time_info.outputBufferDacTime, time_info.currentTime
                    ahead = (dac - cur) if (dac > 0 and cur > 0) else self.out_latency
                    self.got_first = self.active = True
                    self.events.put(("first_audio", self.turn, now + ahead + nz[0] / OUT_SR))
            if not self.active:
                return
            if n and self.in_gap:  # audio resumed after running dry
                self.in_gap = False
                self.events.put(("gap", self.turn, self.gap_t0, now - self.gap_t0))
            if n < frames:
                if self.ended and self.count == 0:
                    self.active = False
                    self.events.put(("drained", self.turn, now + self.out_latency))
                elif not self.in_gap:
                    self.in_gap = True  # ran dry mid-reply: audible gap starts
                    self.gap_t0 = now + n / OUT_SR


class NullPlayer:
    """Same interface as Player, no sound device: for tests, benchmarks and WAV-in runs.
    It "plays" instantly: first_audio = time of the first non-silent write + a simulated device delay."""

    def __init__(self, device=None, out_latency=0.0):
        self.events = queue.SimpleQueue()
        self.out_latency = out_latency
        self.lock = threading.Lock()
        self.turn, self.ended, self.got_first, self.active = None, False, False, False
        self.written = 0

    def start(self):
        pass

    def close(self):
        pass

    def new_turn(self, turn):
        with self.lock:
            self.turn, self.ended, self.got_first, self.active, self.written = turn, False, False, False, 0

    def write(self, x):
        with self.lock:
            self.written += len(x)
            if not self.got_first and len(x) and np.any(np.abs(x) > SILENT):
                self.got_first = self.active = True
                self.events.put(("first_audio", self.turn, time.monotonic() + self.out_latency))
            return len(x)

    def end_turn(self):
        with self.lock:
            self.ended = True
            if self.active:
                self.active = False
                self.events.put(("drained", self.turn, time.monotonic()))

    def stop_now(self):
        with self.lock:
            self.ended, self.active = True, False
            t = time.monotonic()
            self.events.put(("stopped", self.turn, t, t))

    def buffered_ms(self):
        return 0.0

    def is_playing(self):
        return self.active
