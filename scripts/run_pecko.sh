#!/usr/bin/env bash
# Run the full Pecko loop under the declared cap: 2 logical CPUs, 2 GB RAM, swap 0.
#   scripts/run_pecko.sh --mic
#   scripts/run_pecko.sh --wav data/clips/q1.wav --no-wake
# Env: PECKO_CPUS (default 0,1), PECKO_MEM (default 2G), PECKO_SUDO=1 to use the system scope
# with AllowedCPUs (needs sudo); default is a user scope + taskset (no sudo needed).
set -euo pipefail
cd "$(dirname "$0")/.."
CPUS="${PECKO_CPUS:-0,1}"; MEM="${PECKO_MEM:-2G}"
NCPU=$(( $(tr ',' '\n' <<<"$CPUS" | wc -l) ))
QUOTA="$(( NCPU * 100 ))%"
UNIT="pecko-$(date +%H%M%S)"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
echo "cap: CPUs $CPUS (quota $QUOTA), memory $MEM, swap 0  -> unit $UNIT" >&2
echo "show it live: systemd-cgtop  |  cat /sys/fs/cgroup/.../$UNIT.scope/{cpu.max,memory.max,memory.peak}" >&2
if [[ "${PECKO_SUDO:-0}" == 1 ]]; then
  exec sudo systemd-run --scope --unit="$UNIT" -p AllowedCPUs="$CPUS" -p CPUQuota="$QUOTA" \
    -p MemoryMax="$MEM" -p MemorySwapMax=0 --setenv=HF_HUB_OFFLINE=1 \
    -- .venv/bin/python -m spine.app "$@"
fi
exec systemd-run --user --scope --unit="$UNIT" -p CPUQuota="$QUOTA" -p MemoryMax="$MEM" -p MemorySwapMax=0 \
  -- taskset -c "$CPUS" .venv/bin/python -m spine.app "$@"
