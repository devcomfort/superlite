---
description: Approve the review plan so superlite can lint and build it.
argument-hint: "[path to the .review.md]"
---

Approve the human review plan. Arguments: $ARGUMENTS
Use the given path, else the newest `docs/plans/*.review.md`. Show the user a five-line summary of what they are approving and ask only if the intent is unclear. Run `sl orchestrator approve --review <path>`; it needs the user approving reply to be newer than the review file (exit 3 otherwise: tell the user to reply "approve" first). After it succeeds, rewrite the plan in the agent format, lint it, and start the build.
