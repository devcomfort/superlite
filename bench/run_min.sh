#!/usr/bin/env bash
# Minimal benchmark: both arms on one task, in parallel, Opus decision-maker playing the human.
# Usage (repo root): bash bench/run_min.sh <task> [rep]    e.g. bash bench/run_min.sh sitegen-core m1
set -uo pipefail
cd "$(dirname "$0")/.."
export BENCH_TASK="$1"; REP="${2:-m1}"
H="uv run --no-project python bench/harness.py"
for arm in superpowers superlite; do
  ( echo "=== $(date '+%H:%M') start $BENCH_TASK $arm $REP"
    $H run "$arm" "$REP" --human
    $H score "$arm" "$REP" > /dev/null
    echo "=== $(date '+%H:%M') done $BENCH_TASK $arm $REP" ) &
done
wait
$H report | tee "bench/results/table-$BENCH_TASK.md"
echo "ALL-DONE"
