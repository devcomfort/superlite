# Hooks

`hooks/hooks.json` registers these. The run hooks are active only while a run marker exists (`.superlite/stable.json`, `prime.md` or `pool.json`, written by the first lint). They fail open on bad input.

- `session-start`: injects `using-superlite` at startup, clear and compact.
- `block-unsafe-kill`: always on for Bash and PowerShell; blocks killing processes by name or pattern (`taskkill /IM`, `pkill`, `killall`, `Stop-Process -Name`). Kill by PID is allowed.
- `block-coordinator-edits`: during a run, blocks the coordinator (calls without `agent_id`) from writing project code. It may write `docs/plans/**`, `SPEC*.md`, `docs/**/*.md` and `.superlite/**`. Subagents always pass.
- `rewrite-test-runs`: during a run, rewrites the coordinator's raw test commands (pytest, npm test, go test, cargo test, dotnet test, ...) into a background `sl run_tests --full`, and logs a `rule-rewrite` incident.
- `capture-agent-launch`: during a run, appends a `launch` record (agent id, type, model, description) to `.superlite/metrics.jsonl` after each `Agent` call.
- `capture-agent-stop`: during a run, appends a `stop` record (agent id, type, transcript path, last message) to `.superlite/metrics.jsonl` when a subagent stops.
