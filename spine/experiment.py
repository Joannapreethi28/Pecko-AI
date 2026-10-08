"""Sequential event-driven experiment runner with durable failure reporting.

CLI currently supplies a synthetic text driver. Real WAV/engine drivers can use
ExperimentRunner without changing the reporting format or stage contract.
"""

import argparse
import json
from pathlib import Path
from queue import Empty
import sys
from typing import Protocol

from common.clock import now
from common.log import EventLog
from spine.bus import EventBus
from spine.mock import MockStage
from spine.report import build_report, finite, load_events
from spine.dashboard import write_dashboard


class CaseDriver(Protocol):
    def begin(self, case: dict, turn: int, bus: EventBus, log: EventLog) -> float:
        """Enqueue replay/input promptly, return independently labelled EOS time.

        Workers should use complete_turn only after audio/work have stopped and
        the acceptable-answer judgement is available. No blocking inference here.
        """
        ...


def validate_plan(plan: dict) -> None:
    if not isinstance(plan, dict):
        raise ValueError("Plan must be an object")
    for field in ("run_id", "platform", "configuration"):
        if not isinstance(plan.get(field), str) or not plan[field]:
            raise ValueError(f"Plan needs {field}")
    if type(plan.get("synthetic")) is not bool:
        raise ValueError("Plan needs explicit synthetic true/false")
    if "conditions" in plan and not isinstance(plan["conditions"], dict):
        raise ValueError("Experiment conditions must be an object")
    if not isinstance(plan.get("cases"), list) or not plan["cases"]:
        raise ValueError("Plan needs a nonempty cases list")
    seen = set()
    for case in plan["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("case_id"), str) or not case["case_id"]:
            raise ValueError("Every case needs a case_id")
        if case["case_id"] in seen:
            raise ValueError("Case IDs must be unique within a run; use separate runs for repeats")
        seen.add(case["case_id"])
        if finite(case.get("timeout_s"), "timeout_s", minimum=0) == 0:
            raise ValueError("timeout_s must be positive")


def write_json(path: Path, value: dict) -> None:
    """Replace a checkpoint only after the complete new JSON has been written."""
    scratch = path.with_name(path.name + ".tmp")
    scratch.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    scratch.replace(path)


class ExperimentRunner:
    def __init__(self, plan: dict, output: Path, factory, driver: CaseDriver, telemetry_factory=None):
        validate_plan(plan)
        self.plan, self.output = plan, output
        self.factory, self.driver = factory, driver
        self.telemetry_factory = telemetry_factory

    def run(self) -> dict:
        # Existing evidence is never overwritten by a new run.
        self.output.mkdir(parents=True, exist_ok=False)
        write_json(self.output / "plan.json", self.plan)
        manifest = {k: self.plan[k] for k in ("run_id", "platform", "configuration", "synthetic")}
        manifest["conditions"] = self.plan.get("conditions", {})
        manifest["turns"] = [{"turn": i, "case_id": c["case_id"],
                              "t_eos": None, "not_started": True,
                              "timeout_s": c["timeout_s"]}
                             for i, c in enumerate(self.plan["cases"])]
        manifest_path = self.output / "manifest.json"
        write_json(manifest_path, manifest)
        outcomes = []
        aborted = None
        bus = None
        monitor = None
        active_turn = None
        with (self.output / "events.jsonl").open("w", encoding="utf-8") as stream:
            log = EventLog(stream)
            log.emit("spine", "run_start", synthetic=self.plan["synthetic"],
                     platform=self.plan["platform"], configuration=self.plan["configuration"])
            try:
                bus = self.factory(log)
                bus.start()
                if self.telemetry_factory:
                    monitor = self.telemetry_factory(bus, log)
                    monitor.start()
                for row, case in zip(manifest["turns"], self.plan["cases"]):
                    turn = row["turn"]
                    active_turn = turn
                    if monitor:
                        monitor.mark_start(turn)
                    log.emit("spine", "case_start", turn, case_id=case["case_id"])
                    eos = finite(self.driver.begin(case, turn, bus, log), "labelled EOS", minimum=0)
                    row.update(t_eos=eos, not_started=False)
                    write_json(manifest_path, manifest)
                    deadline = eos + case["timeout_s"]
                    while turn not in bus.outcomes:
                        remaining = deadline - now()
                        if remaining <= 0:
                            raise TimeoutError(f"Turn {turn} exceeded its deadline")
                        try:
                            bus.dispatch_one(timeout=remaining)
                        except Empty as exc:
                            raise TimeoutError(f"Turn {turn} exceeded its deadline") from exc
                    outcome = bus.outcomes[turn]
                    if monitor:
                        monitor.mark_end(turn)
                    active_turn = None
                    outcomes.append({"turn": turn, "case_id": case["case_id"],
                                     "status": "completed" if outcome["success"] else "failed",
                                     "reason": outcome["reason"]})
                    # A reported ordinary answer failure is safe to continue
                    # after confirmed completion. Exceptions/timeouts are fatal.
            except (Exception, KeyboardInterrupt) as exc:
                aborted = "interrupted" if isinstance(exc, KeyboardInterrupt) else f"{type(exc).__name__}: {exc}"
                log.emit("spine", "run_abort", reason=aborted)
            finally:
                if monitor is not None:
                    try:
                        if active_turn in monitor.turn_starts:
                            monitor.mark_end(active_turn)
                        monitor.stop()
                    except Exception as exc:
                        aborted = aborted or f"Telemetry shutdown: {exc}"
                        log.emit("spine", "telemetry_error", reason=str(exc))
                if bus is not None:
                    bus.stop()
                completed = {result["turn"] for result in outcomes}
                for row in manifest["turns"]:
                    if row["turn"] in completed:
                        continue
                    # The dispatcher may have recorded completion immediately
                    # before another operation failed. Never log it twice.
                    if bus is not None and row["turn"] in bus.outcomes:
                        outcome = bus.outcomes[row["turn"]]
                        outcomes.append({"turn": row["turn"], "case_id": row["case_id"],
                                         "status": "completed" if outcome["success"] else "failed",
                                         "reason": outcome["reason"]})
                        continue
                    reason = aborted or "no completion acknowledgement"
                    status = "not_started" if row["not_started"] else "failed"
                    log.emit("spine", "turn_end", row["turn"], success=False, reason=reason,
                             not_started=row["not_started"])
                    outcomes.append({"turn": row["turn"], "case_id": row["case_id"],
                                     "status": status, "reason": reason})
                write_json(manifest_path, manifest)
                log.emit("spine", "run_end", aborted=aborted, synthetic=self.plan["synthetic"])
        summary = {"run_id": self.plan["run_id"], "synthetic": self.plan["synthetic"],
                   "aborted": aborted, "expected_cases": len(manifest["turns"]),
                   "completed_cases": sum(r["status"] == "completed" for r in outcomes),
                   "outcomes": sorted(outcomes, key=lambda r: r["turn"])}
        write_json(self.output / "runner_summary.json", summary)
        report = build_report(manifest, load_events(self.output / "events.jsonl"))
        resources = monitor.summary() if monitor else None
        if resources is not None:
            resources["synthetic"] = self.plan["synthetic"]
            resources["run_id"] = self.plan["run_id"]
            started = sum(not row["not_started"] for row in manifest["turns"])
            resources["started_turns"] = started
            cpu_s = resources["accounting"].get("cpu_s")
            resources["cpu_s_per_started_turn"] = None if not started or cpu_s is None else cpu_s / started
            joules = resources["energy"].get("gross_j")
            wall = resources["accounting"].get("wall_s")
            resources["energy_per_started_turn"] = None
            if joules is not None and wall is not None and wall > 0 and started:
                from spine.resources import energy_summary
                resources["energy_per_started_turn"] = energy_summary(joules, wall, started, report["successful_turns"])
            write_json(self.output / "resources.json", resources)
        write_json(self.output / "report.json", report)
        write_dashboard(self.output / "dashboard.html", report,
                        load_events(self.output / "events.jsonl"), resources)
        return summary


class MockDriver:
    def begin(self, case, turn, bus, log):
        t = now()
        if case.get("behavior", "reply") == "error":
            raise RuntimeError("Requested synthetic driver failure")
        bus.publish("ears", {"type": "final", "turn": turn, "text": case["text"],
                             "norm": case["text"].lower(), "t_eos": t, "t_endpoint": t})
        # A timeout case deliberately receives no completion acknowledgement.
        bus.stages["voice"].on_complete = None if case.get("behavior") == "timeout" else bus.complete_turn
        return t


def mock_factory(log):
    stages = {name: MockStage(name, lambda src, msg: bus.publish(src, msg), log)
              for name in ("ears", "brain", "voice")}
    bus = EventBus(stages, log)
    stages["brain"].prepare = bus.prepared
    stages["brain"].validate = bus.validate_final
    return bus


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--telemetry", action="store_true", help="Sample cgroup pressure and package energy")
    parser.add_argument("--cgroup", type=Path)
    parser.add_argument("--rapl-root", type=Path, default=Path("/sys/class/powercap"))
    parser.add_argument("--policy", type=Path, help="Explicit calibrated pressure/transition profile")
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
        validate_plan(plan)
        if plan["synthetic"] is not True:
            raise ValueError("The built-in mock driver requires synthetic:true")
        for case in plan["cases"]:
            if not isinstance(case.get("text"), str) or case.get("behavior", "reply") not in ("reply", "timeout", "error"):
                raise ValueError("Mock cases need text and reply/timeout/error behavior")
        telemetry_factory = None
        if args.telemetry or args.cgroup or args.policy:
            from spine.energy import RaplMeter
            from spine.resources import own_cgroup, read_snapshot
            from spine.telemetry import PressurePolicy, Telemetry
            cgroup = args.cgroup
            if cgroup is None:
                try:
                    cgroup = own_cgroup()
                except OSError:
                    cgroup = None
            policy = PressurePolicy(json.loads(args.policy.read_text())) if args.policy else None
            telemetry_factory = lambda bus, log: Telemetry(
                bus, log, read_snapshot=(lambda: read_snapshot(cgroup)) if cgroup else None,
                energy=RaplMeter(args.rapl_root), policy=policy)
        summary = ExperimentRunner(plan, args.output, mock_factory, MockDriver(), telemetry_factory).run()
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps(summary, indent=2))
    if summary["aborted"]:
        raise SystemExit(130 if summary["aborted"] == "interrupted" else 1)


if __name__ == "__main__":
    main()
