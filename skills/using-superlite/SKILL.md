---
name: using-superlite
description: Use when starting any conversation - explains superlite, how to size a request, and which skill fits which task
---

Superlite: parallel work, short reports.

**Start menu.** On the first user message of a session, if it does not already name a mode and no run is in progress, open with ONE AskUserQuestion built from the "Project state" line: the mode (only the options that fit), then who orchestrates. Skip it for a clear one-line request you can size as trivial, or when the user typed a `/superlite:` command.
- State "run in progress": Resume, Status, Start something new, Finish.
- State "existing code": Feature, Debug, Regular, MVP (a new app beside it), Review.
- State "empty folder": MVP (plan, then a clickable prototype to assess, then build), Regular.
- Orchestrator: Human (you approve a review plan first) or AI (hands off). Run `sl orchestrator set human|ai`, then continue with the matching command's flow (`/superlite:mvp`, `feature`, `debug`, `resume`, `status`, `review`, `finish`).

**Size the request first.**
- Trivial: just do it (human orchestrator: only after an approved review plan).
- Bounded (change to an existing flow): short design in chat, then build.
- Architectural: batched questions (one AskUserQuestion, up to 4), one combined design+plan doc.

**Who orchestrates?** Ask once, in that same batch: human orchestrator (approves the plan before it runs) or AI orchestrator (hands off). Skip it when the request settles it ("decide yourself", user away, pre-approved, headless): AI, as a Ruling. `sl orchestrator set human|ai`. AI stops only for destructive, outward or security-sensitive actions.

**Skill map**
- build -> superlite:brainstorming
- plan -> superlite:writing-plans
- execute -> superlite:subagent-driven-development
- bug -> superlite:systematic-debugging
- tests first -> superlite:test-driven-development
- claim done -> superlite:verification-before-completion
- finish -> superlite:finishing-a-development-branch

**Builds with 2+ tasks always run through `superlite:subagent-driven-development`;** load it before writing the plan. No `general-purpose` agents for build or review. Build inline only when small (a few files, one chain), and say so.

**Final review always applies.** A non-trivial build ends with a fresh `superlite:final-reviewer` reading the review packet, before you claim done.

**Tools.** `bash <skill-dir>/../subagent-driven-development/scripts/sl <tool>`, never `python`. Incidents go to `.superlite/incidents.jsonl`; Graphify only if `sl graphify_gate` allows.

**Platform adaptation.** Off Claude Code, read the matching `references/<harness>-tools.md` next to this skill (antigravity, codex, gemini, hermes, muse, pi). It maps tool names and says how to run `agents/*.md` without plugin agents.
