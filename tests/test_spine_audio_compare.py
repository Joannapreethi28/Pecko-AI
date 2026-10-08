from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest
import wave

from common.clock import now
from spine.audio import inspect_wav, WavReplayer
from spine.batch import run_batch
from spine.compare import compare_reports
from spine.experiment import ExperimentRunner
from spine.report import load_events
from spine.runtime import make_factory, ReplayDriver
from spine.suite import generate
from spine.wav_demo import create_fixture
from spine.placeholders import FACTORIES, PlaceholderEars


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.path = self.root / "tone.wav"
        create_fixture(self.path, duration_s=0.06)

    def test_replay_preserves_samples_and_capture_clock_and_is_paced(self):
        metadata = inspect_wav(self.path, 0.04)
        frames, errors = [], []
        done = Event()
        player = WavReplayer(frames.append, lambda turn: done.set(), errors.append)
        self.addCleanup(player.stop)
        start = now()
        eos = player.start(self.path, 7, metadata, capture_start=start)
        self.assertTrue(done.wait(2))
        self.assertFalse(errors)
        self.assertEqual(len(frames), 3)
        self.assertEqual(sum(len(frame.pcm) // 2 for frame in frames), 960)
        self.assertEqual([frame.offset_frames for frame in frames], [0, 320, 640])
        self.assertAlmostEqual(eos, start + 0.04)
        self.assertAlmostEqual(frames[1].t_capture, start + 0.02)
        self.assertGreaterEqual(now() - start, 0.06)

    def test_cancellation_stops_replay_without_end_callback(self):
        create_fixture(self.path, duration_s=1)
        ended, errors = [], []
        player = WavReplayer(lambda frame: None, ended.append, errors.append)
        player.start(self.path, 0, inspect_wav(self.path, 0.6))
        player.stop()
        self.assertEqual(ended, [])
        self.assertEqual(errors, [])
        self.assertTrue(player.stats["cancelled"])

    def test_changed_pcm_is_detected_before_endpoint_completion(self):
        metadata = inspect_wav(self.path, 0.04)
        with wave.open(str(self.path), "wb") as target:
            target.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            target.writeframes(b"\0" * 1920)
        done, errors = Event(), []
        player = WavReplayer(lambda frame: None, lambda turn: self.fail("Must not complete changed PCM"),
                             lambda reason: (errors.append(reason), done.set()))
        self.addCleanup(player.stop)
        player.start(self.path, 0, metadata)
        self.assertTrue(done.wait(2))
        self.assertIn("changed", errors[0])

    def test_out_of_bounds_label_and_wrong_format_rejected(self):
        with self.assertRaises(ValueError): inspect_wav(self.path, 1)
        with wave.open(str(self.path), "wb") as target:
            target.setparams((2, 2, 16000, 0, "NONE", "not compressed"))
            target.writeframes(b"\0" * 1920)
        with self.assertRaises(ValueError): inspect_wav(self.path, 0.01)

    def test_wav_runtime_records_fingerprint_and_never_claims_asr_or_audio(self):
        profile = {"synthetic": True, "stages": {role: {"adapter": "wav-placeholder" if role == "ears" else "placeholder"}
                                                  for role in ("ears", "brain", "voice")}}
        plan = {"run_id": "wav", "platform": "synthetic", "configuration": "placeholder", "synthetic": True,
                "cases": [{"case_id": "tone", "wav": str(self.path), "eos_offset_s": 0.04,
                           "reference_text": "reference only", "timeout_s": 2}]}
        output = self.root / "run"
        summary = ExperimentRunner(plan, output, make_factory(profile), ReplayDriver()).run()
        self.assertEqual(summary["completed_cases"], 1)
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["turns"][0]["input_sha256"], inspect_wav(self.path, 0.04)["sha256"])
        self.assertFalse(report["headline_ready"])
        self.assertFalse(any(e["event"] == "first_audio_out" for e in load_events(output / "events.jsonl")))

    def test_paired_batch_runs_every_profile_repeat_and_preserves_synthetic_status(self):
        profile = {"synthetic": True, "stages": {role: {"adapter": "placeholder"} for role in ("ears", "brain", "voice")}}
        template = {"run_id": "batch", "platform": "synthetic", "configuration": "placeholder", "synthetic": True,
                    "cases": [{"case_id": "one", "text": "hello", "timeout_s": 2}]}
        output = self.root / "batch"
        result = run_batch(template, profile, profile, output, repeats=3)
        self.assertEqual(result["expected_runs"], 6)
        self.assertEqual(result["runs_recorded"], 6)
        self.assertEqual(result["aborted_runs"], 0)
        self.assertFalse(result["measured_comparison_ready"])
        self.assertEqual(len(result["comparisons"]), 3)
        self.assertIn("SYNTHETIC", (output / "index.html").read_text())
        for repeat in range(1, 4): self.assertTrue((output / f"comparison-repeat-{repeat}.json").is_file())

    def test_interrupted_batch_does_not_start_later_runs(self):
        class InterruptedEars(PlaceholderEars):
            def replay(self, case, turn):
                raise KeyboardInterrupt()
        registry = dict(FACTORIES)
        registry["ears:placeholder"] = InterruptedEars
        profile = {"synthetic": True, "stages": {role: {"adapter": "placeholder"} for role in ("ears", "brain", "voice")}}
        template = {"run_id": "interrupt", "platform": "synthetic", "configuration": "placeholder", "synthetic": True,
                    "cases": [{"case_id": "one", "text": "hello", "timeout_s": 2}]}
        result = run_batch(template, profile, profile, self.root / "interrupted", repeats=3, registry=registry)
        self.assertTrue(result["interrupted"])
        self.assertEqual(result["aborted_runs"], 1)
        self.assertEqual(result["not_started_runs"], 5)


def report(latency, synthetic=False):
    return {"run_id": str(latency), "platform": "test-host", "synthetic": synthetic, "headline_ready": True,
            "conditions": {"llm_id": "same-model", "cpu_limit": 2, "memory_limit": 2**31,
                           "input_set_id": "fixed", "warmup": True},
            "headline_latency_s": {"p50": latency, "p90": latency},
            "turns": [{"turn": 0, "case_id": "one", "success": True, "issues": [], "timeout_s": 5,
                       "input_sha256": "a" * 64, "observed_first_audio_s": latency, "timeout_scored_latency_s": latency}]}


class CompareTests(unittest.TestCase):
    def test_paired_gain_and_percentile_reduction_are_separate(self):
        result = compare_reports(report(2), report(1))
        self.assertTrue(result["measured_comparison_ready"])
        self.assertEqual(result["measured_paired_gain_s"]["mean"], 1)
        self.assertEqual(result["latency_percentile_reduction_s"]["p90"], 1)

    def test_failures_and_missing_cases_cannot_be_dropped(self):
        candidate = report(1)
        failed = deepcopy(candidate["turns"][0])
        failed.update(case_id="missing-in-baseline", success=False, observed_first_audio_s=None, timeout_scored_latency_s=5)
        candidate["turns"].append(failed)
        result = compare_reports(report(2), candidate)
        self.assertEqual(result["expected_pairs"], 2)
        self.assertFalse(result["measured_comparison_ready"])
        self.assertIsNone(result["timeout_scored_paired_gain_s"]["p50"])

    def test_different_inputs_or_caps_withhold_measured_gain(self):
        candidate = report(1)
        candidate["conditions"]["cpu_limit"] = 1
        candidate["turns"][0]["input_sha256"] = "b" * 64
        result = compare_reports(report(2), candidate)
        self.assertIn("condition_mismatch:cpu_limit", result["comparison_issues"])
        self.assertIn("input_mismatch", result["pairs"][0]["issues"])
        self.assertFalse(result["measured_comparison_ready"])

    def test_synthetic_comparison_cannot_become_measured_gain(self):
        result = compare_reports(report(2, synthetic=True), report(1, synthetic=True))
        self.assertFalse(result["measured_comparison_ready"])
        self.assertIsNone(result["measured_paired_gain_s"]["mean"])

    def test_unequal_failure_timeout_policies_not_aggregated(self):
        candidate = report(1)
        candidate["turns"][0]["timeout_s"] = 10
        result = compare_reports(report(2), candidate)
        self.assertIsNone(result["timeout_scored_paired_gain_s"]["p50"])

    def test_unverified_input_identity_withholds_aggregated_score(self):
        candidate = report(1)
        candidate["turns"][0]["input_sha256"] = None
        result = compare_reports(report(2), candidate)
        self.assertIsNone(result["timeout_scored_paired_gain_s"]["p50"])

    def test_seeded_suite_matches_turn_order_and_rotates_run_order(self):
        with tempfile.TemporaryDirectory() as root:
            template = {"run_id": "suite", "platform": "synthetic", "configuration": "mock", "synthetic": True,
                        "cases": [{"case_id": str(i), "text": "test", "timeout_s": 3} for i in range(8)]}
            output = Path(root) / "plans"
            schedule = generate(template, output, ["B0", "Pecko"], 3, 42)
            self.assertEqual(len(schedule["schedule"]), 6)
            for repeat in range(1, 4):
                one = json.loads((output / f"repeat-{repeat}-configuration-1.json").read_text())
                two = json.loads((output / f"repeat-{repeat}-configuration-2.json").read_text())
                self.assertEqual(one["cases"], two["cases"])
            self.assertEqual(schedule["schedule"][2]["configuration"], "Pecko")


if __name__ == "__main__":
    unittest.main()
