# How the rules are enforced

Instructions drift. Scripts and hooks do not. These gates run on every build:

| Gate | What it enforces | How |
|---|---|---|
| **The coordinator cannot write code** | Every change goes to a fix-only or implementer agent, by tier; the block message says which | `block-coordinator-edits` hook |
| **No unsafe kills** | No `pkill` or `taskkill /IM`; only PIDs the run started | `block-unsafe-kill` hook |
| **Tests never block the coordinator** | A raw `pytest`, `npm test`, `go test` and so on is rewritten into a background `sl run_tests` | `rewrite-test-runs` hook |
| **A plan must lint before work starts** | Stable tasks dispatch at once; others wait with a reason. Size band, frozen interfaces, and chain rulings that must carry the id lint printed | `lint --stable` |
| **Same plan, same agents** | Task features pick the agent tier from `routing.json`; Haiku only for mechanical tasks off the critical path, never for fixes | `routing.py` |
| **Agents stay in their tier** | A task goes only to an idle agent of its own tier; nothing queues behind a busy one | `dispatch` |
| **Cost caps are enforced** | Warns at 70% of the cap; over the cap it stops optional work | `sl budget` |
| **Every run is measured** | Each agent's tokens, cost and time are captured automatically and feed the next run's predictions | capture hooks, `~/.superlite/history.jsonl` |
| **No agent spawns agents** | Subagents get explicit tool lists with no `Agent` | agent definitions |

---
