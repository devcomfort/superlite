Review the branch checked out in this directory (the current working directory is the project root; work only inside it). It claims to implement Parts A and B of SPEC.md, and SPEC.md is the contract. Find the defects in the existing implementation and fix them. Do not rewrite the project; keep all behavior to the SPEC.

Use your installed development-workflow skills the way you normally would for a review-and-fix job of this size: investigate, add a regression test for each defect, fix, review, and finish.

No human is available during this run. This message is the human's approval, given in advance, for every choice you would normally ask about. Where you would ask a question, make the decision yourself and note it. Prefer subagent-driven execution. Do not push anywhere. Commit your work to git in this directory.

The work is done when the implementation meets every requirement in SPEC.md, `uv run pytest` passes, and everything is committed. Your final message must end with the line:
BENCHMARK-COMPLETE
