---
name: using-superlite
description: Use when starting any conversation - explains superlite, how to size a request, and which skill fits which task
---

Superlite: one approval gate, parallel work, short reports.

**Size the request first.**
- Trivial: just do it.
- Bounded (change to an existing flow): short design in chat, one approval, then build.
- Architectural: batched questions (one AskUserQuestion, up to 4), one combined design+plan doc, one approval.

After approval, stop only for destructive, outward-facing or security-sensitive actions. If the user is away, the gate is pre-approved: record rulings and proceed.

**Skill map**
- build -> superlite:brainstorming
- plan -> superlite:writing-plans
- execute -> superlite:subagent-driven-development
- bug -> superlite:systematic-debugging
- tests first -> superlite:test-driven-development
- claim done -> superlite:verification-before-completion
- finish -> superlite:finishing-a-development-branch

**Builds with 2+ tasks always run through `superlite:subagent-driven-development`;** load it before writing the plan. Never use `general-purpose` agents for build or review work. Build inline only when small (a few files, one chain), and say so.

**Final review always applies.** A non-trivial build ends with a fresh `superlite:final-reviewer` reading the review packet built from the logs, before you claim done.

**Tools.** Run them as `bash <skill-dir>/../subagent-driven-development/scripts/sl <tool>`, never `python`. Incidents go to `.superlite/incidents.jsonl`; Graphify only if `sl graphify_gate` allows.

**Platform adaptation.** Off Claude Code, read the matching `references/<harness>-tools.md` next to this skill (antigravity, codex, gemini, hermes, muse, pi; claude-code for notes). It maps tool names and says how to run `agents/*.md` without plugin agents.
