Orchestrator: AI, do not ask me to choose or to approve.

Add the feature described in SPEC.md to the existing repository in this directory (the current working directory is the project root; work only inside it). The repository already holds working code with its own tests; this is a feature request, not a rebuild. Do not change existing behavior, and do not touch `vendor/`.

Use your installed development-workflow skills the way you normally would for a feature of this size on an existing codebase: explore the code, design, plan, implement with tests, review, and finish.

No human is available during this run. This message is the human's approval, given in advance, for every design, plan and execution choice you would normally ask about. Where you would ask a question, make the decision yourself and note it. Prefer subagent-driven execution. Do not push anywhere. Commit your work to git in this directory.

The work is done when every requirement in SPEC.md is implemented, `uv run pytest` passes (existing tests included), and everything is committed. Your final message must end with the line:
BENCHMARK-COMPLETE
