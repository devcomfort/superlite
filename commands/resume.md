---
description: Resume an interrupted superlite build from the last committed, tested wave.
argument-hint: "[plan path]"
---

Resume a superlite build. Arguments: $ARGUMENTS
1. Find the plan (the argument, else the newest in docs/plans) and read `.superlite/` state and `git log` to see which tasks are committed and tested.
2. Load `superlite:subagent-driven-development` and continue from the ready queue. Never redo a committed, passing task; re-run only tasks that were running or untested.
3. Report in two lines what was already done and what will run now. Respect the orchestrator choice and the human approval gate.
