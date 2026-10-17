#!/usr/bin/env bash
# Combined sitegen+minisheet benchmark: 3 reps one after another; within a rep both arms run in
# parallel (same moment, same rate-limit pressure). Opus decider plays the human.
# Usage (repo root): bash bench/run_combo.sh [rep-prefix]    e.g. bash bench/run_combo.sh e
set -uo pipefail
cd "$(dirname "$0")/.."
export BENCH_TASK=combo BENCH_BUDGET="${BENCH_BUDGET:-40}"
P="${1:-c}"
H="uv run --no-project python bench/harness.py"
for i in 1 2 3; do
  for arm in superpowers superlite; do
    ( echo "=== $(date '+%H:%M') start $arm $P$i"
      $H run "$arm" "$P$i" --human
      $H score "$arm" "$P$i" > /dev/null
      echo "=== $(date '+%H:%M') done $arm $P$i" ) &
  done
  wait
done
$H report | tee "bench/results/table-combo-$P.md"
echo "ALL-DONE"
