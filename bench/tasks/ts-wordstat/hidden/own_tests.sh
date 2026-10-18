#!/usr/bin/env bash
# Own-test runner: cwd = the run dir itself (node_modules may already exist); write JUnit to $JUNIT.
[ -d node_modules ] || npm install --no-audit --no-fund --silent >/dev/null 2>&1
npx vitest run --exclude "hidden_tests/**" --exclude "node_modules/**" --reporter=junit --outputFile="$JUNIT" >/dev/null 2>&1
exit 0
