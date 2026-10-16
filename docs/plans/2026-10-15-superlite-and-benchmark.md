# Superlite + Benchmark — Design and Plan

**Status:** approved by the user to run unattended (2026-10-15). The coordinator (Opus) makes every ruling and records it under "Rulings" below.
**Execution:** orchestrator skill (`~/.claude/skills/orchestrator/SKILL.md`): waves of at most 5 agents, model and effort set on every call, reports capped.
**Progress:** `docs/plans/progress.md` (one line per task; the recovery map after compaction).

## Goal

1. **superlite**: a Claude Code plugin that ports superpowers' structure (plugin layout, hook, skill names for the core lifecycle) with much less process, so the default flow is far faster at similar quality.
2. **benchmark**: a reproducible head-to-head. The same complex, splittable build task runs headless with (a) stock superpowers 6.4.1 and (b) superlite. The runs are scored on wall-clock time, cost, turns, stops-for-human, and a hidden acceptance test suite.

## Why superpowers is slow (the findings this design answers)

- 8–12 human gates per feature: brainstorming asks one question per message, approves section by section, then reviews the spec, the plan and the execution choice. Worktree consent and the finish menu add more.
- writing-plans makes Opus write the complete code for every task into the plan, and then Sonnet transcribes it.
- subagent-driven-development (SDD) is strictly sequential: "never dispatch multiple implementation subagents in parallel". It adds a per-task review, up to 5 fix rounds with re-reviews, a preflight conflict table, a ledger and a rulings roll-up.
- The full suite is re-run by TDD, the worktree setup, verification and finishing.
- The session hook injects about 3KB with a "1% chance → invoke a skill" rule.
- Templates set no model. Superpowers' own data: about $13 per SDD run, with the Opus controller about half of it over ~150 turns (46% narration or thinking). Review-loop count is the biggest source of variance and is driven by plan ambiguity. Haiku reviewers caught 0 of 10 planted defects, so reviewers stay on Sonnet or above.

## Superlite design

### Layout (mirrors superpowers)

```
.claude-plugin/plugin.json          name "superlite", version 0.1.0
.claude-plugin/marketplace.json     local marketplace entry for this repo
hooks/hooks.json                    SessionStart (startup|clear|compact)
hooks/session-start                 bash; prints the hookSpecificOutput JSON with using-superlite's content
skills/using-superlite/SKILL.md     router (≤ 1,200 chars, injected by the hook)
skills/brainstorming/SKILL.md
skills/writing-plans/SKILL.md
skills/subagent-driven-development/SKILL.md
skills/test-driven-development/SKILL.md
skills/systematic-debugging/SKILL.md
skills/verification-before-completion/SKILL.md
skills/finishing-a-development-branch/SKILL.md
agents/implementer.md               model: sonnet
agents/reviewer.md                  model: sonnet
agents/test-runner.md               model: haiku
README.md
```

Dropped as separate skills: executing-plans (SDD has an inline mode), requesting/receiving-code-review (folded into SDD and the reviewer agent), using-git-worktrees (one paragraph in SDD), dispatching-parallel-agents (waves cover it), writing-skills and diagnosing-superpowers (out of scope).

### Principles every skill follows

1. **Size the request first.** Trivial (a few tool calls): just do it. Bounded (change to an existing flow): a short in-chat design, then one approval. Architectural: batched questions, then one combined design+plan doc, then one approval.
2. **One gate.** The human approves once, before implementation. After that, nothing stops except destructive, outward-facing (push, merge, publish) or security-sensitive actions. If the user says they are away or "decide yourself", the gate is pre-approved: record rulings and proceed.
3. **Batch questions.** Use AskUserQuestion with up to 4 questions in one call. Never one question per message.
4. **Plans carry contracts, not code.** Each task lists files, interfaces (exact signatures), the tests it must pass (names plus the behavior each asserts), and its wave. Code goes in the plan only for non-obvious algorithms, never as boilerplate.
5. **Waves, not queues.** Tasks with disjoint files and no import dependency run in parallel, up to 5 per wave, all sent in one message.
6. **Route models.** Use the orchestrator table: Opus coordinates, Sonnet implements and reviews, Haiku searches and runs tests. Every Agent call sets model and effort.
7. **Review per wave, not per task.** One reviewer per wave reads the wave's diff against the plan's task contracts. At most 2 fix rounds go to the original implementer (SendMessage); after that the coordinator fixes it directly. One final whole-branch review (Sonnet high; Opus when the branch touches auth, security or personal data). One fix pass after the final review, no re-review loop. Remaining findings are listed for the human.
8. **Test once per wave.** test-runner (Haiku) runs the full suite after each wave and once at the end. Implementers run only their focused tests. Its counts line is the evidence.
9. **Reports are short.** Implementers ≤ 200 words, reviewers ≤ 400. No file contents or logs.
10. **Light tracking.** `docs/plans/<plan>-progress.md` gets one line per task (`Task N: done <sha>` / `Ruling: …`), plus a final "Rulings" list in the closing message.

### Skill requirements

- **using-superlite** (≤ 1,200 chars): what superlite is; the size rule (principle 1); the skill map (build → brainstorming, plan → writing-plans, execute → subagent-driven-development, bug → systematic-debugging, claim done → verification-before-completion, finish → finishing-a-development-branch); "invoke a skill only when the task matches it — conversation and trivial edits need none". No "1% rule", no EXTREMELY_IMPORTANT.
- **brainstorming**: sizing announced in one line. Trivial → exit. Bounded → ≤ 1 batched AskUserQuestion, short design in chat, one approval, implement (TDD). Architectural → explore (Explore agent on haiku for broad sweeps), one batched AskUserQuestion (≤ 4 questions, multiple choice where possible), then write ONE doc `docs/plans/YYYY-MM-DD-<topic>.md` containing design + plan (invoke writing-plans for the plan half), self-review inline, one approval of that doc, then subagent-driven-development. Unattended mode skips the questions (choose sensible defaults, record as rulings) and the approval.
- **writing-plans**: plan header (Goal, Architecture, Tech stack, Global constraints with exact values, Waves table). Task template: Files (create/modify/test), Interfaces (consumes/produces with exact signatures), Tests (each test name and the behavior it asserts, with exact values), Notes (only non-obvious algorithm detail), Wave N. Rules: no placeholders; types consistent across tasks; fold setup and docs into the task that needs them; wave assignment follows the orchestrator wave rules (disjoint files, import deps wait, names-only deps share a wave). A self-review checklist (coverage, placeholders, type consistency, wave conflicts). No execution-method question: the default is SDD.
- **subagent-driven-development**: setup (branch: if on the default branch, create `superlite/<topic>` — no worktree unless parallel waves would overlap files; no consent prompt), the progress file, waves. Per wave: dispatch implementers (subagent_type `superlite:implementer`, a brief with the orchestrator's 6 parts pointing at the plan path and task heading, not pasting it), integrate from reports (`git status --short`, `git diff --stat`), commit per task by explicit path (the coordinator commits; implementers never commit), test-runner on the full suite, one `superlite:reviewer` over the wave diff (`git diff <wave-base>..HEAD` written to a file and passed by path), fix rounds ≤ 2 then the coordinator takes over. Final review, one fix pass, then finishing. Inline mode: when the plan has ≤ 3 tasks or one dependency chain, the coordinator implements directly, with one final review. Include the orchestrator routing table and the brief template.
- **test-driven-development**: red → green → refactor; write the failing test first, run only that test to see it fail, minimal code, run the focused tests; no full-suite runs inside a task (the wave's test-runner covers them). ≤ 3,500 chars.
- **systematic-debugging**: reproduce → hypothesize (state the one most likely root cause) → test the hypothesis with the smallest probe → fix with a regression test. After 2 failed fixes, step back and re-read the evidence; after 3, change the approach (a fresh agent on a stronger model, or ask the human if attended). Obvious failures (typo, import error, clear stack trace) get fixed directly. ≤ 4,000 chars.
- **verification-before-completion**: before claiming done, the evidence is a fresh test-runner counts line, or a focused run you executed yourself after the last change. Don't re-run if nothing changed since the last green run. Read the 2–3 lines a claim rests on. ≤ 2,500 chars.
- **finishing-a-development-branch**: test-runner full suite (skip if green since the last change). Attended: ask ONE question (merge locally / push and open a PR / keep the branch) via AskUserQuestion. Unattended: keep the branch, print a summary with the rulings list. Never push or merge without the human. ≤ 3,000 chars.
- **agents/implementer.md** (model sonnet): reads its task from the plan path; follows TDD; edits only its owned files; never commits, switches branches or spawns agents; runs its focused tests; report contract: status DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED, files changed, test command + result line, concerns; ≤ 200 words.
- **agents/reviewer.md** (model sonnet): read-only (tools Read, Grep, Glob, Bash for git); input is the diff file path + plan path + task headings; checks spec compliance per task contract, correctness bugs, missing tests for the contract, and obvious quality problems; it doesn't flag style nits; output: per task ✅/❌, findings tagged Critical / Important / Minor with file:line, verdict APPROVED / CHANGES_REQUESTED; ≤ 400 words.
- **agents/test-runner.md** (model haiku): tools Bash, Read, Grep, Glob; runs the given command; reports the command, the counts line, and each failure's test id + one-line error; never edits; ≤ 200 words.

## Benchmark design

### Task: `sitegen`, a static site generator (Python 3.12+, stdlib only, uv, pytest)

Chosen because it splits into 7 independent pure modules plus 2 integration layers. That suits waves and is the same scale as a real feature. `bench/task/SPEC.md` gives both arms the full public contract (module paths, function signatures, behavior with exact examples), so a hidden test suite can score them fairly.

Modules (all under `src/sitegen/`):
1. `frontmatter.py`: `parse(text) -> tuple[dict, str]` (YAML-subset front matter between `---` lines: str, int, bool, quoted strings, inline lists).
2. `markdown.py`: `render(md: str) -> str` (headings, paragraphs, emphasis/strong, inline code, fenced code, links, images, flat ul/ol, blockquote, hr, HTML escaping).
3. `templates.py`: `render(template: str, context: dict) -> str` (`{{ var }}`, dotted lookup, filters `upper|lower|title|escape|safe|default:"x"|join:", "|length`, `{% for %}` with `loop.index`, `{% if %}/{% elif %}/{% else %}`, autoescape on by default, `TemplateError` on bad syntax).
4. `slug.py`: `slugify(text) -> str`, `unique_slug(text, taken: set[str]) -> str`.
5. `feed.py`: `build_rss(site: dict, posts: list[dict]) -> str` (RSS 2.0, newest first, max 20 items, RFC-822 dates, escaped).
6. `search.py`: `build_index(docs) -> dict`, `search(index, query, limit=10) -> list[str]` (tokenize, lowercase, stopwords, TF scoring, AND semantics, tie-break by slug).
7. `links.py`: `find_broken_links(pages: dict[str, str]) -> list[tuple[str, str]]` (internal hrefs only; resolves relative paths and `#anchors` by id).
8. `site.py`: `build(src: Path, out: Path) -> BuildReport` (content/*.md → posts; drafts skipped; templates/; per-post pages, index, tag pages, feed.xml, search.json; static/ copied).
9. `cli.py` + `__main__.py`: `python -m sitegen build SRC OUT`, `python -m sitegen check OUT` (exit 0 / 1 / 2 contract).

### Hidden acceptance suite

`bench/hidden_tests/` (≈ 80 tests) is written from SPEC.md alone by one agent. `bench/reference/` is a reference implementation written from SPEC.md alone by a different agent. Both must agree: run the hidden tests against the reference, and every disagreement is ruled against the SPEC (fix the test, the reference, or clarify the SPEC). The arms never see either.

### Harness: `bench/run_arm.sh <arm> <rep>`

- Creates `bench/runs/<arm>-<rep>/` (git-ignored): `git init`, copies SPEC.md, makes an initial commit.
- Runs `claude -p` with `--model opus`, `--permission-mode auto`, `--output-format stream-json --verbose` and `--max-budget-usd 60`, in the run dir, logging the stream to `bench/results/<arm>-<rep>.jsonl`.
  - `superpowers` arm: the user settings as they are (superpowers enabled).
  - `superlite` arm: `--settings '{"enabledPlugins":{"superpowers@claude-plugins-official":false}}' --plugin-dir <repo>`.
- The same prompt for both arms, from `bench/prompt.md`: build SPEC.md; use your installed development-workflow skills as you normally would; no human is available, so this message pre-approves any design, spec, plan and execution choice; prefer subagent-driven execution; end with the line `BENCHMARK-COMPLETE`.
- **Stops-for-human:** if the final message lacks `BENCHMARK-COMPLETE`, resume the session (`--resume <id> -p "Approved. No human is available — decide yourself and continue."`), up to 6 times. Each resume counts as one human round trip.
- `bench/score.sh <arm> <rep>`: copies hidden_tests into a temp copy of the run dir, runs pytest, and writes `bench/results/<arm>-<rep>.json` with: wall_ms, cost_usd, turns, resumes, hidden pass/total, own test count, src LOC, and per-model usage from the result events.
- `bench/report.md`: the comparison table plus observations.

Reps: 1 per arm first (sequential, for clean timing); add a second rep per arm if the first results are close or noisy.

## Waves

| Wave | Tasks (parallel) |
|---|---|
| 1 | T1 plugin skeleton + hook + using-superlite + README · T2 brainstorming + writing-plans · T3 subagent-driven-development + 3 agents · T4 TDD + debugging + verification + finishing · T5 bench/task/SPEC.md |
| 2 | T6 reference impl · T7 hidden tests · T8 harness scripts + prompt (needs SPEC only by path) · coordinator reviews T1–T4 |
| 3 | T9 reconcile hidden tests vs reference (test-runner + fixes) · T10 harness smoke test (superlite plugin loads, superpowers disabled, a 1-turn prompt) |
| 4 | T11 run the superpowers arm · then T12 run the superlite arm (background, sequential) |
| 5 | T13 score both, write bench/report.md, commit |

## Rulings

- Ruling: the repo lives at `C:\Users\CWogu\source\repos\superlite` (the user's repos folder); git main branch, no remote; no pushes.
- Ruling: Python via `uv run` (no system python on this machine).
- Ruling: both arms run on `--model opus` with the user's normal user-level config (the orchestrator skill, the Explore/test-runner overrides and the Sonnet subagent default all apply to both). This is "regular superpowers as this user runs it". The report notes the contamination risk from the user-level orchestrator skill.
- Ruling: `--permission-mode auto --permission-prompts none` rather than bypass, for unattended safety; each run is confined to its own run dir by the prompt.
- Ruling (supersedes the contamination note above): both arms disable the user-level `orchestrator` skill with `--settings '{"skillOverrides":{"orchestrator":"off"}}'` plus `--disallowedTools "Skill(orchestrator)"`, so the comparison isolates the plugins. superlite carries the orchestrator's rules inside its own SDD skill. The Sonnet subagent default, Explore=haiku and test-runner user agents stay as they are for both arms.
- Ruling: plugin agents set `model` and `effort` in frontmatter (both documented for plugin subagents). They are referenced as `superlite:<agent>`; the smoke test (T10) confirms the Agent tool accepts that subagent_type.
