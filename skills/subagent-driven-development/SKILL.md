---
name: subagent-driven-development
description: Use when executing an implementation plan that has a Waves table or several tasks. Runs tasks in parallel waves with per-wave review and routed models.
---

# Subagent-Driven Development

You are the coordinator. You decide, dispatch, integrate and commit. Workers read, write and run, on the cheapest model that does the job. Your context is the budget: everything you read or paste is re-sent every turn. Keep narration to one short line between tool calls.

**Rulings, not stalls.** A running plan does not wait on a human. Conflicts, ambiguities, plan defects: decide them (the spec is binding, the plan is its argument, your judgment fills the rest). Append `Ruling: <decision> - <why> - <cost if wrong>` to the progress file and keep going. Stop only for: an irreversible or destructive operation; a security-sensitive action; an outward side effect (merge, push, publish); a plan so broken every path is a guess.

## Setup

- Branch: if on the default branch, create `superlite/<topic>`. No worktree and no consent prompt. Use `isolation: "worktree"` on a call only if tasks in one wave might overlap files.
- Progress file `docs/plans/<plan>-progress.md`: one line per task (`Task N: done <sha>`) and each `Ruling:`. It is the recovery map after compaction: trust it and `git log` over memory, and never re-dispatch a done task.
- Read the plan once (header, global constraints, Waves table). One todo per wave. If a task text is ambiguous, rule on it now and put the ruling in the brief.

## Inline mode

With 3 or fewer tasks, or one dependency chain, skip agents: implement directly (TDD), commit per task, run the suite once yourself or via test-runner, then do the final review. Waves buy nothing here.

## Routing: every Agent call sets `model` and `effort`

| Work | subagent_type | model | effort |
|---|---|---|---|
| Find files or symbols | Explore | haiku | low |
| Explain how code works | Explore | sonnet | medium |
| Implement (plan has full code) | superlite:implementer | sonnet | low |
| Implement (contract in prose) | superlite:implementer | sonnet | medium |
| Run tests or a build | superlite:test-runner | haiku | low |
| Wave review | superlite:reviewer | sonnet | medium |
| Final review | superlite:reviewer | sonnet | high |
| Final review, branch touches auth, security or personal data | superlite:reviewer | opus | high |
| Web or docs research | general-purpose | sonnet | medium |

Pass `model` and `effort` on the call; they override the agent frontmatter. Haiku never reviews. For fix round 2 or a BLOCKED task, re-dispatch on a stronger model, not the same one.

## Waves

- A wave is tasks that share no files and need no one else's output. At most 5 agents; send all of them in **one message**.
- A task waits when its code or tests import an earlier task's files, or it documents what that task built.
- A task needing only a name from another (a route, a flag), whose tests do not run that code, gets the name in both briefs and shares the wave.
- Use the plan's wave assignment. Re-check it for file overlap; fix it by ruling if wrong.

## The brief: six parts, in order

1. **Goal**: what done looks like.
2. **Source**: "Read Task N in `<plan path>`." Never paste the task text.
3. **Files**: the files it owns, and the ones it must not touch.
4. **Rules it will not inherit**: shell and test command, forbidden files, no `git add`, `commit` or `switch`, no spawning agents.
5. **Verify**: the focused test command to run before reporting.
6. **Report**: "Reply in at most 200 words: status (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED), files changed, test command and result line, open questions. No file contents or logs."

Add only what the plan cannot know: interface names from other waves' reports, your rulings.

## Per-wave loop

1. Record the wave base: `git rev-parse HEAD`.
2. Dispatch the whole wave in one message.
3. **Integrate from reports.** DONE proceeds. DONE_WITH_CONCERNS: read the concerns; correctness or scope ones are fixed before review, observations are noted. NEEDS_CONTEXT: answer by SendMessage to that agent. BLOCKED: add context, split the task, or re-dispatch on a stronger model; never retry unchanged. Check scope with `git status --short` and `git diff --stat`. If a decision rests on one claim, read the 2-3 lines it cites.
4. **Commit per task by explicit path** (`git add <task's files>`, then `git commit`). Only you commit; never `git add -A`. Add `Task N: done <sha>` to the progress file.
5. **Test.** Dispatch `superlite:test-runner` on the full suite. Its quoted command and counts line is the evidence. Do not run the suite yourself or re-run implementers' tests.
6. **Review.** Write the diff to a file: `git diff <wave-base>..HEAD > <scratch>/wave-N.diff`, with `git log --oneline` and `--stat` output at the top. Dispatch one `superlite:reviewer` with the diff path, the plan path and the wave's task headings, in the same brief shape (word cap 400). Do not pre-judge: never tell it to skip or soften an issue. If you think a finding is wrong, let it raise it and rule afterwards.
7. **Resolve "Cannot verify from diff" items yourself**; you hold the cross-task context. A real gap joins the findings.
8. **Fix rounds, at most 2.** Send Critical and Important findings verbatim to the original implementer with SendMessage, and ask for the covering tests re-run. Commit the fix, then test-runner on the full suite. Minor findings go to the progress file (`Task N: minor: ...`) for the final review. A finding that conflicts with the plan text is yours to rule on, as a ruling. No re-review per round: the next wave's reviewer and the final review see the fixed code. If Critical or Important findings remain after round 2, take the task over yourself, fix it directly, and record a ruling.
9. Update the progress file, mark the todo done, start the next wave. Do not pause between waves to check in.

## Final review

When all waves are done and the suite is green:
- Write the whole-branch diff to a file (`git diff $(git merge-base <default-branch> HEAD)..HEAD`).
- Dispatch one `superlite:reviewer` (sonnet, high; opus, high if the branch touches auth, security or personal data). Give it the diff path, the plan path, and the progress file's minor and ruling lines to triage.
- If it returns findings, dispatch **one** implementer (or fix small ones yourself) with the complete findings list, not one per finding. Then test-runner once. No re-review loop.
- Anything still open is listed for the human, with a ruling.

## Finish

Collect every `Ruling:` line from the progress file and print them in your closing message under "Rulings I made", in order, each with what it costs if wrong. The list is exhaustive; it is the only way your decisions reach the human. Then invoke `superlite:finishing-a-development-branch`.

## Common mistakes

| Mistake | Do instead |
|---|---|
| Dispatching one implementer at a time | Send the whole wave in one message |
| `model` left unset (inherits Opus) | Set model and effort on every call |
| Pasting task text into a brief | Give the plan path and heading |
| Reviewer without a diff file | Write the diff to a file, pass the path |
| Per-task reviews or re-review loops | One reviewer per wave; at most 2 fix rounds |
| Running the suite yourself | test-runner; its counts line is the evidence |
| `git add -A`, or implementers committing | Coordinator commits by explicit path |
| Asking "should I continue?" between waves | Apply the four stop conditions only |
