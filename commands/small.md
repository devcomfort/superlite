---
description: Make a small change inline, with a reviewer, without the full planning flow.
argument-hint: "[the change]"
---

Small change: $ARGUMENTS
Do it inline in a few tool calls and say so; no plan document. Run the focused tests, then dispatch one `superlite:package-reviewer` on the diff before claiming done. If it turns out to span more than a few files or several chains, say so and switch to `/superlite:feature`.
