import io
import json
from pathlib import Path
import tempfile
import unittest

from common.log import EventLog
from spine.experiment import ExperimentRunner
from spine.placeholders import FACTORIES
from spine.preflight import inspect
from spine.report import load_events
from spine.runtime import make_factory, ReplayDriver, StageContext


ROOT = Path(__file__).resolve().parents[1]


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.output = Path(self.folder.name) / "run"
        self.profile = json.loads((ROOT / "spine/examples/runtime.placeholder.json").read_text())

    def test_scripted_correction_and_prompt_revision_release_only_committed_generations(self):
        plan = json.loads((ROOT / "spine/examples/plan.scripted.json").read_text())
        result = ExperimentRunner(plan, self.output, make_factory(self.profile), ReplayDriver()).run()
        self.assertEqual(result["completed_cases"], 3)
        events = load_events(self.output / "events.jsonl")
        for turn in range(3):
            commits = [e for e in events if e["turn"] == turn and e["event"] == "commit"]
            releases = [e for e in events if e["turn"] == turn and e["event"] == "placeholder_release"]
            self.assertEqual(len(releases), 1)
            self.assertEqual(releases[0]["extra"]["gen"], commits[-1]["extra"]["gen"])
            self.assertGreaterEqual(releases[0]["t"], commits[-1]["t"])
        revisions = [e for e in events if e["event"] == "prompt_mismatch"]
        self.assertEqual(len(revisions), 1)
        self.assertFalse(any(e["event"] == "first_audio_out" for e in events))

    def test_placeholder_profile_cannot_claim_real_engines(self):
        self.profile["synthetic"] = False
        with self.assertRaisesRegex(ValueError, "Placeholder"):
            make_factory(self.profile)

    def test_missing_adapter_fails_before_startup(self):
        self.profile["stages"]["brain"]["adapter"] = "not-installed"
        with self.assertRaisesRegex(ValueError, "registered factory"):
            make_factory(self.profile)

    def test_real_owner_can_register_stage_factory_without_changing_bus(self):
        registry = dict(FACTORIES)
        registry["brain:team-adapter"] = registry["brain:placeholder"]
        self.profile["stages"]["brain"]["adapter"] = "team-adapter"
        bus = make_factory(self.profile, registry)(EventLog(io.StringIO()))
        self.assertEqual(set(bus.stages), {"ears", "brain", "voice"})

    def test_role_scoped_callbacks_cannot_prepare_from_ears(self):
        context = StageContext("ears", lambda: None, EventLog(io.StringIO()), True)
        with self.assertRaises(ValueError): context.prepared(0, 0, [1])
        with self.assertRaises(ValueError): context.complete(0, 0, success=True)

    def test_preflight_missing_hardware_or_models_cannot_claim_readiness(self):
        report = inspect(cgroup=Path(self.folder.name))
        self.assertFalse(report["automated_checks_passed"])
        self.assertFalse(report["judged_loop_ready"])
        self.assertTrue(report["manual_gates"])


if __name__ == "__main__":
    unittest.main()
