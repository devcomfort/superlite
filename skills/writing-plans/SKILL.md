---
name: writing-plans
description: Use when you have an approved design or requirements for a multi-step task and need an implementation plan, before touching code.
---

# Writing Plans

A plan is a set of contracts that Sonnet implementers can execute without asking questions. Each task says which files it owns, which signatures it consumes and produces, which tests it must pass, and which wave it runs in. The plan does not contain boilerplate code. Writing code the implementer would write anyway burns Opus time and invites transcription errors.

Save to `docs/plans/YYYY-MM-DD-<topic>.md`. When called from `superlite:brainstorming`, append to its doc instead. If the spec covers independent subsystems, write one plan per subsystem.

## Decompose first

List the files and what each is responsible for. One responsibility per file, split by responsibility and not by layer, and follow the repo's existing patterns. Then cut tasks: a task is the smallest unit with its own tests and a deliverable a reviewer could accept or reject alone. Fold setup, config and docs into the task that needs them. No separate "scaffolding" or "write README" task unless the README documents other tasks' output, and then it waits for them.

## Plan header

```markdown
# <Feature> Plan
**Goal:** one sentence.
**Architecture:** 2-3 sentences.
**Tech stack:** versions, test runner, shell.
**Spec:** path (omit if the design is in this file).
## Global constraints
- exact values copied from the spec: version floors, dependency limits, names, formats
## Waves
| Wave | Tasks (parallel) |
|---|---|
| 1 | T1, T2 |
| 2 | T3 (imports T1) |
```

Global constraints apply to every task. Task briefs point the implementer here, so do not repeat them per task.

## Task template

```markdown
### Task N: <name>
**Files:** create `src/x.py`; modify `src/y.py` (what changes); test `tests/test_x.py`
**Interfaces:**
- Consumes: `y.parse(text: str) -> tuple[dict, str]` (Task 1)
- Produces: `x.render(md: str, *, safe: bool = False) -> str`
**Tests:**
- `test_render_escapes_html`: `render("<b>")` returns `"<p>&lt;b&gt;</p>"`
- `test_render_empty`: `render("")` returns `""`
**Notes:** only non-obvious algorithm detail (a tie-break rule, an ordering). Code only when prose would be ambiguous.
**Wave:** 1
```

- **Files:** exact paths, and only the ones this task owns.
- **Interfaces:** exact names, parameter types and return types. An implementer reads only its own task, so this is how it learns what neighbors named things.
- **Tests:** each test by name, with the behavior it asserts and exact inputs and outputs. Include the error and edge cases the spec implies (empty input, bad syntax, boundary values), not only the happy path. "Tests for the above" is a plan failure.
- **Notes:** omit the line when there is nothing non-obvious.

## Assign waves

These are the orchestrator rules. Apply them to every task.

- A wave is a set of tasks that share no files and need none of each other's output.
- A task waits for an earlier task if its code or tests import that task's files, or if it documents what that task built.
- A task that needs only a name from an earlier task (a route path, a CLI flag) and whose own tests do not run that code goes in the same wave. List the name in both tasks' Interfaces.
- At most 5 tasks per wave. Split a larger wave in two.
- Disjoint files share one checkout. If two same-wave tasks might touch one file, move one to the next wave.

Integration tasks (the layer that wires the modules together) are usually the last wave.

## No placeholders

These are plan failures: "TBD", "TODO", "add error handling", "handle edge cases", "similar to Task N", a test without a name and an asserted value, or a type or function that no task defines.

## Self-review checklist

Run it yourself, as a checklist and not a subagent. Fix problems in place, with no re-review.

1. **Coverage:** every spec requirement maps to a task. Add the missing task.
2. **Placeholders:** none from the list above.
3. **Type consistency:** every name and signature in a Consumes line matches the Produces line of the task that defines it. `clearLayers` in Task 3 and `clearFullLayers` in Task 7 is a bug.
4. **Wave conflicts:** no two same-wave tasks share a file or an import. No wave has more than 5 tasks.

## Handoff

Do not ask about an execution method. The default is `superlite:subagent-driven-development`, which has its own inline mode for small plans. If called from brainstorming, return to it for the single approval. Otherwise give the path and wait for the user's go-ahead, unless they pre-approved (then record any open choice as `Ruling: ...` and proceed).

## Red flags

| Thought | Reality |
|---|---|
| "I'll paste the full code so Sonnet can't go wrong" | Contracts and tests constrain it. Code is for non-obvious algorithms only. |
| "Task 5 can be sequential, to be safe" | If the rules allow a shared wave, use it. Needless sequencing is the slow path. |
| "Tests: cover the parser" | Name each test and the exact value it asserts. |
| "Its README can go in wave 1" | Docs wait for the code they describe. |
