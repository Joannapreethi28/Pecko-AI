#!/usr/bin/env bash
# One-command live demo: Pecko under the 2 CPU / 2 GB / swap 0 cap + the live dashboard.
#   scripts/demo.sh            live mic (say "Hey Pecko, ...")
#   scripts/demo.sh --wav      fallback: plays the synthetic question WAVs at real-time speed
# Extra args go to spine.app (e.g. --half-duplex if the speaker echo makes Pecko interrupt itself).
# Ctrl+C stops both. The run folder is printed at the end.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="data/results/demo-$(date +%H%M%S)"
mkdir -p "$OUT"
if [[ "${1:-}" == "--wav" ]]; then
  shift
  SRC=(--wav data/clips/synthetic/q1.wav data/clips/synthetic/q2.wav data/clips/synthetic/q3.wav data/clips/synthetic/q4.wav)
else
  SRC=(--mic)
fi
scripts/run_pecko.sh "${SRC[@]}" --ears-tier 2 --out "$OUT" "$@" > "$OUT/pecko.stdout" 2>&1 &
PECKO=$!
trap 'kill $PECKO 2>/dev/null; wait $PECKO 2>/dev/null; echo; echo "run folder: $OUT"; python3 scripts/turn_report.py "$OUT" 2>/dev/null | tail -8' EXIT
echo "starting Pecko (models load ~10-20 s) -> $OUT"
until [[ -s "$OUT/events.jsonl" ]] && grep -q '"stage": "spine", "event": "ready"' "$OUT/events.jsonl"; do
  kill -0 $PECKO 2>/dev/null || { echo "Pecko exited during startup:"; tail -20 "$OUT/pecko.stdout"; exit 1; }
  sleep 0.5
done
echo "READY. Say: \"Hey Pecko, what is the capital of France?\""
sleep 1
.venv/bin/python -m spine.dashboard "$OUT/events.jsonl" --watch &
DASH=$!
wait $PECKO || true
kill $DASH 2>/dev/null || true
