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
| Cost (API-equivalent) | $8.15 | **$3.28** (60% cheaper) |

Full write-up: [bench/report.md](bench/report.md). (An earlier version of these numbers overstated both costs because of a scoring bug; see the correction note in the report.)

## Tasks

- [ ] **Superlite 0.2: cache sharing, Opus review and code-in-plan as measured options, 3 reps.** The design is in `C:\Work\Planning\Specs\2026-10-17-superlite-architecture-design.md`. Steps:
  - Shared, byte-identical brief prefixes, with warm-then-fan-out dispatch and the 1-hour subagent cache TTL.
  - The Opus final review back as the default.
  - A `code-in-plan` switch.
  - A harder benchmark task where review quality shows.
  - 3 reps per arm, run sequentially.

  Done when the measured speed holds (at least 2.5× faster than superpowers), cost stays at or below superpowers', and each option's effect is measured.

## Note

Do not enable superlite at the same time as superpowers. They share skill names and both inject session context, so they conflict.

## License

MIT
