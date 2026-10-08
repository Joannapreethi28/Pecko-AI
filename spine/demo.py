"""Integrated synthetic demonstration of telemetry, safe tier changes and review.

No speech, inference, hardware readings or energy measurements are produced.
"""

import argparse
from pathlib import Path
from threading import Event, Thread

from common.clock import now
from spine.bus import EventBus
from spine.experiment import ExperimentRunner, MockDriver
from spine.mock import MockStage
from spine.resources import Snapshot
from spine.telemetry import PressurePolicy, Telemetry


class DemoVoice(MockStage):
    def __init__(self, emit, log):
        super().__init__("voice", emit, log)
        self.shutdown = Event()
        self.worker = None

    def _released(self, msg, blocks):
        if not blocks:
            return
        self.log.emit("voice", "mock_release", msg["turn"], gen=msg["gen"], synthetic=True, audio=False)
        delay = (1.2, 2.6, 0.4)[msg["turn"]]
        def complete():
            if not self.shutdown.wait(delay):
                self.emit("voice", {"type": "playback_state", "turn": msg["turn"], "playing": False, "t": now()})
                self.on_complete(msg["turn"], msg["gen"], success=True)
        self.worker = Thread(target=complete, name="synthetic-turn")
        self.worker.start()

    def stop(self):
        self.shutdown.set()
        if self.worker:
            self.worker.join(timeout=2)


def factory(log):
    emit = lambda source, msg: bus.publish(source, msg)
    stages = {name: MockStage(name, emit, log) for name in ("ears", "brain")}
    stages["voice"] = DemoVoice(emit, log)
    bus = EventBus(stages, log)
    stages["brain"].prepare = bus.prepared
    stages["brain"].validate = bus.validate_final
    return bus


def monitor_factory(bus, log):
    start = now()
    usage = psi = 0
    last = start
    def read():
        nonlocal usage, psi, last
        t = now()
        elapsed = t - last
        usage += int(elapsed * 0.8 * 1e6)
        psi += int(elapsed * (0.6 if bus.turns.turn == 0 else 0.01) * 1e6)
        last = t
        return Snapshot("synthetic-cgroup", t, usage, "200000 100000", "0-1",
                        300_000_000, 400_000_000, 2_000_000_000, False, "0", psi, 0, ())
    policy = PressurePolicy({
        "calibrated": True, "synthetic": True, "psi_fraction": 0.2, "memory_ratio": 0.85,
        "tiers": [{"tier": t, "min_cpu": 0, "min_memory_bytes": 0} for t in range(4)],
        "memory_guard_bytes": 100_000_000,
        "transition_peak_bytes": {f"{old}->{new}": 600_000_000 for old in range(4) for new in range(4)},
    })
    return Telemetry(bus, log, read_snapshot=read, policy=policy)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    plan = {"run_id": "integrated-synthetic-demo", "platform": "synthetic",
            "configuration": "mock-stages-and-simulated-pressure", "synthetic": True,
            "cases": [{"case_id": label, "text": text, "timeout_s": 8}
                      for label, text in (("pressure", "Show the constrained turn"),
                                          ("recovery", "Show recovery after the pressure falls"),
                                          ("steady", "Finish the demonstration"))]}
    result = ExperimentRunner(plan, args.output, factory, MockDriver(), monitor_factory).run()
    print(f"Synthetic cases completed: {result['completed_cases']}/{result['expected_cases']}")
    print(f"Dashboard: {(args.output / 'dashboard.html').resolve()}")
    if result["aborted"]:
        raise SystemExit(result["aborted"])


if __name__ == "__main__":
    main()
