"""Run paired repeated experiments on supplied profiles; preserve every run.

Configuration labels never implement B0. Real baseline engines must be supplied
by stage owners; two placeholder profiles exercise only the comparison plumbing.
"""

import argparse
from copy import deepcopy
from html import escape
import json
from pathlib import Path

from spine.compare import compare_reports
from spine.experiment import ExperimentRunner, write_json
from spine.runtime import make_factory, ReplayDriver
from spine.suite import generate
from spine.telemetry import Telemetry


def write_index(output, result):
    rows = []
    for run in result["runs"]:
        path = f"repeat-{run['repeat']}-{run['configuration']}/dashboard.html"
        link = f'<a href="{path}">View run</a>' if run["report"] else "No report artifact"
        status = escape(run["aborted"] or "Completed pipeline")
        rows.append(f'<tr><td>{run["repeat"]}</td><td>{escape(run["configuration"])}</td><td>{run["completed_cases"] if run["completed_cases"] is not None else "Unknown"}/{run["expected_cases"]}</td><td>{status}</td><td>{link}</td></tr>')
    mode = "SYNTHETIC · NO VOICE PERFORMANCE CLAIM" if result["synthetic"] else "RECORDED EXPERIMENT · VERIFY CONDITIONS"
    ready = "Ready for review" if result["measured_comparison_ready"] else "Unavailable: synthetic, incomplete or unmatched evidence"
    links = " ".join(f'<a href="{item["file"]}">Repeat {item["repeat"]} comparison</a>' for item in result["comparisons"] if "file" in item)
    html = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pecko · Paired experiment suite</title>
<style>:root{{color-scheme:dark;font-family:system-ui;background:#101820;color:#eef4f7}}body{{max-width:1000px;margin:40px auto;padding:0 24px}}h1{{font-size:38px}}.badge{{color:#f5cc76;font-size:12px;letter-spacing:1px}}.card{{padding:22px;background:#1a2833;border:1px solid #304451;border-radius:12px;margin:20px 0}}table{{width:100%;border-collapse:collapse}}td,th{{padding:14px 10px;text-align:left;border-bottom:1px solid #304451}}a{{color:#62c7c2;margin-right:16px}}.scroll{{overflow-x:auto}}footer{{color:#a6bac5;font-size:13px;margin-top:30px}}</style>
<div class="badge">{mode}</div><h1>Paired experiment suite</h1><p>Shared request order · alternating profile order · every declared run retained</p>
<section class="card"><b>{result["runs_recorded"]}/{result["expected_runs"]} runs recorded</b> · {result["repeats"]} repeats · {result["aborted_runs"]} aborted runs<p>Measured comparison: {ready}</p></section>
<section class="card scroll"><table><thead><tr><th>Repeat</th><th>Profile</th><th>Cases</th><th>Status</th><th>Review</th></tr></thead><tbody>{''.join(rows)}</tbody></table></section>
<section class="card">{links}</section><footer>Profile labels do not implement B0. Two placeholder profiles validate orchestration only. Positive measured gains require matching inputs, model and resource conditions, complete real audio, and compatible timeouts. Repeated recordings are not independent turns for cutoff-confidence claims.</footer></html>'''
    (output / "index.html").write_text(html, encoding="utf-8")


def run_batch(template, baseline_profile, candidate_profile, output: Path,
              *, repeats=3, seed=42, registry=None, telemetry_factory=None):
    if template.get("synthetic") != baseline_profile.get("synthetic") or template.get("synthetic") != candidate_profile.get("synthetic"):
        raise ValueError("Template and both profile synthetic declarations must match")
    factories = {"baseline": make_factory(baseline_profile, registry),
                 "candidate": make_factory(candidate_profile, registry)}
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "baseline-profile.json", baseline_profile)
    write_json(output / "candidate-profile.json", candidate_profile)
    schedule = generate(template, output / "plans", ["baseline", "candidate"], repeats, seed)
    outcomes = []
    reports = {}
    for position, item in enumerate(schedule["schedule"]):
        label, repeat = item["configuration"], item["repeat"]
        plan = json.loads((output / "plans" / item["plan"]).read_text(encoding="utf-8"))
        run_output = output / f"repeat-{repeat}-{label}"
        try:
            summary = ExperimentRunner(plan, run_output, factories[label], ReplayDriver(), telemetry_factory).run()
            report = json.loads((run_output / "report.json").read_text(encoding="utf-8"))
            reports[repeat, label] = report
            outcomes.append({**item, "aborted": summary["aborted"],
                             "completed_cases": summary["completed_cases"], "expected_cases": summary["expected_cases"],
                             "report": str(run_output.relative_to(output) / "report.json")})
        except Exception as exc:
            # Preserve the declared run in the suite even if artifact creation
            # itself failed. No zero-latency replacement is manufactured.
            outcomes.append({**item, "aborted": f"{type(exc).__name__}: {exc}",
                             "completed_cases": None, "expected_cases": len(plan["cases"]), "report": None})
        write_json(output / "batch-progress.json", {"runs": outcomes, "expected_runs": len(schedule["schedule"])})
        if outcomes[-1]["aborted"] == "interrupted":
            for remaining in schedule["schedule"][position + 1:]:
                outcomes.append({**remaining, "aborted": "not started after interruption", "not_started": True,
                                 "completed_cases": None, "expected_cases": len(template["cases"]), "report": None})
            write_json(output / "batch-progress.json", {"runs": outcomes, "expected_runs": len(schedule["schedule"])})
            break
    comparisons = []
    for repeat in range(1, repeats + 1):
        b, c = reports.get((repeat, "baseline")), reports.get((repeat, "candidate"))
        if b is None or c is None:
            comparisons.append({"repeat": repeat, "measured_comparison_ready": False,
                                "error": "Missing baseline or candidate report"})
            continue
        comparison = compare_reports(b, c)
        filename = f"comparison-repeat-{repeat}.json"
        write_json(output / filename, comparison)
        comparisons.append({"repeat": repeat, "measured_comparison_ready": comparison["measured_comparison_ready"],
                            "file": filename, "expected_pairs": comparison["expected_pairs"]})
    result = {"synthetic": template["synthetic"], "seed": seed, "repeats": repeats,
              "expected_runs": len(schedule["schedule"]), "runs_recorded": len(outcomes),
              "aborted_runs": sum(r["aborted"] is not None and not r.get("not_started", False) for r in outcomes),
              "not_started_runs": sum(r.get("not_started", False) for r in outcomes),
              "interrupted": any(r["aborted"] == "interrupted" for r in outcomes),
              "measured_comparison_ready": all(r["measured_comparison_ready"] for r in comparisons),
              "runs": outcomes, "comparisons": comparisons,
              "independence_note": "Repeated recordings are not independent speakers/turns for cutoff-confidence claims."}
    write_json(output / "batch-summary.json", result)
    write_index(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--baseline-profile", required=True, type=Path)
    parser.add_argument("--candidate-profile", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        template = json.loads(args.template.read_text(encoding="utf-8-sig"))
        for case in template.get("cases", []):
            if "wav" in case:
                path = Path(case["wav"])
                case["wav"] = str((args.template.parent / path).resolve() if not path.is_absolute() else path)
        baseline = json.loads(args.baseline_profile.read_text(encoding="utf-8-sig"))
        candidate = json.loads(args.candidate_profile.read_text(encoding="utf-8-sig"))
        result = run_batch(template, baseline, candidate, args.output, repeats=args.repeats, seed=args.seed,
                           telemetry_factory=lambda bus, log: Telemetry(bus, log))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(json.dumps({key: result[key] for key in ("synthetic", "expected_runs", "runs_recorded", "aborted_runs", "measured_comparison_ready")}, indent=2))
    if result["aborted_runs"]:
        raise SystemExit(130 if result["interrupted"] else 1)


if __name__ == "__main__":
    main()
