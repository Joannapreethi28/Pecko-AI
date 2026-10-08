"""Periodic pressure telemetry, optional calibrated control, and run accounting."""

from dataclasses import asdict
import math
from threading import Event, Lock, Thread

from common.clock import now
from spine.ladder import PressureSample, TierLadder
from spine.resources import usage_delta, effective_cpu_limit


class PressurePolicy:
    """Explicitly configured thresholds and transition peaks; no invented profile."""
    def __init__(self, config: dict):
        self.config = config
        for field in ("psi_fraction", "memory_ratio"):
            value = config.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 1:
                raise ValueError(f"{field} must be in (0, 1]")
        if type(config.get("calibrated")) is not bool:
            raise ValueError("Policy must declare calibrated true/false")
        for row in config.get("tiers", []):
            if type(row.get("tier")) is not int or not 0 <= row["tier"] <= 3:
                raise ValueError("Invalid profile tier")
            for field in ("min_cpu", "min_memory_bytes"):
                if not isinstance(row.get(field), (int, float)) or row[field] < 0 or not math.isfinite(row[field]):
                    raise ValueError(f"Invalid {field}")
        self.ladder = TierLadder()
        self.last_request = None
        self.revision = 0

    def risk(self, snapshot, delta):
        psi = None if delta is None else delta["cpu_psi_some_fraction"]
        memory = None
        if snapshot.memory_current is not None and snapshot.memory_max:
            memory = snapshot.memory_current / snapshot.memory_max
        values = [(psi, self.config["psi_fraction"]), (memory, self.config["memory_ratio"])]
        if any(value is not None and value >= limit for value, limit in values):
            return True
        return False if all(value is not None for value, _ in values) else None

    def decide(self, snapshot, delta, bus):
        if bus.tier_revision != self.revision:
            self.ladder.acknowledge(bus.tier, snapshot.t)
            self.revision = bus.tier_revision
            self.last_request = None
        cpu = effective_cpu_limit(snapshot)
        eligible = [r["tier"] for r in self.config.get("tiers", [])
                    if cpu is not None and snapshot.memory_max is not None
                    and cpu >= r["min_cpu"] and snapshot.memory_max >= r["min_memory_bytes"]]
        floor = min(eligible) if eligible else 3
        requested = self.ladder.observe(PressureSample(snapshot.t, snapshot.regime,
                                                       self.risk(snapshot, delta), floor))
        if not self.config["calibrated"] or not eligible:
            return None
        # Only configurations present in the measured profile can be requested.
        supported = sorted(t for t in eligible if t >= requested)
        if not supported:
            return None
        target = supported[0]
        if target != self.last_request:
            self.last_request = target
            return target
        return None

    def transition_allowed(self, old, new, snapshot):
        if (not self.config["calibrated"] or snapshot is None
                or snapshot.memory_max is None or snapshot.memory_current is None):
            return False
        peak = self.config.get("transition_peak_bytes", {}).get(f"{old}->{new}")
        guard = self.config.get("memory_guard_bytes", 0)
        if (type(peak) is not int or peak < 0 or type(guard) is not int or guard < 0):
            return False
        cpu = effective_cpu_limit(snapshot)
        supported = any(r["tier"] == new and cpu is not None and cpu >= r["min_cpu"]
                        and snapshot.memory_max >= r["min_memory_bytes"] for r in self.config.get("tiers", []))
        return supported and max(snapshot.memory_current or 0, peak) + guard <= snapshot.memory_max


class Telemetry:
    def __init__(self, bus, log, read_snapshot=None, energy=None, policy=None, interval_s=0.2):
        if not math.isfinite(interval_s) or interval_s <= 0:
            raise ValueError("interval_s must be positive and finite")
        self.bus, self.log = bus, log
        self.read_snapshot, self.energy, self.policy = read_snapshot, energy, policy
        self.interval_s = interval_s
        self._stop = Event()
        self._lock = Lock()
        self._thread = None
        self.first = self.last = None
        self.samples = 0
        self.started_t = self.stopped_t = None
        self.error = None
        self.regime_changes = 0
        self.counter_reset = False
        self.cpu_invalid_events = 0
        self.turn_starts = {}
        self.turns = {}

    def _sample(self, control=True):
        with self._lock:
            current = self.read_snapshot() if self.read_snapshot else None
            energy = self.energy.sample() if self.energy else {"available": False, "gross_j": None}
            delta = None
            if current is not None:
                if self.last is not None:
                    delta = usage_delta(self.last, current)
                    self.regime_changes += int(delta["regime_changed"])
                    self.counter_reset |= delta["cpu_s"] is None
                    self.cpu_invalid_events += int(delta["cpu_s"] is None)
                self.first = self.first or current
                self.last = current
            self.samples += 1
            fields = {"snapshot": asdict(current) if current else None, "delta": delta, "energy": energy}
            if self.policy is not None and self.policy.config.get("synthetic") is True:
                fields["synthetic"] = True
            self.log.emit("spine", "pressure", **fields)
            if control and current is not None and self.policy is not None:
                target = self.policy.decide(current, delta, self.bus)
                if target is not None:
                    self.log.emit("spine", "tier_request", tier=target)
                    self.bus.request_tier(target)
            return current, energy.get("gross_j")

    def _guard(self, old, new):
        # Re-read at the actual safe boundary: an old sample cannot authorize
        # loading models after the memory cap has tightened.
        current = self.read_snapshot() if self.read_snapshot else None
        return self.policy.transition_allowed(old, new, current)

    def start(self):
        if self._thread is not None:
            raise RuntimeError("Telemetry already started")
        self.started_t = now()
        if self.policy is not None:
            self.bus.tier_guard = self._guard
        self._sample()
        self._thread = Thread(target=self._run, name="pecko-pressure", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.wait(self.interval_s):
            try:
                self._sample()
            except Exception as exc:
                self.error = repr(exc)
                self.bus.fail("spine", f"Telemetry failed: {exc}")
                return

    def mark_start(self, turn):
        current, energy = self._sample(control=False)
        self.turn_starts[turn] = (current, energy, self.cpu_invalid_events, self.regime_changes)

    def mark_end(self, turn):
        current, joules = self._sample(control=False)
        before, start_j, invalid_before, regimes_before = self.turn_starts[turn]
        result = usage_delta(before, current) if before is not None and current is not None else {}
        if self.cpu_invalid_events != invalid_before:
            result.update(cpu_s=None, mean_cores=None)
        if self.regime_changes != regimes_before:
            result.update(cpu_psi_some_fraction=None, regime_changed=True)
        result["gross_package_j"] = None if joules is None or start_j is None else joules - start_j
        self.turns[turn] = result
        self.log.emit("spine", "turn_resources", turn, **result)
        self.turn_starts.pop(turn)

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                raise RuntimeError("Telemetry sampler failed to stop")
        if self.started_t is not None:
            self._sample(control=False)
        self.stopped_t = now()

    def summary(self):
        accounting = usage_delta(self.first, self.last) if self.first and self.last and self.last.t > self.first.t else {}
        if self.counter_reset:
            accounting.update(cpu_s=None, mean_cores=None)
        if self.regime_changes:
            accounting.update(cpu_psi_some_fraction=None, regime_changed=True)
        return {"samples": self.samples, "accounting": accounting,
                "regime_changes": self.regime_changes, "counter_reset_or_missing": self.counter_reset,
                "energy": self.energy.summary() if self.energy else {"available": False, "gross_j": None},
                "turns": self.turns, "error": self.error,
                "interval_s": self.interval_s,
                "instrumentation_cost": "Sampler runs inside the application process/cgroup; its cost is included.",
                "memory_peak_scope": "cgroup lifetime, including model warm-up",
                "window": "after stage warm-up through pre-shutdown sampling"}
