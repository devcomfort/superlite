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

## Note

Do not enable superlite at the same time as superpowers. They share skill names and both inject session context, so they conflict.

## License

MIT
