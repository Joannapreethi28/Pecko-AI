from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from spine.resources import (effective_cpu_limit, energy_summary, rapl_delta_j,
                             read_snapshot, usage_delta)


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        files = {"cpu.stat": "usage_usec 1000000\nuser_usec 700000\n",
                 "cpu.max": "150000 100000\n", "cpuset.cpus.effective": "0-1,3\n",
                 "memory.current": "1000", "memory.peak": "2000",
                 "memory.max": "3000", "memory.swap.max": "0",
                 "cpu.pressure": "some avg10=0.1 avg60=0.1 avg300=0.1 total=20000\n",
                 "memory.events": "oom 0\noom_kill 0\n"}
        for name, content in files.items():
            (self.path / name).write_text(content, encoding="ascii")
        self.before = read_snapshot(self.path, t=10)

    def test_reading_accounts_for_quota_and_cpuset(self):
        self.assertEqual(effective_cpu_limit(self.before), 1.5)
        self.assertEqual(self.before.memory_peak, 2000)
        self.assertEqual(self.before.unavailable, ())
        self.assertEqual(effective_cpu_limit(replace(self.before, cpu_max="max 100000")), 3)

    def test_delta_uses_cpu_seconds_and_short_psi_window(self):
        after = replace(self.before, t=12, cpu_usage_usec=4000000, psi_some_usec=220000)
        delta = usage_delta(self.before, after)
        self.assertEqual(delta["cpu_s"], 3)
        self.assertEqual(delta["mean_cores"], 1.5)
        self.assertAlmostEqual(delta["cpu_psi_some_fraction"], 0.1)

    def test_cap_change_resets_pressure_window(self):
        after = replace(self.before, t=12, cpu_max="100000 100000", psi_some_usec=220000)
        delta = usage_delta(self.before, after)
        self.assertTrue(delta["regime_changed"])
        self.assertIsNone(delta["cpu_psi_some_fraction"])

    def test_missing_counters_are_unavailable_not_zero(self):
        (self.path / "cpu.stat").unlink()
        after = read_snapshot(self.path, t=12)
        self.assertIsNone(after.cpu_usage_usec)
        self.assertIsNone(usage_delta(self.before, after)["cpu_s"])
        self.assertTrue(after.unavailable)

    def test_unlimited_memory_is_distinct_from_missing_limit(self):
        (self.path / "memory.max").write_text("max")
        snapshot = read_snapshot(self.path)
        self.assertTrue(snapshot.memory_limit_unbounded)
        self.assertIsNone(snapshot.memory_max)

    def test_counter_reset_cannot_become_negative_cpu_use(self):
        after = replace(self.before, t=12, cpu_usage_usec=1)
        self.assertIsNone(usage_delta(self.before, after)["cpu_s"])

    def test_rapl_wrap_and_energy_accounting(self):
        self.assertAlmostEqual(rapl_delta_j(900000, 100000, 1000000), 0.2)
        result = energy_summary(100, 10, 5, 4, idle_watts=2)
        self.assertEqual(result["gross_j_per_turn"], 20)
        self.assertEqual(result["idle_adjusted_j_per_turn"], 16)
        self.assertEqual(result["successful_turns_per_gross_j"], 0.04)
        self.assertIsNone(energy_summary(0, 1, 1, 0)["successful_turns_per_gross_j"])

    def test_nonfinite_energy_is_rejected(self):
        with self.assertRaises(ValueError):
            energy_summary(float("nan"), 10, 5, 4)


if __name__ == "__main__":
    unittest.main()
