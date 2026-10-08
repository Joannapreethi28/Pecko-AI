import json
from pathlib import Path
from queue import Empty
import tempfile
from threading import Thread
import unittest

from spine.experiment import ExperimentRunner, MockDriver, mock_factory
from spine.report import load_events


def plan(behaviors=("reply", "reply")):
    return {"run_id": "test-run", "platform": "synthetic", "configuration": "mock",
            "synthetic": True,
            "cases": [{"case_id": f"case-{i}", "text": "Hello",
                       "timeout_s": 0.05 if behavior == "timeout" else 2,
                       "behavior": behavior} for i, behavior in enumerate(behaviors)]}


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.output = Path(self.folder.name) / "run"
        self.bus = None

    def factory(self, log):
        self.bus = mock_factory(log)
        return self.bus

    def run_plan(self, data, factory=None):
        return ExperimentRunner(data, self.output, factory or self.factory, MockDriver()).run()

    def test_multi_turn_run_completes_and_writes_all_artifacts(self):
        summary = self.run_plan(plan())
        self.assertEqual(summary["completed_cases"], 2)
        self.assertIsNone(summary["aborted"])
        self.assertEqual(self.bus._started, [])
        for name in ("plan.json", "events.jsonl", "manifest.json", "runner_summary.json", "report.json"):
            self.assertTrue((self.output / name).is_file())
        events = load_events(self.output / "events.jsonl")
        self.assertEqual(sum(e["event"] == "turn_end" for e in events), 2)
        report = json.loads((self.output / "report.json").read_text())
        self.assertTrue(report["synthetic"])
        self.assertFalse(report["headline_ready"])
        self.assertIsNone(report["headline_latency_s"]["p50"])

    def test_timeout_stops_stages_and_preserves_remaining_cases(self):
        summary = self.run_plan(plan(("reply", "timeout", "reply")))
        self.assertEqual([r["status"] for r in summary["outcomes"]],
                         ["completed", "failed", "not_started"])
        self.assertIn("TimeoutError", summary["aborted"])
        self.assertEqual(self.bus._started, [])
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertIsNotNone(manifest["turns"][1]["t_eos"])
        self.assertIsNone(manifest["turns"][2]["t_eos"])
        report = json.loads((self.output / "report.json").read_text())
        self.assertEqual(report["expected_turns"], 3)
        events = load_events(self.output / "events.jsonl")
        self.assertEqual(sum(e["event"] == "turn_end" for e in events), 3)

    def test_startup_failure_leaves_all_declared_cases_visible(self):
        def broken(log):
            raise RuntimeError("model loading failed")
        summary = self.run_plan(plan(), factory=broken)
        self.assertEqual(summary["completed_cases"], 0)
        self.assertTrue(all(r["status"] == "not_started" for r in summary["outcomes"]))
        self.assertTrue((self.output / "report.json").is_file())

    def test_driver_error_preserves_results_from_previous_turn(self):
        summary = self.run_plan(plan(("reply", "error", "reply")))
        self.assertEqual(summary["completed_cases"], 1)
        self.assertIn("RuntimeError", summary["aborted"])
        self.assertEqual(len(summary["outcomes"]), 3)

    def test_existing_evidence_is_not_overwritten(self):
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("evidence")
        with self.assertRaises(FileExistsError):
            self.run_plan(plan())
        self.assertEqual(marker.read_text(), "evidence")
        self.assertIsNone(self.bus)

    def test_worker_error_aborts_runner_without_waiting_for_timeout(self):
        class BrokenWorkerDriver:
            def begin(self, case, turn, bus, log):
                from common.clock import now
                worker = Thread(target=lambda: bus.fail("voice", "synthesis failed"))
                worker.start()
                worker.join()
                return now()
        summary = ExperimentRunner(plan(), self.output, self.factory, BrokenWorkerDriver()).run()
        self.assertIn("voice worker failed", summary["aborted"])
        self.assertEqual(self.bus._started, [])

    def test_full_queue_still_propagates_worker_failure(self):
        class OverloadedDriver:
            def begin(self, case, turn, bus, log):
                from common.clock import now
                from queue import Full
                try:
                    for _ in range(257):
                        bus.publish("ears", {"type": "partial", "turn": turn})
                except Full:
                    pass  # Emulates an isolated worker exception.
                return now()
        summary = ExperimentRunner(plan(), self.output, self.factory, OverloadedDriver()).run()
        self.assertIn("Event queue capacity exceeded", summary["aborted"])

    def test_scored_answer_failure_can_continue_after_confirmed_stop(self):
        class ScoredDriver(MockDriver):
            def begin(self, case, turn, bus, log):
                eos = super().begin(case, turn, bus, log)
                if turn == 0:
                    bus.stages["voice"].on_complete = lambda t, g, **kw: bus.complete_turn(
                        t, g, success=False, reason="unacceptable answer")
                return eos
        summary = ExperimentRunner(plan(), self.output, self.factory, ScoredDriver()).run()
        self.assertIsNone(summary["aborted"])
        self.assertEqual([r["status"] for r in summary["outcomes"]], ["failed", "completed"])

    def test_interruption_retains_declared_turns_and_cleans_up(self):
        class InterruptedDriver:
            def begin(self, *args):
                raise KeyboardInterrupt()
        summary = ExperimentRunner(plan(), self.output, self.factory, InterruptedDriver()).run()
        self.assertEqual(summary["aborted"], "interrupted")
        self.assertEqual(self.bus._started, [])
        self.assertEqual(len(summary["outcomes"]), 2)


if __name__ == "__main__":
    unittest.main()
