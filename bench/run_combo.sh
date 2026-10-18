#!/usr/bin/env bash
# Combined sitegen+minisheet benchmark. Opus decider plays the human.
# Default: 3 reps one after another; within a rep the arms run in parallel (same moment, same
# rate-limit pressure).
#   ARMS="superlite"  run only these arms (default "superpowers superlite")
#   REPS_PARALLEL=1   start every rep at once instead of one rep at a time
# Usage (repo root): [ARMS=...] [REPS_PARALLEL=1] bash bench/run_combo.sh [rep-prefix]
set -uo pipefail
cd "$(dirname "$0")/.."
export BENCH_TASK=combo BENCH_BUDGET="${BENCH_BUDGET:-40}"
P="${1:-c}"
ARMS="${ARMS:-superpowers superlite}"
H="uv run --no-project python bench/harness.py"
one() {
  echo "=== $(date '+%H:%M') start $1 $2"
  $H run "$1" "$2" --human
  $H score "$1" "$2" > /dev/null
  echo "=== $(date '+%H:%M') done $1 $2"
}
for i in 1 2 3; do
  for arm in $ARMS; do one "$arm" "$P$i" & done
  [ "${REPS_PARALLEL:-0}" = 1 ] || wait
done
wait
$H report | tee "bench/results/table-combo-$P.md"
echo "ALL-DONE"
