"""Create and replay an explicitly synthetic tone fixture through PCM ingress."""

import argparse
import json
import math
from pathlib import Path
import struct
import wave

from spine.experiment import ExperimentRunner, write_json
from spine.runtime import make_factory, ReplayDriver
from spine.telemetry import Telemetry


def create_fixture(path, duration_s=0.2):
    frames = int(duration_s * 16000)
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        # Test tone followed by silence; never represents a real spoken recording.
        pcm = b"".join(struct.pack("<h", int(1000 * math.sin(2 * math.pi * 440 * i / 16000)) if i < frames * 0.6 else 0)
                       for i in range(frames))
        target.writeframes(pcm)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    path = (args.output / "synthetic-tone.wav").resolve()
    create_fixture(path)
    profile = {"synthetic": True, "stages": {
        "ears": {"adapter": "wav-placeholder"}, "brain": {"adapter": "placeholder"},
        "voice": {"adapter": "placeholder"}}}
    conditions = {"llm_id": "placeholder-no-LLM", "cpu_limit": "unenforced",
                  "memory_limit": "unenforced", "input_set_id": "synthetic-tone-only", "warmup": True}
    plan = {"run_id": "synthetic-wav-ingress", "platform": "portable-development",
            "configuration": "wav-plus-placeholders", "synthetic": True, "conditions": conditions,
            "cases": [{"case_id": "tone-fixture", "wav": str(path), "reference_text": "This is supplied reference text",
                       "eos_offset_s": 0.12, "timeout_s": 3}]}
    write_json(args.output / "runtime.json", profile)
    write_json(args.output / "input-plan.json", plan)
    result = ExperimentRunner(plan, args.output / "run", make_factory(profile), ReplayDriver(),
                              lambda bus, log: Telemetry(bus, log)).run()
    print(json.dumps(result, indent=2))
    if result["aborted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
