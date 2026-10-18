# Who orchestrates: human orchestrator or AI orchestrator

When someone asks superlite to create something, it first settles who orchestrates (D40).

- **Human orchestrator:** the human validates the plan before it is linted and sent off, in two phases. Phase 1: the review plan
  (`docs/plans/<date>-<topic>.review.md`, plain words with diagrams; template in `../writing-plans/review-plan.md`) is shown with its
  path and a five-line summary. Phase 2, after the yes: `sl orchestrator approve --review <path>`, then the coordinator writes the
  machine plan from it (header `**Review plan:** <path>`), `schedule --insert`, `lint --stable`, dispatch.
- **AI orchestrator:** does everything itself (plan, lint, dispatch, rulings) and never stops to ask, except for the
  destructive, outward-facing or security-sensitive actions in the SDD "Stop conditions".

## The question (brainstorming, once)
One single-choice question, in the same `AskUserQuestion` call as brainstorming's other open questions (up to 4 per call):

- `Human orchestrator: I approve the plan before it runs`
- `AI orchestrator: hands off, it does everything`

Do NOT ask when the request already settles it: "decide yourself", "I am away", pre-approved design and plan, or any other
unattended signal (all mean AI). When no human can answer (a headless `claude -p` run), default to AI and record it:
`sl orchestrator set ai --by coordinator --ruling "orchestrator defaulted to AI - headless run, no human can answer - cost if wrong: none"`.

## The tool (`sl orchestrator`)
- `set human|ai [--by NAME] [--ruling TEXT]` writes `.superlite/orchestrator.json` `{mode, approved, by, time}`
  (`approved` is true for AI, false for human until `approve`).
- `approve [--by NAME] [--review PATH]` records the approval (human mode only; exit 2 otherwise). `--review` also records the review
  plan's path and sha256 in `orchestrator.json` (`review_path`, `review_sha256`); a missing file fails with exit 2; without `--review`
  nothing else changes. `status` and `finish` print the review plan path.
- `status` prints one line: `orchestrator: human, awaiting approval` / `human, approved <time> by <name>` / `AI` / `not set (ungated)`.
- Gate: in human mode without an approval `plan_tools lint --stable`, `dispatch`, `wave0` and `build_prime` exit 4 with
  `BLOCKED: human orchestrator selected, show the plan, ask for approval, then run sl orchestrator approve`.
  `schedule --insert`, `prune` and plain `lint` are never gated. With no `orchestrator.json` nothing is gated, so existing
  runs behave as before. `finish` prints the mode line (with the approval time in human mode).
- The gate stops the tools, not the model: the coordinator could still call `approve` itself. Only a human answer to the
  approval question may precede `approve`.

## Benchmarks
Every prompt file under `bench/` (`prompt*.md`, `tasks/*/prompt*.md`) ends with `Orchestrator: AI, do not ask me to choose or to approve.`
(a test checks this), so the decider is never asked. To test the human gate, run the session in human mode:
`sl orchestrator set human` before the run (or ask for it in the prompt), expect `BLOCKED` from `lint --stable` until
`sl orchestrator approve`, and expect a headless run to end on the approval question.

## Proposed, not built: a hook (owned by the hooks session)
A PreToolUse hook on `AskUserQuestion` that, when `.superlite/orchestrator.json` says `ai`, denies the call with
`AI orchestrator: decide yourself, record a Ruling` unless the question's text names a destructive, outward-facing
(push, merge, publish) or security-sensitive action. It should allow the call when the file is absent or says `human`,
log each denial as an incident `kind: rule-block`, and also deny a Bash call of `sl orchestrator approve` unless an
`AskUserQuestion` answer was received earlier in the session.
