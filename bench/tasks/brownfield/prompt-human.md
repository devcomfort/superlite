Add the feature described in SPEC.md to the existing repository in this directory (the current working directory is the project root; work only inside it). The repository already holds working code with its own tests; this is a feature request, not a rebuild. Do not change existing behavior, and do not touch `vendor/`.

Use your installed development-workflow skills the way you normally would for a feature of this size on an existing codebase: explore the code, design, plan, implement with tests, review, and finish.

How to execute is your call, based on your own judgment of the task's complexity, but lean toward orchestration: an orchestrator dispatching subagents, in parallel where the work allows. Build everything inline in one context only if you judge the task small enough that orchestration would not pay off, and say so. Either way, finish with a code review by a separate reviewer, and fix what it finds.

A product owner is available, but only between your turns. When you need a decision, an approval or a clarification, put your question or questions in your final message and end your turn. Their answer arrives as the next message. Do not push anywhere. Commit your work to git in this directory.

The work is done when every requirement in SPEC.md is implemented, `uv run pytest` passes (existing tests included), and everything is committed. Only then, end your final message with the line:
BENCHMARK-COMPLETE
