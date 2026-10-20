# omp Tool Mapping

Skills speak in Claude Code's tool names. On Oh My Pi (omp) they resolve as follows.

| Skill says | omp equivalent |
|---|---|
| `Skill` (load a skill) | `read skill://<name>`; the user can also run `/skill:<name>` |
| `Agent` (dispatch an agent) | the `task` tool with `agent: "<name>"` (names below) |
| `model`, `effort` on `Agent` | pass `model` on the task item when it is allowed; otherwise the spawn falls back to the session model |
| `SendMessage` to a running agent | `write agent://<id>` |
| `AskUserQuestion` | the `ask` tool |
| Plan or todo list | the `todo` tool |
| `/superlite:<name>` | read `commands/<name>.md` from the plugin root and follow it |
| `Bash` / `PowerShell` | `bash` |
| `Read` / `Write` / `Edit` | `read` / `write` / `edit` |
| `Grep` / `Glob` | `grep` / `glob` |
| `WebFetch` / `WebSearch` | `read <url>` / `web_search` |
| `NotebookEdit` | `write` on the notebook file |

## Running superlite's agents

omp discovers this package's `agents/` directory as task agents: `implementer`, `implementer-haiku`, `package-reviewer`, `final-reviewer`, `fixer-sonnet`, `fixer-sonnet-high`, `fixer-opus`. Dispatch them by name; the agent definition already carries its brief.

- Give the shared plan, spec and global constraints in `context`, and the single task in `tasks[].task`. Every spawn starts fresh, so the two-message `READY` handshake from the Claude Code flow does not apply: send the plan and the task in the same call.
- A spawned agent is idle after it yields. Continue it with `write agent://<id>` instead of spawning again, and read its final report with `read agent://<id>`.
- The frontmatter tiers (`opus`, `sonnet`, `haiku`) are Claude Code model names. When they do not resolve against the configured providers, omp falls back to the session model; keep the tier in the prompt when it matters.
- `task` calls carry no `agent_id`, and omp has no subagent lifecycle hook. The Claude Code coordinator gates in `hooks/` are therefore inactive here (see below).

## Not ported

`hooks/` targets Claude Code's hook protocol (`PreToolUse`, `SubagentStop`, `UserPromptSubmit`). On omp only the session bootstrap runs, from `.omp/extensions/superlite.js`. Nothing mechanically enforces the following, so follow the skills yourself:

- The coordinator does not write project code while a run is active, and never writes `.superlite/orchestrator.json` or `.superlite/human-replies.jsonl` by hand; `bash $SUPERLITE/skills/subagent-driven-development/scripts/sl orchestrator ...` owns the first.
- No builds while the mode is `human` and `approved` is `false`.
- Run tests through `sl run_tests`, not by hand, so `rewrite-test-runs`' guarantee (focused fast runs, no full-suite runs from agents) still holds.
- Kill only processes you started, by PID. Never `pkill`, `killall`, `taskkill /IM` or `Stop-Process -Name`.

## Tools and paths

`$SUPERLITE` is the plugin root printed at the end of this bootstrap; run the tools with `bash`, never `python`:

```
bash $SUPERLITE/skills/subagent-driven-development/scripts/sl <tool> [args]
```

`bash` and `python3` are on PATH. Run `sl` from the project being built, not from the plugin root, because it resolves `.superlite/` against the working directory.
