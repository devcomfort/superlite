#!/usr/bin/env bash
# Runner contract (bench/harness.py): cwd = temp copy of the run dir with this suite in $HIDDEN_DIR;
# write JUnit XML to $JUNIT. Node is already first on PATH.
npm install --no-audit --no-fund --silent >/dev/null 2>&1
npm run build --silent >/dev/null 2>&1
# Own config: the project's vitest config may only include its own tests/ directory.
cat > "$HIDDEN_DIR/vitest.hidden.config.mjs" <<EOF
export default { test: { include: ["$HIDDEN_DIR/**/*.test.ts"], exclude: ["**/node_modules/**"] } };
EOF
npx vitest run --config "$HIDDEN_DIR/vitest.hidden.config.mjs" --reporter=junit --outputFile="$JUNIT" >/dev/null 2>&1
exit 0
