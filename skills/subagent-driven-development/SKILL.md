---
name: subagent-driven-development
description: Use when executing an implementation plan that has a Waves table or several tasks. Runs tasks in parallel waves with pipelined review and routed models.
---

# Subagent-Driven Development

You are the coordinator. You decide, dispatch, integrate and commit. Workers read, write and run, on the cheapest model that does the job. Your context is the budget: everything you read or paste is re-sent every turn. Keep narration to one short line between tool calls. Agents carry their own rules: never paste skill text into a brief.

**Rulings, not stalls.** A running plan does not wait on a human. Conflicts, ambiguities, plan defects: decide them (the spec is binding, the plan is its argument, your judgment fills the rest). Append `Ruling: <decision> - <why> - <cost if wrong>` to the progress file and keep going. Stop only for: an irreversible or destructive operation; a security-sensitive action; an outward side effect (merge, push, publish); a plan so broken every path is a guess.

**Unattended** (the user is away, said "decide yourself", or pre-approved the run): never end your turn to wait. For the four cases above, take the safe path instead: skip or defer the outward or destructive action, choose the most conservative reading of a broken plan, record the ruling, and keep going. The closing message lists what you deferred.

## Setup

- Branch: if on the default branch, create `superlite/<topic>`. No worktree and no consent prompt. Record the start SHA (`git rev-parse HEAD`) in the progress file; the final review diffs from it.
- Progress file `docs/plans/<plan>-progress.md`: one line per task (`Task N: done <sha> agent <id>`), each `Ruling:`, and per wave its minutes plus each task's actual vs estimated context when the result reports usage. It is the recovery map after compaction: trust it and `git log` over memory, and never re-dispatch a done task. Commit the plan and the progress file with the first task commit and again at the end.
- Scratch files (primes, diffs) go in the OS temp dir (`${TMPDIR:-${TEMP:-/tmp}}/superlite-<topic>/`), never in the repo.
- Read the plan once (header, global constraints, Waves table). One todo per wave. If a task text is ambiguous, rule on it now and put the ruling in its task message.
- **Skeleton first.** Before wave 1, create whatever every parallel task needs in order to run its tests (project manifest, package `__init__`, test config, shared error types) yourself, in one commit, unless the plan has a Wave 0 task for it. Parallel tasks must never collide on these files.

## Inline mode

With 3 or fewer tasks, or one dependency chain, skip agents: implement directly (TDD), commit per task, run the full suite once via test-runner, then do the final review. Waves buy nothing here.

## Routing: every Agent call sets `model` and `effort`

| Work | subagent_type | model | effort |
|---|---|---|---|
| Find files or symbols | Explore | haiku | low |
| Explain how code works | Explore | sonnet | medium |
| Implement a task (low when the plan carries full code or the change is single-file mechanical) | superlite:implementer | sonnet | medium |
| Run tests or a build | superlite:test-runner | haiku | low |
| Wave review | superlite:reviewer | sonnet | medium |
| Package or mid-build review of a finished component (optional) | fork | opus | high |
| Final review: always, fresh eyes plus robustness probes | superlite:reviewer (final mode) | opus | high |
| Web or docs research | general-purpose | sonnet | medium |

Pass `model` and `effort` on the call; they override the agent frontmatter. Haiku never reviews. For fix round 2 or a BLOCKED task, re-dispatch once on a stronger model, not the same one (a fresh agent skips the prime: brief it with the task message plus the plan path); if it is still blocked, take the task over yourself.

## Waves

- A wave is tasks that share no files and need no one else's output. At most 5 agents. Every implementer in a wave uses the same subagent_type, model and effort (identical prefix, shared cache): pick one effort per wave.
- A task waits when its code or tests import an earlier task's files, or it documents what that task built.
- A task needing only a name from another (a route, a flag), whose tests do not run that code, gets the name in both task messages and shares the wave.
- Use the plan's wave assignment. Re-check it for file overlap; fix it by ruling if wrong.
- **Context check before dispatch.** Read each task's `Est. context` line (no line: 20 tokens per line written, 37 per line read). Above 80k: split the task or add an Explore summary. Variable part (peak minus the implementer prefix, about 18k) below the prefix: merge it with a same-wave neighbor, if the merge stays under 80k. Record a ruling.

## Prime, then assign

Siblings share the cache only when the whole first message is byte-identical, so the task never goes in it.

1. **Prime file**, written once per wave to the scratch dir: a fixed preamble ("Shared context for this wave's implementers: plan and spec follow; do not act yet."), the plan text, the SPEC sections the wave needs, and the last line "Reply with exactly READY; your task follows in the next message." A plan over 25k chars is not pasted: put the plan path in the prime.
2. **Warm.** Dispatch the first implementer alone with the prime text pasted verbatim as its prompt; wait for READY.
3. **Fan out.** Dispatch the rest of the wave in **one message**, the same prime bytes, subagent_type, model and effort.
4. **Assign.** In one message, SendMessage each agent its task: the task heading, files it owns and must not touch, shell and test command, rulings and interface names from earlier waves' reports (never the task text), the verify command, and the report contract: "Reply in at most 200 words: status (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED), files changed, test command and result line, open questions. No file contents or logs."

## Per-wave loop

1. Record the wave base: HEAD where the previous wave's review diff ended (before its fix commits), or the skeleton commit for wave 1. Each wave's review then covers the previous wave's fixes.
2. Context check, prime, warm, fan out, assign.
3. **Wait once.** Do not re-wake to poll. Handle the wave's reports in one bookkeeping message: integrate, commit, progress file, next dispatch.
4. **Integrate from reports.** DONE proceeds. DONE_WITH_CONCERNS: correctness or scope concerns are fixed before review, observations are noted. NEEDS_CONTEXT: answer by SendMessage. BLOCKED: add context, split the task, or re-dispatch on a stronger model; never retry unchanged. Check scope with `git status --short` and `git diff --stat`. If a decision rests on one claim, read the 2-3 lines it cites.
5. **Commit per task by explicit path** (`git add <task's files>`, then `git commit`). Only you commit; never `git add -A`.
6. **Pipeline.** Write the diff to a scratch file (`git log --oneline` and `git diff --stat` for the range at the top, then `git diff <wave-base>..HEAD`). In **one message** dispatch `superlite:test-runner` (full suite) and one `superlite:reviewer` (diff path, plan path, the wave's task headings, "read the plan header's Global constraints", word cap 400), plus the next wave's warm prime. The suite needs a quiet tree, so send the next wave's task messages once the test-runner reports; its counts line is the evidence, and failures are findings. The reviewer runs while the next wave implements. The last wave has no wave review; the final review covers it.
7. **Findings arrive during the next wave.** Never pre-judge or soften them. Resolve "Cannot verify from diff" items yourself; a real gap joins the findings. Send Critical and Important findings verbatim to the original implementer by SendMessage (fix messages), asking for the covering tests re-run; commit the fix by path. Minor findings go to the progress file (`Task N: minor: ...`). A finding that conflicts with the plan is yours to rule on.
8. **Blocking rule.** If a finding is in code a next-wave task imports, hold only that task: send its task message after the fix commits (if it already started, forward the fix by SendMessage). The other tasks proceed.
9. **At most 2 fix rounds.** No re-review per round: the next review and the final review see the fixed code, and the next suite run covers it. If Critical or Important findings remain after round 2, take the task over yourself and record a ruling.
10. Update the progress file, mark the todo done, start the next wave. Do not pause between waves to check in.

## Final review

When all waves are done, pending findings are fixed, and the suite is green:
- Write the whole-branch diff to a scratch file (`git diff <start-sha>..HEAD`).
- Dispatch one **fresh** `superlite:reviewer` in **final mode** (model opus, effort high). It is not a fork: it must not share your blind spots. Its brief holds the diff path, the spec path, the plan path, how to import and run the code (package path and entry points), the progress file's minor and ruling lines to triage, and "final mode: re-derive the requirements from the spec, and run the robustness checklist with real probes". A 15-second final review is a failed review: if it returns in under 2 minutes with no probes listed, send it back once with "run the checklist probes".
- If it returns findings, dispatch **one** implementer (or fix small ones yourself) with the complete list. Every robustness finding gets a regression test built from its probe input. Then test-runner once. If a Critical finding was fixed, one scoped reviewer checks just the fix diff; otherwise no re-review.
- Anything still open is listed for the human, with a ruling.

## Finish

Collect every `Ruling:` line from the progress file and print them in your closing message under "Rulings I made", in order, each with what it costs if wrong. The list is exhaustive; it is the only way your decisions reach the human. Then invoke `superlite:finishing-a-development-branch`.

## Common mistakes

| Mistake | Do instead |
|---|---|
| Task line in the first message, or primes that differ | Identical prime bytes; task by SendMessage |
| Fanning out before the first READY | Warm one, then send the rest |
| Mixed model or effort inside a wave | One setting per wave |
| Waiting on each wave review before starting the next wave | Review runs during the next wave |
| `model` left unset (inherits Opus) | Set model and effort on every call |
| Pasting task text or skill text into a brief | Task heading; agents have their rules |
| Respawning to fix | SendMessage the original implementer |
| Polling or one wake per report | One bookkeeping message per wave |
| Dispatching without the `Est. context` check | Split above 80k, merge below the floor |
| Running the suite yourself | test-runner; its counts line is the evidence |
| `git add -A`, or implementers committing | Coordinator commits by explicit path |
| Asking "should I continue?" between waves | Apply the four stop conditions only |
