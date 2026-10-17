#!/usr/bin/env bash
# Combined sitegen+minisheet benchmark: 3 sequential reps, alternating arm order, Opus decider.
# Usage (repo root): bash bench/run_combo.sh [rep-prefix]    e.g. bash bench/run_combo.sh e10
set -uo pipefail
cd "$(dirname "$0")/.."
export BENCH_TASK=combo BENCH_BUDGET="${BENCH_BUDGET:-40}"
P="${1:-c}"
H="uv run --no-project python bench/harness.py"
ORDER=("superpowers superlite" "superlite superpowers" "superpowers superlite")
for i in 1 2 3; do
  for arm in ${ORDER[$((i-1))]}; do
    echo "=== $(date '+%H:%M') start $arm $P$i"
    $H run "$arm" "$P$i" --human
    $H score "$arm" "$P$i" > /dev/null
    echo "=== $(date '+%H:%M') done $arm $P$i"
  done
done
$H report | tee "bench/results/table-combo-$P.md"
echo "ALL-DONE"
