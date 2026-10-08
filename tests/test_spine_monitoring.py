from dataclasses import replace
import io
import json
from pathlib import Path
from queue import Empty
import tempfile
import unittest

from common.log import EventLog
from spine.dashboard import DashboardState, EventTail
from spine.energy import RaplMeter
from spine.experiment import ExperimentRunner, MockDriver, mock_factory
from spine.resources import Snapshot
from spine.telemetry import PressurePolicy, Telemetry


def snapshot(t=1, usage=1000000, psi=100000):
    return Snapshot("fixture", t, usage, "200000 100000", "0-1", 100, 200, 1000,
                    False, "0", psi, 0, ())


def profile():
    return {"calibrated": True, "psi_fraction": 0.2, "memory_ratio": 0.8,
            "memory_guard_bytes": 100,
            "tiers": [{"tier": i, "min_cpu": 0, "min_memory_bytes": 100} for i in range(4)],
            "transition_peak_bytes": {"0->1": 700, "1->0": 800}}


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)

    def domain(self, folder, name, energy, maximum=1000000):
        path = self.root / folder.replace(":", "_")
        path.mkdir(parents=True)
        for file, text in {"name": name, "energy_uj": str(energy),
                           "max_energy_range_uj": str(maximum)}.items():
            (path / file).write_text(text)
        return path

    def test_energy_counts_packages_without_core_double_counting(self):
        package = self.domain("intel-rapl:0", "package-0", 900000)
        self.domain("intel-rapl:0/intel-rapl:0:0", "core", 700000)
        meter = RaplMeter(self.root)
        meter.sample(t=1)
        (package / "energy_uj").write_text("100000")
        result = meter.sample(t=1.2)
        self.assertAlmostEqual(result["gross_j"], 0.2)
        self.assertEqual(result["domains"], ["package-0"])

    def test_lost_counter_invalidates_complete_run_energy(self):
        package = self.domain("intel-rapl:0", "package-0", 100)
        meter = RaplMeter(self.root)
        meter.sample(t=1)
        (package / "energy_uj").unlink()
        self.assertIsNone(meter.sample(t=1.2)["gross_j"])
        (package / "energy_uj").write_text("200")
        self.assertIsNone(meter.sample(t=1.4)["gross_j"])

    def test_long_sampling_gap_does_not_claim_wrap_correctness(self):
        self.domain("intel-rapl:0", "package-0", 100)
        meter = RaplMeter(self.root)
        meter.sample(t=1)
        self.assertFalse(meter.sample(t=5)["available"])

    def test_missing_energy_is_not_zero(self):
        self.assertIsNone(RaplMeter(self.root).sample()["gross_j"])

    def test_transition_guard_uses_current_cap_and_unknown_memory_is_denied(self):
        policy = PressurePolicy(profile())
        self.assertTrue(policy.transition_allowed(0, 1, snapshot()))
        self.assertFalse(policy.transition_allowed(0, 1, replace(snapshot(), memory_max=750)))
        self.assertFalse(policy.transition_allowed(0, 1, replace(snapshot(), memory_current=None)))
        self.assertFalse(policy.transition_allowed(0, 2, snapshot()))

    def test_uncalibrated_profile_only_observes(self):
        cfg = profile()
        cfg["calibrated"] = False
        policy = PressurePolicy(cfg)
        bus = mock_factory(EventLog(io.StringIO()))
        for t in range(1, 10):
            self.assertIsNone(policy.decide(snapshot(t), {"cpu_psi_some_fraction": 0.8}, bus))
        self.assertEqual(bus.queue.qsize(), 0)

    def test_safe_boundary_rechecks_a_cap_that_changed_after_tier_request(self):
        log = EventLog(io.StringIO())
        bus = mock_factory(log)
        bus.start()
        self.addCleanup(bus.stop)
        current = [snapshot()]
        monitor = Telemetry(bus, log, read_snapshot=lambda: current[0], policy=PressurePolicy(profile()))
        bus.tier_guard = monitor._guard
        bus.publish("ears", {"type": "partial", "turn": 0})
        bus.request_tier(1)
        bus.dispatch_one(timeout=0)
        bus.dispatch_one(timeout=0)
        current[0] = replace(current[0], memory_max=750)
        bus.finish_turn(0)
        bus.dispatch_one(timeout=0)
        self.assertEqual(bus.tier, 0)
        self.assertEqual(bus.tier_revision, 1)

    def test_monitor_connects_risk_to_deferred_tier_and_resource_accounting(self):
        log = EventLog(io.StringIO())
        bus = mock_factory(log)
        bus.start()
        self.addCleanup(bus.stop)
        tick = [0]
        def read():
            tick[0] += 1
            return snapshot(tick[0], tick[0] * 1000000, tick[0] * 500000)
        monitor = Telemetry(bus, log, read_snapshot=read, policy=PressurePolicy(profile()))
        bus.tier_guard = monitor._guard
        for _ in range(4):
            monitor._sample()
            while not bus.queue.empty(): bus.dispatch_one(timeout=0)
        self.assertEqual(bus.tier, 1)
        self.assertGreater(monitor.summary()["accounting"]["cpu_s"], 0)

    def test_runner_saves_monitoring_and_dashboard_with_unavailable_counters(self):
        plan = {"run_id": "integrated", "platform": "synthetic", "configuration": "mock",
                "synthetic": True, "cases": [{"case_id": "one", "text": "<script>bad</script>", "timeout_s": 2}]}
        output = self.root / "run"
        summary = ExperimentRunner(plan, output, mock_factory, MockDriver(),
                                   lambda bus, log: Telemetry(bus, log)).run()
        self.assertEqual(summary["completed_cases"], 1)
        resources = json.loads((output / "resources.json").read_text())
        self.assertIsNone(resources["energy"]["gross_j"])
        html = (output / "dashboard.html").read_text()
        self.assertIn("SYNTHETIC", html)
        self.assertNotIn("<script>bad</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_live_tail_waits_for_complete_json_line(self):
        path = self.root / "events.jsonl"
        path.write_bytes(b'{"event":"run_')
        tail = EventTail(path)
        self.assertEqual(tail.read(), [])
        with path.open("ab") as stream: stream.write(b'end","extra":{}}\n')
        self.assertEqual(tail.read()[0]["event"], "run_end")
        self.assertEqual(tail.read(), [])

    def test_dashboard_strips_terminal_control_characters(self):
        state = DashboardState()
        state.update({"event": "transcript", "extra": {"text": "hi\x1b[2J", "final": True}})
        self.assertNotIn("\x1b", state.terminal())

    def test_transient_counter_reset_cannot_hide_in_turn_or_run_totals(self):
        log = EventLog(io.StringIO())
        bus = mock_factory(log)
        samples = iter([snapshot(1, 100), snapshot(2, 50), snapshot(3, 300)])
        monitor = Telemetry(bus, log, read_snapshot=lambda: next(samples))
        monitor.mark_start(0)
        monitor._sample(control=False)
        monitor.mark_end(0)
        self.assertIsNone(monitor.turns[0]["cpu_s"])
        self.assertIsNone(monitor.summary()["accounting"]["cpu_s"])


if __name__ == "__main__":
    unittest.main()
