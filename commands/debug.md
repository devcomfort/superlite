---
description: Find the root cause of a bug first, then fix it with a regression test.
argument-hint: "[the bug or failing test]"
---

Superlite debug mode. Problem: $ARGUMENTS

If the problem is empty, ask for it in one line (what fails, how to reproduce). Then load `superlite:systematic-debugging` and follow it: reproduce, find the root cause, write the failing regression test, fix, verify. Fixes go to fix-only agents by tier. Use the project's own test command. Do not widen the change beyond the cause.
