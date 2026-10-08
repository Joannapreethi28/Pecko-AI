"""Read-only Ubuntu handoff checks. Offline and audio verification remain explicit."""

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import platform
import sys

from spine.energy import RaplMeter
from spine.resources import effective_cpu_limit, own_cgroup, read_snapshot


def inspect(cgroup=None, models=(), expected_cpus=2, memory_gib=2):
    if expected_cpus <= 0 or memory_gib <= 0 or not all(math.isfinite(v) for v in (expected_cpus, memory_gib)):
        raise ValueError("Expected limits must be positive and finite")
    checks = [{"name": "Python 3.10+", "passed": sys.version_info >= (3, 10)}]
    checks.append({"name": "Linux runtime", "passed": sys.platform == "linux"})
    snap = None
    unavailable = None
    try:
        snap = read_snapshot(cgroup if cgroup is not None else own_cgroup())
        cpu = effective_cpu_limit(snap)
        checks.extend([
            {"name": "Declared CPU cap", "passed": cpu is not None and abs(cpu - expected_cpus) < 1e-6,
             "observed": cpu, "expected": expected_cpus},
            {"name": "Declared memory cap", "passed": snap.memory_max == int(memory_gib * 2**30),
             "observed": snap.memory_max, "expected": int(memory_gib * 2**30)},
            {"name": "Swap disabled", "passed": snap.swap_max == "0", "observed": snap.swap_max},
            {"name": "No OOM kills", "passed": snap.oom_kill == 0, "observed": snap.oom_kill},
        ])
    except (OSError, ValueError) as exc:
        unavailable = str(exc)
        checks.append({"name": "cgroup counters", "passed": False, "reason": unavailable})
    files = []
    for path in models:
        path = Path(path)
        present = path.is_file() and path.stat().st_size > 0
        files.append({"path": str(path.resolve()), "present": present,
                      "bytes": path.stat().st_size if present else None})
    checks.append({"name": "Declared local model files", "passed": bool(files) and all(f["present"] for f in files)})
    return {"platform": platform.platform(), "checks": checks,
            "automated_checks_passed": all(c["passed"] for c in checks),
            "judged_loop_ready": False,
            "snapshot": asdict(snap) if snap else None, "models": files,
            "rapl": RaplMeter().summary(), "unavailable": unavailable,
            "manual_gates": ["Declare VM/native host and hardware", "Verify external networking is off, localhost remains available",
                             "Verify CPU-only engine builds and model provenance", "Warm each stage and validate audible loop",
                             "Measure first sustained content audio and interruption with audio-path cross-check"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cgroup", type=Path)
    parser.add_argument("--model", type=Path, action="append", default=[])
    parser.add_argument("--expected-cpus", type=float, default=2)
    parser.add_argument("--memory-gib", type=float, default=2)
    args = parser.parse_args()
    try:
        report = inspect(args.cgroup, args.model, args.expected_cpus, args.memory_gib)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, allow_nan=False))
    if not report["automated_checks_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
