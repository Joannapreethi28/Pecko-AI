#!/usr/bin/env bash
# End-to-end leave-one-out ablation on the 24 synthetic WAVs, same cap as run_pecko.sh (2 CPU, 2 GB, swap 0).
# Each config is ONE run of 24 turns, run sequentially, then compared against the B0 baseline.
#   scripts/run_ablation_e2e.sh            # all configs
#   scripts/run_ablation_e2e.sh no-router  # just some
set -euo pipefail
cd "$(dirname "$0")/.."
export PECKO_CPUS="${PECKO_CPUS:-2,3}"
B0=data/results/baseline-syn24-b0
[[ -f data/clips/synthetic24/q01.wav ]] || .venv/bin/python scripts/make_question_set.py
declare -A FLAGS=(
  [full]=""
  [no-hold]="--no-hold"
  [no-early-prefill]="--no-early-prefill"
  [no-cache-prompt]="--no-cache-prompt"
  [no-router]="--no-router"
  [fixed800]="--endpointer fixed_800"
)
ORDER=(full no-hold no-early-prefill no-cache-prompt no-router fixed800)
(( $# )) && ORDER=("$@")
for name in "${ORDER[@]}"; do
  out=data/results/ablation-e2e-$name
  echo "=== $name: ${FLAGS[$name]}" >&2
  # shellcheck disable=SC2086
  scripts/run_pecko.sh --wav data/clips/synthetic24/q*.wav --ears-tier 2 --no-audio ${FLAGS[$name]} --out "$out"
  .venv/bin/python scripts/compare_runs.py "$out" "$B0" | tail -8
done
