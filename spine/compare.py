"""Complete paired-turn comparison with explicit condition/input checks."""

import argparse
import json
from pathlib import Path

from spine.report import finite, percentile


def index(report):
    rows = {}
    if not isinstance(report.get("turns"), list):
        raise ValueError("Report needs a turns list")
    for row in report["turns"]:
        key = row.get("case_id")
        if not isinstance(key, str) or not key or key in rows:
            raise ValueError("Each report needs unique case IDs")
        for field in ("timeout_s", "timeout_scored_latency_s"):
            finite(row.get(field), field, minimum=0)
        if row.get("observed_first_audio_s") is not None:
            finite(row["observed_first_audio_s"], "observed latency")
        rows[key] = row
    return rows


def compare_reports(baseline, candidate):
    for report in (baseline, candidate):
        if not isinstance(report.get("conditions", {}), dict):
            raise ValueError("Report conditions must be an object")
    left, right = index(baseline), index(candidate)
    issues = []
    if not left and not right:
        raise ValueError("Cannot compare empty runs")
    if baseline.get("platform") != candidate.get("platform"):
        issues.append("platform_mismatch")
    required = ("llm_id", "cpu_limit", "memory_limit", "input_set_id", "warmup")
    for field in required:
        first = baseline.get("conditions", {}).get(field)
        second = candidate.get("conditions", {}).get(field)
        if first is None or second is None:
            issues.append(f"missing_condition:{field}")
        elif first != second:
            issues.append(f"condition_mismatch:{field}")
    synthetic = baseline.get("synthetic") is not False or candidate.get("synthetic") is not False
    pairs = []
    for case_id in sorted(left.keys() | right.keys()):
        b, c = left.get(case_id), right.get(case_id)
        pair_issues = []
        observed_gain = scored_gain = None
        if b is None or c is None:
            pair_issues.append("missing_baseline_case" if b is None else "missing_candidate_case")
        else:
            if b["timeout_s"] != c["timeout_s"]:
                pair_issues.append("timeout_policy_mismatch")
            else:
                scored_gain = b["timeout_scored_latency_s"] - c["timeout_scored_latency_s"]
            if b.get("input_sha256") is None or c.get("input_sha256") is None:
                pair_issues.append("input_identity_unverified")
            elif b["input_sha256"] != c["input_sha256"]:
                pair_issues.append("input_mismatch")
            if b.get("observed_first_audio_s") is not None and c.get("observed_first_audio_s") is not None:
                observed_gain = b["observed_first_audio_s"] - c["observed_first_audio_s"]
        pairs.append({"case_id": case_id, "issues": pair_issues,
                      "baseline_success": None if b is None else b.get("success"),
                      "candidate_success": None if c is None else c.get("success"),
                      "observed_gain_s": observed_gain, "timeout_scored_gain_s": scored_gain,
                      "baseline_issues": None if b is None else b.get("issues"),
                      "candidate_issues": None if c is None else c.get("issues")})
    ready = (not synthetic and not issues and not any(p["issues"] for p in pairs)
             and baseline.get("headline_ready") is True and candidate.get("headline_ready") is True
             and all(p["baseline_success"] is True and p["candidate_success"] is True for p in pairs))
    measured = [p["observed_gain_s"] for p in pairs] if ready else []
    if ready and any(value is None for value in measured):
        ready, measured = False, []
    scores = [p["timeout_scored_gain_s"] for p in pairs]
    score_complete = (all(value is not None for value in scores) and not issues
                      and not any(p["issues"] for p in pairs))
    return {"baseline_run": baseline.get("run_id"), "candidate_run": candidate.get("run_id"),
            "synthetic": synthetic, "expected_pairs": len(pairs), "comparison_issues": issues,
            "measured_comparison_ready": ready,
            "measured_paired_gain_s": {"mean": sum(measured) / len(measured) if measured else None,
                                       "p50": percentile(measured, 0.5)},
            "latency_percentile_reduction_s": {
                key: baseline["headline_latency_s"][key] - candidate["headline_latency_s"][key] if ready else None
                for key in ("p50", "p90")},
            "timeout_scored_paired_gain_s": {"p50": percentile(scores, 0.5) if score_complete else None,
                                              "p90": percentile(scores, 0.9) if score_complete else None},
            "note": "Positive gain favors the candidate. Timeout scores are declared failure penalties, not observed latency. No unmatched cases are dropped.",
            "pairs": pairs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = compare_reports(json.loads(args.baseline.read_text(encoding="utf-8-sig")),
                                 json.loads(args.candidate.read_text(encoding="utf-8-sig")))
        rendered = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
        else:
            print(rendered, end="")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
