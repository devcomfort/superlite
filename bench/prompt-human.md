Build the project described in SPEC.md in this directory (the current working directory is the project root; work only inside it).

Use your installed development-workflow skills the way you normally would for a new project of this size: design, plan, implement with tests, review, and finish.

How to execute is your call, based on your own judgment of the task's complexity, but lean toward orchestration: an orchestrator dispatching subagents, in parallel where the work allows. Build everything inline in one context only if you judge the task small enough that orchestration would not pay off, and say so. Either way, finish with a code review by a separate reviewer before you finish, and fix what it finds.

A product owner is available, but only between your turns. When you need a decision, an approval or a clarification, put your question or questions in your final message and end your turn. Their answer arrives as the next message. Do not push anywhere. Commit your work to git in this directory.

The work is done when every requirement in SPEC.md is implemented, `uv run pytest` passes, and everything is committed. Only then, end your final message with the line:
BENCHMARK-COMPLETE
