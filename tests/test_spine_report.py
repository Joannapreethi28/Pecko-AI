import copy
import unittest

from spine.report import build_report


def event(stage, name, turn, t, **extra):
    return {"stage": stage, "event": name, "turn": turn, "t": t, "extra": extra}


def manifest(synthetic=False):
    return {"run_id": "test", "platform": "unit-test", "configuration": "fixture",
            "synthetic": synthetic,
            "turns": [{"turn": 1, "case_id": "ordinary-01", "t_eos": 10,
                       "timeout_s": 5}]}


def trace():
    return [event("ears", "endpoint", 1, 10.2),
            event("spine", "commit", 1, 10.3, gen=2),
            event("voice", "pcm_ready", 1, 10.5, gen=2, seq=0),
            event("voice", "first_audio_out", 1, 10.55, gen=2, content=True, sustained=True),
            event("spine", "turn_end", 1, 11.5, success=True, gap_s=0)]


class ReportTests(unittest.TestCase):
    def test_labelled_eos_and_matching_generation_determine_critical_path(self):
        events = trace()
        events.insert(0, event("voice", "pcm_ready", 1, 9, gen=1, seq=0))
        result = build_report(manifest(), reversed(events))
        self.assertAlmostEqual(result["headline_latency_s"]["p50"], 0.55)
        row = result["turns"][0]
        self.assertEqual(row["generation"], 2)
        self.assertEqual(row["limiting_dependency"], "answer_ready")
        self.assertAlmostEqual(row["device_and_dispatch_s"], 0.05)

    def test_commit_later_than_pcm_is_limiting(self):
        events = trace()
        events[1]["t"] = 10.52
        result = build_report(manifest(), events)
        self.assertEqual(result["critical_path_counts"]["commit"], 1)

    def test_stale_generation_does_not_contaminate_brain_timeline(self):
        events = trace() + [event("brain", "first_token", 1, 9, gen=1),
                            event("brain", "first_token", 1, 10.4, gen=2)]
        result = build_report(manifest(), events)
        self.assertAlmostEqual(result["turns"][0]["timeline"]["first_token_s"], 0.4)

    def test_missing_turn_is_preserved_with_separate_timeout_score(self):
        data = manifest()
        data["turns"].append({"turn": 2, "case_id": "missing", "t_eos": 20, "timeout_s": 5})
        result = build_report(data, trace())
        self.assertEqual(result["expected_turns"], 2)
        self.assertEqual(result["failed_or_incomplete_turns"], 1)
        self.assertIsNone(result["headline_latency_s"]["p90"])
        self.assertIsNone(result["turns"][1]["observed_first_audio_s"])
        self.assertEqual(result["turns"][1]["timeout_scored_latency_s"], 5)
        self.assertAlmostEqual(result["timeout_scored_latency_s"]["p90"], 4.555)

    def test_failed_turn_with_audio_still_counts_as_failure(self):
        events = trace()
        events[-1]["extra"].update(success=False, reason="wrong answer")
        result = build_report(manifest(), events)
        self.assertEqual(result["turns"][0]["timeout_scored_latency_s"], 5)
        self.assertEqual(result["turns"][0]["failure_reason"], "wrong answer")

    def test_fillers_and_unverified_audio_do_not_enter_headline(self):
        events = trace()
        events[3]["extra"]["content"] = False
        result = build_report(manifest(), events)
        self.assertIsNone(result["turns"][0]["observed_first_audio_s"])

    def test_mock_marker_overrides_real_manifest_claim(self):
        events = trace() + [event("spine", "mock_run", None, 1, synthetic=True)]
        result = build_report(manifest(), events)
        self.assertTrue(result["synthetic"])
        self.assertFalse(result["headline_ready"])

    def test_cleanup_failure_withholds_otherwise_complete_headline(self):
        result = build_report(manifest(), trace() + [event("spine", "stop_error", None, 12, error="worker alive")])
        self.assertFalse(result["headline_ready"])
        self.assertEqual(result["run_issues"], ["stop_error"])

    def test_audio_before_commit_is_invalid(self):
        events = trace()
        events[1]["t"] = 10.6
        result = build_report(manifest(), events)
        self.assertIn("audio_before_commit_or_pcm", result["turns"][0]["issues"])

    def test_baseline_without_commit_still_has_latency(self):
        events = [e for e in trace() if e["event"] != "commit"]
        result = build_report(manifest(), events)
        self.assertTrue(result["headline_ready"])
        self.assertIsNone(result["turns"][0]["commit_s"])

    def test_unknown_gap_is_not_reported_as_zero(self):
        events = trace()
        del events[-1]["extra"]["gap_s"]
        result = build_report(manifest(), events)
        self.assertEqual(result["gap_s"], {"known_turns": 0, "total": None})

    def test_invalid_manifest_and_nonfinite_events_rejected(self):
        data = manifest()
        data["turns"].append(copy.deepcopy(data["turns"][0]))
        with self.assertRaises(ValueError):
            build_report(data, trace())
        events = trace()
        events[0]["t"] = float("nan")
        with self.assertRaises(ValueError):
            build_report(manifest(), events)


if __name__ == "__main__":
    unittest.main()
