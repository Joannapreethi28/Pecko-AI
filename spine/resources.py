"""Read-only cgroup v2 snapshots and accounting; fixtures work on any host.

Run python -m spine.resources from inside the capped scope on Ubuntu.
This module reports enforced values; it does not change limits or poll playback.
"""

import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import sys

from common.clock import now


def counters(text: str) -> dict[str, int]:
    return {key: int(value) for key, value in (line.split() for line in text.splitlines())}


def psi_some(text: str) -> int:
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == "some":
            values = dict(item.split("=", 1) for item in parts[1:])
            return int(values["total"])
    raise ValueError("No PSI some total")


def cpuset_count(text: str) -> int:
    ids = set()
    for part in text.strip().split(","):
        if not part:
            continue
        ends = part.split("-")
        start = int(ends[0])
        stop = int(ends[-1])
        if start < 0 or stop < start:
            raise ValueError("Invalid cpuset")
        ids.update(range(start, stop + 1))
    return len(ids)


@dataclass(frozen=True)
class Snapshot:
    path: str
    t: float
    cpu_usage_usec: int | None
    cpu_max: str | None
    cpuset: str | None
    memory_current: int | None
    memory_peak: int | None
    memory_max: int | None
    memory_limit_unbounded: bool | None
    swap_max: str | None
    psi_some_usec: int | None
    oom_kill: int | None
    unavailable: tuple[str, ...]

    @property
    def regime(self):
        return self.cpu_max, self.cpuset, self.memory_max, self.memory_limit_unbounded, self.swap_max


def read_snapshot(path: Path, *, t: float | None = None) -> Snapshot:
    errors = []

    def read(name, parse=lambda text: text.strip()):
        try:
            return parse((path / name).read_text(encoding="ascii"))
        except (OSError, ValueError, KeyError) as exc:
            errors.append(f"{name}: {type(exc).__name__}")
            return None

    stat = read("cpu.stat", counters)
    events = read("memory.events", counters)
    limit = read("memory.max")
    try:
        memory_max = None if limit in (None, "max") else int(limit)
    except ValueError:
        errors.append("memory.max: ValueError")
        memory_max = None
        limit = None
    cpu_max = read("cpu.max")
    cpuset = read("cpuset.cpus.effective")
    current = read("memory.current", int)
    peak = read("memory.peak", int)
    swap = read("memory.swap.max")
    psi = read("cpu.pressure", psi_some)
    return Snapshot(str(path.resolve()), now() if t is None else t,
                    None if stat is None else stat.get("usage_usec"), cpu_max, cpuset,
                    current, peak, memory_max, None if limit is None else limit == "max",
                    swap, psi, None if events is None else events.get("oom_kill"), tuple(errors))


def effective_cpu_limit(snapshot: Snapshot) -> float | None:
    if snapshot.cpu_max is None or snapshot.cpuset is None:
        return None
    quota, period = snapshot.cpu_max.split()
    count = cpuset_count(snapshot.cpuset)
    if count == 0:
        return None
    if quota == "max":
        return float(count)
    if int(period) <= 0 or int(quota) <= 0:
        raise ValueError("Invalid CPU quota")
    return min(float(count), int(quota) / int(period))


def usage_delta(before: Snapshot, after: Snapshot) -> dict:
    if before.path != after.path:
        raise ValueError("Cannot compare different cgroups")
    elapsed = after.t - before.t
    if elapsed <= 0:
        raise ValueError("Snapshots need increasing timestamps")
    changed = before.regime != after.regime

    def delta(first, last):
        return None if first is None or last is None or last < first else last - first

    usage = delta(before.cpu_usage_usec, after.cpu_usage_usec)
    # A changed cap starts a fresh pressure window; old history is incomparable.
    psi = None if changed else delta(before.psi_some_usec, after.psi_some_usec)
    return {"wall_s": elapsed, "regime_changed": changed,
            "cpu_s": None if usage is None else usage / 1e6,
            "mean_cores": None if usage is None else usage / 1e6 / elapsed,
            "cpu_psi_some_fraction": None if psi is None else psi / 1e6 / elapsed,
            "oom_kill_delta": delta(before.oom_kill, after.oom_kill),
            "memory_peak_bytes": after.memory_peak}


def rapl_delta_j(before_uj: int, after_uj: int, max_range_uj: int) -> float:
    """One counter interval, assuming fewer than one full wrap between samples.

    Sample each package domain separately. Do not add package plus its core
    subdomain. The returned energy is whole-package, not cgroup-specific.
    """
    if max_range_uj <= 0 or not (0 <= before_uj < max_range_uj and 0 <= after_uj < max_range_uj):
        raise ValueError("Invalid RAPL counter/range")
    return ((after_uj - before_uj) % max_range_uj) / 1e6


def energy_summary(gross_j: float, wall_s: float, turns: int,
                   successful_turns: int, idle_watts: float | None = None) -> dict:
    values = [gross_j, wall_s] + ([] if idle_watts is None else [idle_watts])
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError("Energy values must be finite numbers")
    if type(turns) is not int or type(successful_turns) is not int:
        raise ValueError("Turn counts must be integers")
    if gross_j < 0 or wall_s <= 0 or turns <= 0 or not (0 <= successful_turns <= turns):
        raise ValueError("Invalid energy accounting inputs")
    if idle_watts is not None and idle_watts < 0:
        raise ValueError("Idle power cannot be negative")
    adjusted = None if idle_watts is None else gross_j - idle_watts * wall_s
    # Preserve negative net energy as evidence of noise/mismatched idle conditions.
    return {"gross_j_per_turn": gross_j / turns,
            "idle_adjusted_j_per_turn": None if adjusted is None else adjusted / turns,
            "successful_turns_per_gross_j": None if gross_j == 0 else successful_turns / gross_j}


def own_cgroup() -> Path:
    if sys.platform != "linux":
        raise OSError("cgroup readings require Linux; Windows has no cgroup counters")
    for line in Path("/proc/self/cgroup").read_text().splitlines():
        if line.startswith("0::"):
            relative = line[3:].lstrip("/")
            if ".." in Path(relative).parts:
                raise OSError("Unexpected cgroup namespace path; pass --cgroup explicitly")
            return Path("/sys/fs/cgroup") / relative
    raise OSError("Unified cgroup v2 not found")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cgroup", type=Path, help="Explicit cgroup path; defaults to this process")
    args = parser.parse_args()
    try:
        snapshot = read_snapshot(args.cgroup if args.cgroup is not None else own_cgroup())
        report = asdict(snapshot)
        report["effective_cpu_limit"] = effective_cpu_limit(snapshot)
        report["energy_j"] = None
        report["energy_note"] = "No package energy sampler attached; CPU-seconds are not joules."
    except (OSError, ValueError) as exc:
        report = {"available": False, "reason": str(exc)}
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
