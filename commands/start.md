---
description: Start a superlite session. Pick the mode (regular, MVP, feature, debug) and who orchestrates.
argument-hint: "[regular|mvp|feature|debug] [what you want]"
---

Start a superlite session. Arguments: $ARGUMENTS

1. If the first word of the arguments is `regular`, `mvp`, `feature` or `debug`, that is the mode; the rest is the request. Otherwise the mode is unset.
2. Ask what is still unset, in ONE AskUserQuestion (up to 2 questions):
   - Mode, if unset: Regular (size the request, then brainstorm, plan, build, review), MVP (smallest working version first), Feature (a change to existing code), Debug (find the cause, fix with a regression test).
   - Orchestrator, always unless the user already said: Human (you approve a plain-language review plan before anything is built) or AI (hands off). Then run `sl orchestrator set human|ai`.
3. If there is no request text yet, ask for it in one line.
4. Load the skill for the mode and follow it:
   - Regular: `superlite:using-superlite` sizing, then `superlite:brainstorming`.
   - MVP: same as `/superlite:mvp`.
   - Feature: same as `/superlite:feature`.
   - Debug: same as `/superlite:debug`.
