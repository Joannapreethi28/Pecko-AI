"""Offline turn-report harness. Ground truth comes from an experiment manifest.

Run: python -m spine.report events.jsonl --manifest experiment.json
Logs and manifests are data. Neither can supply executable callbacks.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Iterable


def finite(value, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    if not math.isfinite(value) or (minimum is not None and value < minimum):
        raise ValueError(f"Invalid {name}: {value}")
    return float(value)


def percentile(values: list[float], fraction: float) -> float | None:
    """Linear interpolation, position=(n-1)*fraction; defined for n=1."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    left = int(position)
    right = min(left + 1, len(ordered) - 1)
    return ordered[left] + (ordered[right] - ordered[left]) * (position - left)


def load_events(path: Path) -> list[dict]:
    events = []
    with path.open(encoding="utf-8-sig") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                validate_event(event)
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"{path}:{number}: {exc}") from exc
            events.append(event)
    return events


def validate_event(event: dict) -> None:
    if not isinstance(event, dict):
        raise ValueError("Expected an event object")
    for field in ("stage", "event"):
        if not isinstance(event.get(field), str):
            raise ValueError(f"Missing string {field}")
    finite(event.get("t"), "event time", minimum=0)
    turn = event.get("turn")
    if turn is not None and (type(turn) is not int or turn < 0):
        raise ValueError("Invalid event turn")
    if not isinstance(event.get("extra", {}), dict):
        raise ValueError("event extra must be an object")
    for field in ("gen", "seq"):
        value = event.get("extra", {}).get(field)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"Invalid event {field}")


def validate_manifest(manifest: dict) -> None:
    if not isinstance(manifest, dict) or not isinstance(manifest.get("turns"), list):
        raise ValueError("Manifest needs a turns list")
    if not manifest["turns"]:
        raise ValueError("Manifest must contain expected turns")
    if type(manifest.get("synthetic")) is not bool:
        raise ValueError("Manifest must declare synthetic true/false")
    for field in ("run_id", "platform", "configuration"):
        if not isinstance(manifest.get(field), str) or not manifest[field]:
            raise ValueError(f"Manifest needs {field}")
    seen = set()
    for row in manifest["turns"]:
        turn = row.get("turn")
        if type(turn) is not int or turn < 0 or turn in seen:
            raise ValueError("Expected unique nonnegative turn IDs")
        seen.add(turn)
        if not isinstance(row.get("case_id"), str) or not row["case_id"]:
            raise ValueError("Each turn needs a case_id for paired comparisons")
        if row.get("t_eos") is None:
            if row.get("not_started") is not True:
                raise ValueError("Missing t_eos requires explicit not_started:true")
        else:
            finite(row["t_eos"], "labelled t_eos", minimum=0)
        if finite(row.get("timeout_s"), "timeout_s", minimum=0) == 0:
            raise ValueError("timeout_s must be positive")


def first(events: list[dict], stage: str, name: str) -> dict | None:
    matches = [e for e in events if e["stage"] == stage and e["event"] == name]
    return min(matches, key=lambda e: e["t"]) if matches else None


def turn_report(row: dict, events: list[dict]) -> dict:
    eos = row["t_eos"]
    issues = []
    if eos is None:
        issues.append("missing_labelled_eos")
    ends = [e for e in events if e["stage"] == "spine" and e["event"] == "turn_end"]
    end = max(ends, key=lambda e: e["t"]) if ends else None
    if len(ends) > 1:
        issues.append("multiple_turn_end_events")
    if end is None:
        issues.append("missing_turn_end")
    elif type(end.get("extra", {}).get("success")) is not bool:
        issues.append("missing_success_status")
    elif not end["extra"]["success"]:
        issues.append("turn_failed")

    # Headline requires the audio adapter to identify real sustained content.
    audio_events = [e for e in events if e["stage"] == "voice"
                    and e["event"] == "first_audio_out"
                    and e.get("extra", {}).get("content") is True
                    and e.get("extra", {}).get("sustained") is True]
    audio = min(audio_events, key=lambda e: e["t"]) if audio_events else None
    if audio is None:
        issues.append("missing_sustained_content_audio")
    latency = None if audio is None or eos is None else audio["t"] - eos
    if latency is not None and latency < 0:
        issues.append("audio_before_labelled_eos")
    if latency is not None and latency > row["timeout_s"]:
        issues.append("deadline_exceeded")
    if end is not None and audio is not None and end["t"] < audio["t"]:
        issues.append("turn_end_before_audio")

    gen = audio.get("extra", {}).get("gen") if audio else None
    commits = [e for e in events if e["stage"] == "spine" and e["event"] == "commit"]
    if gen is None and commits:
        generations = {e.get("extra", {}).get("gen") for e in commits}
        if len(generations) == 1 and None not in generations:
            gen = next(iter(generations))
        else:
            issues.append("ambiguous_audio_generation")
    matched_commits = [e for e in commits if e.get("extra", {}).get("gen") == gen]
    commit = min(matched_commits, key=lambda e: e["t"]) if matched_commits else None
    pcm_events = [e for e in events if e["stage"] == "voice" and e["event"] == "pcm_ready"
                  and e.get("extra", {}).get("seq") == 0
                  and e.get("extra", {}).get("gen") == gen]
    pcm = min(pcm_events, key=lambda e: e["t"]) if pcm_events else None
    if commits and audio is not None and commit is None:
        issues.append("audio_generation_not_committed")
    residual = None
    if audio and commit and pcm:
        residual = audio["t"] - max(commit["t"], pcm["t"])
        if residual < -1e-9:
            issues.append("audio_before_commit_or_pcm")

    gap = end.get("extra", {}).get("gap_s") if end else None
    if gap is not None:
        gap = finite(gap, "complete turn gap_s", minimum=0)
    success = not issues
    timestamps = {}
    for stage, name in (("ears", "endpoint"), ("ears", "asr_final"),
                        ("brain", "prompt_ready"), ("brain", "first_token"),
                        ("brain", "first_chunk")):
        relevant = [e for e in events if stage != "brain" or
                    e.get("extra", {}).get("gen") == gen or
                    ("gen" not in e.get("extra", {}) and len(commits) <= 1)]
        event = first(relevant, stage, name)
        timestamps[name + "_s"] = None if event is None or eos is None else event["t"] - eos
    # This is declared failure scoring, NOT an observed latency for missing audio.
    scored = latency if success else max(row["timeout_s"], latency or 0)
    return {"turn": row["turn"], "case_id": row["case_id"], "success": success,
            "issues": issues, "failure_reason": end.get("extra", {}).get("reason") if end else None,
            "observed_first_audio_s": latency, "timeout_scored_latency_s": scored,
            "commit_s": None if commit is None or eos is None else commit["t"] - eos,
            "pcm_ready_s": None if pcm is None or eos is None else pcm["t"] - eos,
            "limiting_dependency": None if not (commit and pcm) else
                ("commit" if commit["t"] > pcm["t"] else
                 "answer_ready" if pcm["t"] > commit["t"] else "tie"),
            "device_and_dispatch_s": residual, "gap_s": gap,
            "generation": gen, "timeline": timestamps}


def build_report(manifest: dict, events: Iterable[dict]) -> dict:
    validate_manifest(manifest)
    events = list(events)
    for event in events:
        validate_event(event)
    expected = {r["turn"] for r in manifest["turns"]}
    unexpected = sorted({e["turn"] for e in events if e.get("turn") is not None} - expected)
    grouped = {turn: [] for turn in expected}
    for event in events:
        if event.get("turn") in grouped:
            grouped[event["turn"]].append(event)
    turns = [turn_report(row, grouped[row["turn"]]) for row in manifest["turns"]]
    synthetic = manifest["synthetic"] or any(
        e["event"] == "mock_run" or e.get("extra", {}).get("synthetic") is True for e in events)
    failures = sum(not r["success"] for r in turns)
    run_issues = [e["event"] for e in events if e["event"] in ("run_abort", "stop_error", "telemetry_error")]
    complete_audio = [r["observed_first_audio_s"] for r in turns]
    headline_ready = not synthetic and not failures and not unexpected and not run_issues
    scored = [r["timeout_scored_latency_s"] for r in turns]
    gaps = [r["gap_s"] for r in turns if r["gap_s"] is not None]
    return {
        "run_id": manifest["run_id"], "platform": manifest["platform"],
        "configuration": manifest["configuration"], "synthetic": synthetic,
        "expected_turns": len(turns), "successful_turns": len(turns) - failures,
        "failed_or_incomplete_turns": failures, "unexpected_turns": unexpected,
        "headline_ready": headline_ready,
        "run_issues": run_issues,
        "verification_note": "Log completeness only; labels, sustained-content flags, caps and quality require independent verification.",
        "headline_latency_s": {"p50": percentile(complete_audio, 0.5) if headline_ready else None,
                               "p90": percentile(complete_audio, 0.9) if headline_ready else None},
        "timeout_scored_latency_s": {"p50": percentile(scored, 0.5),
                                     "p90": percentile(scored, 0.9)},
        "scoring_note": "Failed/missing turns score max(declared timeout, observed latency); not measured latency.",
        "gap_s": {"known_turns": len(gaps), "total": sum(gaps) if gaps else None},
        "critical_path_counts": {name: sum(r["limiting_dependency"] == name for r in turns)
                                 for name in ("commit", "answer_ready", "tie")},
        "percentile_method": "linear interpolation at (n-1)*q",
        "turns": turns,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
        report = build_report(manifest, load_events(args.events))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
