#!/usr/bin/env bash
# Benchmark round 2: both arms, Opus decision-maker playing the human, 3 sequential reps with
# alternating arm order. Usage (repo root): bash bench/run_human.sh
set -uo pipefail
cd "$(dirname "$0")/.."
H="uv run --no-project python bench/harness.py"
RUNS="${BENCH_RUNS:-$(cd .. && pwd)/superlite-bench-runs}"

if ! claude auth status 2>/dev/null | grep -q '"loggedIn": true'; then
  echo "claude CLI is not logged in; run: claude auth login" >&2
  exit 3
fi

rm -rf "$RUNS"/*-smoke
for arm in superpowers superlite; do
  $H run "$arm" 0 --smoke
done

ORDER=("superpowers superlite" "superlite superpowers" "superpowers superlite")
for i in 1 2 3; do
  for arm in ${ORDER[$((i-1))]}; do
    echo "=== $(date '+%H:%M') start $arm h$i"
    $H run "$arm" "h$i" --human
    $H score "$arm" "h$i" > /dev/null
    echo "=== $(date '+%H:%M') done $arm h$i"
  done
done
$H report | tee bench/results/table-human.md
echo "ALL-DONE"
