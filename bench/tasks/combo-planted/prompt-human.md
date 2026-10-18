Review the branch checked out in this directory (the current working directory is the project root; work only inside it). It claims to implement Parts A and B of SPEC.md, and SPEC.md is the contract. Find the defects in the existing implementation and fix them. Do not rewrite the project; keep all behavior to the SPEC.

Use your installed development-workflow skills the way you normally would for a review-and-fix job of this size: investigate, add a regression test for each defect, fix, review, and finish.

How to execute is your call, based on your own judgment of the task's complexity, but lean toward orchestration: an orchestrator dispatching subagents, in parallel where the work allows. Build everything inline in one context only if you judge the task small enough that orchestration would not pay off, and say so. Either way, finish with a review by a separate reviewer, and fix what it finds.

A product owner is available, but only between your turns. When you need a decision, an approval or a clarification, put your question or questions in your final message and end your turn. Their answer arrives as the next message. Do not push anywhere. Commit your work to git in this directory.

The work is done when the implementation meets every requirement in SPEC.md, `uv run pytest` passes, and everything is committed. Only then, end your final message with the line:
BENCHMARK-COMPLETE
