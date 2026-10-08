"""Real Voice (voice.team_adapter, real Piper engine, NullPlayer) inside Spine's real bus + ExperimentRunner,
with Spine's placeholder Ears/Brain and scripted plan. Skipped when the Piper model is not downloaded."""
import json
from pathlib import Path

import pytest

from spine.experiment import ExperimentRunner
from spine.placeholders import FACTORIES
from spine.report import load_events
from spine.runtime import ReplayDriver, make_factory
from voice.engine import MODELS, TIERS
from voice.team_adapter import create_stage

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not any((MODELS / TIERS[0]["engine"]).glob("*.onnx")),
                                reason="Piper model not downloaded (python voice/get_models.py)")


def test_real_voice_in_spine_pipeline(tmp_path):
    profile = json.loads((ROOT / "spine/examples/runtime.placeholder.json").read_text())
    profile["stages"]["voice"] = {"adapter": "team", "config": {"audio": False}}
    registry = dict(FACTORIES, **{"voice:team": create_stage})
    plan = json.loads((ROOT / "spine/examples/plan.scripted.json").read_text())
    result = ExperimentRunner(plan, tmp_path / "run", make_factory(profile, registry), ReplayDriver()).run()
    assert result["completed_cases"] == len(plan["cases"])

    events = load_events(tmp_path / "run" / "events.jsonl")
    for turn in sorted({e["turn"] for e in events if e["event"] == "commit"}):
        commit = [e for e in events if e["turn"] == turn and e["event"] == "commit"][-1]
        audio = [e for e in events if e["stage"] == "voice" and e["turn"] == turn and e["event"] == "first_audio_out"]
        pcm = [e for e in events if e["stage"] == "voice" and e["turn"] == turn and e["event"] == "pcm_ready"
               and e["extra"].get("seq") == 0 and e["extra"].get("gen") == commit["extra"]["gen"]]
        assert len(audio) == 1, f"turn {turn}: one first_audio_out"
        a = audio[0]["extra"]
        assert a["content"] is True and a["sustained"] is True             # spine/report.py headline criteria
        assert a["gen"] == commit["extra"]["gen"]                          # only the committed gen is heard
        assert audio[0]["t"] >= commit["t"]                                # nothing audible before commit (v2.1)
        assert pcm, f"turn {turn}: pcm_ready seq 0 for the committed gen (R)"
