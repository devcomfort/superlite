---
description: Add or change a feature in an existing codebase. Reads the code first, checks the seams.
argument-hint: "[the change you want]"
---

Superlite feature mode. Request: $ARGUMENTS

If the request is empty, ask for it in one line. Then:

- Ask the orchestrator choice (human or AI) unless the user already said; run `sl orchestrator set human|ai`.
- Read before designing: find the files and tests the change touches, and follow the project's own conventions and toolchain. Offer Graphify only if `sl graphify_gate` allows, and never install it without the user's yes.
- Load `superlite:brainstorming`, then `superlite:subagent-driven-development`.
- Scope rules for this mode: change only what the request needs. Name the existing interfaces the new code must keep (FROZEN in the plan) and add seam checks between new and existing code. Existing tests must still pass.
