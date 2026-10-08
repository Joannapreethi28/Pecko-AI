"""Ubuntu systemd/cgroup launcher. Dry-run is portable; enforcement is Linux-only."""

import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys


def build_command(python: str, cpus: str, quota: int, memory: str,
                  command: list[str]) -> list[str]:
    if quota <= 0:
        raise ValueError("CPU quota must be positive")
    return ["systemd-run", "--scope", "--unit=pecko",
            "-p", f"AllowedCPUs={cpus}", "-p", f"CPUQuota={quota}%",
            "-p", f"MemoryMax={memory}", "-p", "MemorySwapMax=0",
            "--", python, *command]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpus", required=True, help="Available logical CPUs, e.g. 0,1")
    parser.add_argument("--quota", type=int, default=200)
    parser.add_argument("--memory", default="2G")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="Python arguments after --; defaults to -m spine.mock")
    args = parser.parse_args()
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    invocation = build_command(sys.executable, args.cpus, args.quota,
                               args.memory, command or ["-m", "spine.mock"])
    if args.dry_run:
        print(shlex.join(invocation))
        return
    if sys.platform != "linux":
        parser.error("Enforcement requires native Linux; use --dry-run here")
    if not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
        parser.error("Unified cgroup v2 is required")
    env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
    # Cache flags prevent model downloads; they do NOT enforce network isolation.
    print("Network isolation is separate: disable networking before measurement.",
          file=sys.stderr)
    raise SystemExit(subprocess.call(invocation, env=env,
                                    cwd=Path(__file__).resolve().parents[1]))


if __name__ == "__main__":
    main()
