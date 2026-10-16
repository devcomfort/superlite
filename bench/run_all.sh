#!/usr/bin/env bash
# Run the full benchmark: smoke-check both arms, then each arm in sequence, then score.
# Usage: bash bench/run_all.sh [rep]   (from the repo root)
set -uo pipefail
cd "$(dirname "$0")/.."
REP="${1:-1}"
H="uv run --no-project python bench/harness.py"
RUNS="${BENCH_RUNS:-$(cd .. && pwd)/superlite-bench-runs}"

if ! claude auth status 2>/dev/null | grep -q '"loggedIn": true'; then
  echo "claude CLI is not logged in; run: claude auth login" >&2
  exit 3
fi

rm -rf "$RUNS"/*-smoke
for arm in superpowers superlite; do
  $H run "$arm" 0 --smoke
  if ! uv run --no-project python -c "
import json,sys
r=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8') if l.startswith('{') and '\"type\":\"result\"' in l.replace(' ','')]
sys.exit(0 if r and 'BENCHMARK-COMPLETE' in (r[-1].get('result') or '') else 1)" "bench/results/$arm-0-smoke.jsonl"; then
    echo "smoke failed for $arm; see bench/results/$arm-0-smoke.jsonl" >&2
    exit 4
  fi
done

for arm in superpowers superlite; do
  $H run "$arm" "$REP"
  $H score "$arm" "$REP"
done
$H report | tee "bench/results/table-rep$REP.md"
echo "ALL-DONE"
