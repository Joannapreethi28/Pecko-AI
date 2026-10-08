"""Generate repeat plans with shared seeded turn order and counterbalanced runs."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import random

from spine.experiment import validate_plan, write_json


def generate(template, output: Path, configurations, repeats=3, seed=42):
    validate_plan(template)
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be a positive integer")
    if not configurations or len(set(configurations)) != len(configurations):
        raise ValueError("Supply unique configuration labels")
    if any(not isinstance(c, str) or not c for c in configurations):
        raise ValueError("Configurations must be nonempty text")
    output.mkdir(parents=True, exist_ok=False)
    rng = random.Random(seed)
    schedule = []
    for repeat in range(repeats):
        cases = deepcopy(template["cases"])
        rng.shuffle(cases)
        # Shared request order within a repeat; rotate configuration execution
        # order to reduce systematic first/second-run effects.
        order = configurations[repeat % len(configurations):] + configurations[:repeat % len(configurations)]
        for position, name in enumerate(order):
            plan = deepcopy(template)
            plan.update(run_id=f"{template['run_id']}-r{repeat + 1}-c{configurations.index(name) + 1}",
                        configuration=name, cases=deepcopy(cases), repeat=repeat + 1, seed=seed)
            path = output / f"repeat-{repeat + 1}-configuration-{configurations.index(name) + 1}.json"
            write_json(path, plan)
            schedule.append({"repeat": repeat + 1, "position": position + 1,
                             "configuration": name, "plan": path.name})
    summary = {"seed": seed, "repeats": repeats, "configurations": configurations,
               "synthetic": template["synthetic"], "schedule": schedule,
               "note": "Labels do not implement a baseline. Bind each plan to its actual engine profile; preserve input and frozen conditions."}
    write_json(output / "schedule.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--configurations", nargs="+", default=["B0", "Pecko"])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        plan = json.loads(args.template.read_text(encoding="utf-8-sig"))
        for case in plan.get("cases", []):
            if "wav" in case:
                path = Path(case["wav"])
                case["wav"] = str((args.template.parent / path).resolve() if not path.is_absolute() else path)
        print(json.dumps(generate(plan, args.output, args.configurations, args.repeats, args.seed), indent=2))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
