# superlite

A plugin for Claude Code and the other coding-agent harnesses superpowers supports (see Installation). It keeps the structure of [superpowers](https://github.com/obra/superpowers) (plugin layout, SessionStart hook, core lifecycle skills) with far less process, so the default flow is much faster at similar quality.

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

## Installation

Installation differs by harness. If you use more than one, install superlite separately for each one. Every integration loads `using-superlite` at session start; to verify, open a fresh session and send `Let's make a react todo list`. A working install triggers `brainstorming` before any code is written.

Each harness has a tool-mapping file in `skills/using-superlite/references/` (Antigravity, Codex, Gemini, Hermes, Muse, Pi, plus Claude Code notes). Where a harness has no plugin agents, `implementer`, `reviewer` and `test-runner` run as that harness's generic subagent with `agents/<name>.md` as its instructions.

### Claude Code

Load for one session from a local checkout:

    claude --plugin-dir <path-to-superlite>

Or add a local checkout as a marketplace:

    /plugin marketplace add <path-to-superlite>
    /plugin install superlite@superlite-dev

Or install from GitHub:

    /plugin marketplace add iha2/superlite
    /plugin install superlite@superlite-dev

### Antigravity

Install superlite as a plugin from this repository:

```bash
agy plugin install https://github.com/iha2/superlite
```

Antigravity runs the plugin's session-start hook, so superlite is active from the first message. Reinstall with the same command to update.

### Codex App

> Unverified: superpowers ships on Codex through the official Codex marketplace, which superlite isn't listed in. This repo includes `.agents/plugins/marketplace.json` for a repo marketplace, but the command below hasn't been tested yet.

- Add this repository as a plugin marketplace:

  ```bash
  codex plugin marketplace add iha2/superlite
  ```

- In the Codex app, click on Plugins in the sidebar, find `Superlite` in the Coding section, and click the `+` next to it.
- Add `[features]` `multi_agent = true` to `~/.codex/config.toml` for subagent dispatch.

### Codex CLI

> Unverified: superpowers ships on Codex through the official Codex marketplace, which superlite isn't listed in. This repo includes `.agents/plugins/marketplace.json` for a repo marketplace, but the command below hasn't been tested yet.

- Add this repository as a plugin marketplace:

  ```bash
  codex plugin marketplace add iha2/superlite
  ```

- Open the plugin search interface:

  ```bash
  /plugins
  ```

- Search for `superlite` and select `Install Plugin`.

### Cursor

- In Cursor Agent chat, install from marketplace:

  ```text
  /add-plugin superlite
  ```

- Or search for "superlite" in the plugin marketplace.
- Or load a local checkout of `https://github.com/iha2/superlite` as a local plugin; Cursor reads `.cursor-plugin/plugin.json`.

### Devin CLI

- Install the plugin from this repository:

  ```bash
  devin plugins install iha2/superlite
  ```

- Update to the latest version with:

  ```bash
  devin plugins update superlite
  ```

### Factory Droid

- Register the marketplace:

  ```bash
  droid plugin marketplace add https://github.com/iha2/superlite
  ```

- Install the plugin:

  ```bash
  droid plugin install superlite@superlite-dev
  ```

### Gemini CLI

- Install the extension:

  ```bash
  gemini extensions install https://github.com/iha2/superlite
  ```

- Update later:

  ```bash
  gemini extensions update superlite
  ```

### GitHub Copilot CLI

- Register the marketplace:

  ```bash
  copilot plugin marketplace add iha2/superlite
  ```

- Install the plugin:

  ```bash
  copilot plugin install superlite@superlite-dev
  ```

### Grok Build CLI

> Unverified: superpowers ships on Grok through the official xAI marketplace, which superlite isn't listed in. The commands below haven't been tested yet.

- Register this repository as a marketplace:

  ```bash
  grok plugin marketplace add iha2/superlite
  ```

- Install the plugin:

  ```bash
  grok plugin install superlite@superlite-dev --trust
  ```

- Or open the marketplace in the TUI, search for Superlite, and install it:

  ```text
  /marketplace
  ```

### Kimi Code

- Open Kimi Code's plugin manager:

  ```text
  /plugins
  ```

- Install directly from this repository:

  ```text
  /plugins install https://github.com/iha2/superlite
  ```

- Start a fresh session with `/new` afterwards.
- Detailed docs: [docs/README.kimi.md](docs/README.kimi.md)

### OpenCode

OpenCode uses its own plugin install; install superlite separately even if you already use it in another harness.

- Tell OpenCode:

  ```
  Fetch and follow instructions from https://raw.githubusercontent.com/iha2/superlite/refs/heads/main/.opencode/INSTALL.md
  ```

- Detailed docs: [docs/README.opencode.md](docs/README.opencode.md)

### Pi

Install superlite as a Pi package from this repository:

```bash
pi install git:github.com/iha2/superlite
```

For local development, run Pi with a checkout loaded as a temporary package:

```bash
pi -e /path/to/superlite
```

The Pi package loads the superlite skills and a small extension that injects the `using-superlite` bootstrap at session startup and again after compaction. Subagent and task-list tools remain optional Pi companion packages.

### Qwen Code

Qwen Code installs plugins from Claude Code marketplaces directly.

- Install the plugin from this repository:

  ```bash
  qwen extensions install iha2/superlite
  ```

- Update later:

  ```bash
  qwen extensions update superlite
  ```

### Hermes Agent

Install superlite as a Hermes plugin from this repository:

```bash
hermes plugins install iha2/superlite --enable
```

Restart any active Hermes sessions after installing. Hermes has no post-compaction hook, so a very long session that compacts over its first turn loses the bootstrap; start a fresh session if skills stop triggering.

### Muse

Superlite is a native Muse plugin. The `using-superlite` bootstrap is injected via the native `SessionStart` hook, with no per-session opt-in.

- Install from a local checkout:

  ```bash
  muse plugins install ./
  muse plugins approve superlite
  ```

  Or clone and install:

  ```bash
  git clone https://github.com/iha2/superlite.git
  muse plugins install ./superlite
  muse plugins approve superlite
  ```

- Update later:

  ```bash
  muse plugins update superlite
  ```

Restart any active Muse sessions after installing so the `SessionStart` hook takes effect; hooks require approval on first install.

### Keeping versions in sync

The version lives in every manifest listed in `.version-bump.json`. Bump all of them with one command, and check for drift with `--check` or `--audit`:

```bash
scripts/bump-version.sh 0.2.0
scripts/bump-version.sh --check
```

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
