---
name: using-superlite
description: Use when starting any conversation - explains superlite, how to size a request, and which skill fits which task
---

Superlite is a lean build lifecycle: one approval gate, parallel waves, short reports.

**Size the request first.**
- Trivial (a few tool calls): just do it.
- Bounded (change to an existing flow): short design in chat, one approval, then build.
- Architectural: batched questions (one AskUserQuestion, up to 4), one combined design+plan doc, one approval.

After approval, stop only for destructive, outward-facing (push, merge, publish) or security-sensitive actions. If the user is away or says "decide yourself", the gate is pre-approved: record rulings and proceed.

**Skill map**
- build -> superlite:brainstorming
- plan -> superlite:writing-plans
- execute -> superlite:subagent-driven-development
- bug -> superlite:systematic-debugging
- tests first -> superlite:test-driven-development
- claim done -> superlite:verification-before-completion
- finish -> superlite:finishing-a-development-branch

Invoke a skill only when the task matches it. Conversation and trivial edits need none. **Lean toward orchestration:** for a non-trivial build, plan waves and dispatch subagents in parallel. Build inline only when you judge the task small (a few files, one dependency chain), and say so.

**Final review always applies.** Any non-trivial build, inline or in waves, ends with one fresh `superlite:reviewer` in final mode on your own model tier (opus, effort high) before you claim done. It re-derives requirements from the spec and runs the robustness checklist with real probes.

**Platform adaptation.** Off Claude Code, read the matching `references/<harness>-tools.md` next to this skill (antigravity, codex, gemini, hermes, muse, pi; claude-code for notes). It maps tool names and says how to run `agents/*.md` without plugin agents.
