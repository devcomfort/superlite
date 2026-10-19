---
description: Stop dispatching new superlite tasks cleanly and report where the build stands.
argument-hint: ""
---

Stop the build cleanly. Dispatch no new tasks. Let running agents finish (do not kill processes). Commit nothing half-done; leave uncommitted work untouched. Write a short note to `.superlite/stopped.md` with: tasks committed, tasks running or unfinished, and the command to continue (`/superlite:resume`). Report the same in under 10 lines.
