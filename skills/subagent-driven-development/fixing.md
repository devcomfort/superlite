# Fixing: routing, escalation, contract

The coordinator never edits source or tests and never runs raw `pytest`. Every fix goes to a fix-only agent.

| Tier | Agent | Use when |
|---|---|---|
| 1 | `superlite:fixer-haiku` (haiku, high) | Fully specified: exact `file:line` and change known (a reviewer's concrete fix line, missing import, CRLF, rename). |
| 2 | `superlite:fixer-sonnet` (sonnet, medium) | Cause known; fix confined to one module, plus a regression test. |
| 3 | `superlite:fixer-sonnet-high` (sonnet, high) | Cause known, but the fix spans modules or a seam, or a known probe class (deep recursion, huge input, protocol edge). |
| 4 | `superlite:fixer-opus` (opus, high) | Cause unknown and needs diagnosis, or a lower tier failed 2 rounds. |

- **Escalation:** after 2 failed rounds at a tier, move up one. Log each failed round with `incident`.
- **Owner reuse:** if the task's own implementer is idle, within reuse limits (<=3 tasks, <=80k context, <=50 min idle) and its model matches the tier, send it a fix-only brief instead of a fresh fixer.
- **Package reviewers** still fix what they find, but must close every finding, including ones sent later, and report a closed list.
- **Final reviewer** only reports findings. They go to fixers, routed by tier and split by file.
- **Fixer contract:** fix only the named findings; one regression test per fix; run `bash "$SL" run_tests --fast PATHS --background` on the touched files and wait only for that summary; `commit_task` by path; report a closed list. Never refactor, never touch files outside the finding.
- Never pass `model` to an agent call (it overrides the agent file). Never dispatch an extra or ad-hoc reviewer, and never `general-purpose` for build, review or fix work. An inadequate review gets a `Ruling:`.
