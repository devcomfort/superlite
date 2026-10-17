# superlite

A Claude Code plugin that keeps the structure of [superpowers](https://github.com/obra/superpowers) (plugin layout, SessionStart hook, core lifecycle skills) with far less process, so the default flow is much faster at similar quality.

## Why

Profiling superpowers 6.4.1 showed where the time and money go:

- 8-12 human gates per feature (one question per message, section-by-section approvals).
- Plans that contain full code for every task, which a second model then transcribes.
- Strictly sequential subagent execution with per-task reviews and long fix loops.
- The full test suite re-run by several skills.
- About 3KB injected at session start.

Superlite uses one approval gate, plans that carry contracts instead of code, parallel waves, one review per wave, one test run per wave, and short reports. The session hook injects about 1KB.

## Skills

- `using-superlite` (injected at session start)
- `brainstorming`
- `writing-plans`
- `subagent-driven-development`
- `test-driven-development`
- `systematic-debugging`
- `verification-before-completion`
- `finishing-a-development-branch`

Agents: `implementer` (sonnet), `reviewer` (sonnet), `test-runner` (haiku).

## Install locally

Load for one session:

    claude --plugin-dir <path-to-superlite>

Or add it as a marketplace:

    /plugin marketplace add <path-to-superlite>
    /plugin install superlite@superlite-dev

## Benchmark

`bench/` holds a head-to-head harness: both plugins build the same 9-module project (`bench/task/SPEC.md`) headless on Opus, and a hidden 89-test suite scores the result. Run 1 (n=1 per arm; the runs overlapped):

| | superpowers 6.4.1 | superlite 0.1.0 |
|---|---|---|
| Wall-clock | 34.4 min | **8.8 min** (3.9× faster) |
| Hidden tests | 89 / 89 | 89 / 89 |
| Cost (API-equivalent) | **$24.44** | $29.52 |

Full write-up: [bench/report.md](bench/report.md).

## Tasks

- [ ] **Superlite 0.2: cut worker cost, re-run with 3 reps.** In run 1, Sonnet spend tripled ($15.72 vs $5.15, 651K output tokens) and the Opus coordinator accumulated about 20M cache-read tokens. Steps:
  - Find what the coordinator re-read each turn (from `bench/results/superlite-1.jsonl`) and push that reading into workers.
  - Run implementers at effort `low` for contract tasks.
  - Give each implementer up to 2 related modules per brief.
  - Tighten the test guidance in `writing-plans` so implementers don't over-produce tests.
  - Re-run 3 reps per arm sequentially and update `bench/report.md` with mean/min/max.

  Done when superlite's cost is at or below superpowers', it is still at least 2.5× faster, and it still passes 89/89.

## Note

Do not enable superlite at the same time as superpowers. They share skill names and both inject session context, so they conflict.

## License

MIT
