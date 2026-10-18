Orchestrator: AI, do not ask me to choose or to approve.

Build the project described in SPEC.md, in this (empty) directory. SPEC.md is the contract.

Use your installed development-workflow skills the way you normally would: plan, build, test, review, and finish.

How to execute is your call, based on your own judgment of the task's complexity, but lean toward orchestration: an orchestrator dispatching subagents, in parallel where the work allows. Build everything inline in one context only if you judge the task small enough that orchestration would not pay off, and say so. Either way, finish with a review by a separate reviewer, and fix what it finds.

A product owner is available, but only between your turns. When you need a decision, an approval or a clarification, put your question or questions in your final message and end your turn. Their answer arrives as the next message. Do not push anywhere. Commit your work to git in this directory.

The work is done when the implementation meets every requirement in SPEC.md, `npm install`, `npm run build` and `npm test` succeed, and everything is committed. Only then, end your final message with the line:
BENCHMARK-COMPLETE
