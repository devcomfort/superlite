#!/usr/bin/env bash
# Runner contract (bench/harness.py): cwd = temp copy of the run dir with this suite in $HIDDEN_DIR;
# write JUnit XML to $JUNIT. Node is already first on PATH.
npm install --no-audit --no-fund --silent >/dev/null 2>&1
npm run build --silent >/dev/null 2>&1
npx vitest run "$HIDDEN_DIR" --reporter=junit --outputFile="$JUNIT" >/dev/null 2>&1
exit 0
