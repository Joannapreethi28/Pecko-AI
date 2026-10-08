"""Swappable stage runtime. Registry factories are trusted Python code, not plan data."""

import argparse
import json
from pathlib import Path

from spine.bus import EventBus
from spine.experiment import ExperimentRunner
from spine.placeholders import FACTORIES
from spine.wav_placeholder import WavPlaceholderEars

BUILTIN_FACTORIES = dict(FACTORIES, **{"ears:wav-placeholder": WavPlaceholderEars})


class StageContext:
    """Role-scoped callback bindings shared by placeholders and real factories."""
    def __init__(self, role, bus, log, synthetic):
        self.role, self._bus, self._log, self.synthetic = role, bus, log, synthetic

    def publish(self, msg):
        self._bus().publish(self.role, msg)

    def log(self, event, turn=None, **extra):
        if self.synthetic:
            extra["synthetic"] = True
        self._log.emit(self.role, event, turn, **extra)

    def fail(self, reason):
        self._bus().fail(self.role, reason)

    def prepared(self, turn, gen, tokens):
        if self.role != "brain": raise ValueError("Only Brain prepares prompts")
        self._bus().prepared(turn, gen, tokens)

    def validate(self, turn, gen, tokens):
        if self.role != "brain": raise ValueError("Only Brain validates prompts")
        self._bus().validate_final(turn, gen, tokens)

    def complete(self, turn, gen, **outcome):
        if self.role != "voice": raise ValueError("Voice/supervisor confirms drained playback")
        self._bus().complete_turn(turn, gen, **outcome)


def validate_profile(profile, registry):
    if not isinstance(profile, dict):
        raise ValueError("Runtime profile must be an object")
    if type(profile.get("synthetic")) is not bool:
        raise ValueError("Runtime must declare synthetic true/false")
    if not isinstance(profile.get("stages"), dict) or set(profile["stages"]) != {"ears", "brain", "voice"}:
        raise ValueError("Runtime must define all three stages")
    for role, item in profile["stages"].items():
        if not isinstance(item, dict):
            raise ValueError("Each stage profile must be an object")
        key = f"{role}:{item.get('adapter')}"
        if key not in registry:
            raise ValueError(f"No registered factory for {key}")
        if not isinstance(item.get("config", {}), dict):
            raise ValueError("Stage config must be an object")
        if not profile["synthetic"] and getattr(registry[key], "placeholder", False):
            raise ValueError("Placeholder engines require synthetic:true")


def make_factory(profile, registry=None):
    """Real owners register role:name -> factory(context, config) in trusted code.

    Stage construction must not load/start workers; that belongs in start().
    A mixed runtime remains synthetic until every placeholder has been replaced.
    """
    registry = dict(BUILTIN_FACTORIES if registry is None else registry)
    validate_profile(profile, registry)
    def create(log):
        bus = None
        stages = {}
        for role in ("ears", "brain", "voice"):
            context = StageContext(role, lambda: bus, log, profile["synthetic"])
            item = profile["stages"][role]
            stages[role] = registry[f"{role}:{item['adapter']}"](context, item.get("config", {}))
            if getattr(stages[role], "placeholder", False) and not profile["synthetic"]:
                raise ValueError("Runtime instance is a placeholder; require synthetic:true")
            for method in ("start", "feed", "stop", "set_tier"):
                if not callable(getattr(stages[role], method, None)):
                    raise ValueError(f"{role} adapter is missing {method}")
        bus = EventBus(stages, log)
        return bus
    return create


class ReplayDriver:
    def begin(self, case, turn, bus, log):
        return bus.stages["ears"].replay(case, turn)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        profile = json.loads(args.profile.read_text(encoding="utf-8-sig"))
        plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
        for case in plan.get("cases", []):
            if "wav" in case:
                path = Path(case["wav"])
                case["wav"] = str((args.plan.parent / path).resolve() if not path.is_absolute() else path)
        factory = make_factory(profile)
        if plan.get("synthetic") != profile["synthetic"]:
            raise ValueError("Plan and runtime synthetic declarations must match")
        from spine.energy import RaplMeter
        from spine.resources import own_cgroup, read_snapshot
        from spine.telemetry import Telemetry
        try:
            path = own_cgroup()
        except OSError:
            path = None
        monitor = lambda bus, log: Telemetry(bus, log,
            read_snapshot=(lambda: read_snapshot(path)) if path else None, energy=RaplMeter())
        summary = ExperimentRunner(plan, args.output, factory, ReplayDriver(), monitor).run()
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(summary, indent=2))
    if summary["aborted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
