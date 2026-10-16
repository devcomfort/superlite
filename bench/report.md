# Benchmark report: superpowers 6.4.1 vs superlite 0.1.0

**Date:** 2026-10-16 · **Task:** build `sitegen` from `bench/task/SPEC.md` (9 modules, stdlib Python) · **Reps:** 1 per arm

## Results

| | superpowers 6.4.1 | superlite 0.1.0 | superlite vs superpowers |
|---|---|---|---|
| Wall-clock | 2,062 s (34.4 min) | **527 s (8.8 min)** | **3.9× faster** |
| Hidden acceptance tests | 89 / 89 | 89 / 89 | same |
| Own tests written | 298 | 208 | −30% |
| Stops-for-human (auto-resumes) | 0 | 0 | same |
| Cost (API-equivalent) | **$24.44** | $29.52 | +21% |
| Opus cost (coordinator + Opus agents) | $19.29 | $13.79 | −29% |
| Sonnet cost (workers) | $5.15 | $15.72 | +205% |
| Haiku cost | none | $0.01 | |
| Coordinator turns | 68 | 46 | −32% |
| Coordinator tool calls | 61 | 36 | −41% |
| Subagent dispatches (by model) | 21 (16 Sonnet, 5 Opus) | 10 (8 Sonnet, 2 Haiku) | −52% |
| Source lines / commits | 1,192 / 14 | 1,075 / 12 | |

Raw data: `bench/results/<arm>-1.json`. Stream logs (git-ignored) live in `bench/results/*.jsonl`.

## What the numbers say

1. **Speed: superlite delivered.** It finished in about a quarter of the time at identical hidden-test quality. Superpowers dispatched 21 agents one after another (implementer, then reviewer, per task). Superlite dispatched 10 in parallel waves.
2. **Cost: superlite moved spend instead of cutting it.** Opus spend fell 29%. That's what the plan aimed for: contracts instead of full code in the plan, fewer coordinator turns, and no Opus final reviewer. But Sonnet spend tripled (651K output tokens vs 194K, 3.2M cache writes vs 1.1M). In superpowers, Opus writes the code into the plan and Sonnet transcribes it. In superlite, Sonnet implementers design and write the code from contracts, and each fresh parallel agent warms its own cache.
3. **Quality: equal on this task.** Both arms scored 89/89. Superpowers wrote 43% more tests of its own, which is consistent with its per-task TDD and review gates. The hidden suite didn't separate them, so this task can't tell whether those extra tests catch more bugs.

## Caveats

- **n = 1 per arm.** Superpowers' own data puts run-to-run variance mostly in review-loop counts, so timing could move ±30%.
- **The arms overlapped.** Superpowers ran 02:38–03:12, and superlite ran 03:00–03:09, entirely inside that window, sharing rate limits. Each arm's wall-clock is probably inflated somewhat. Superpowers was the one running alone for its first 22 minutes.
- **Costs are API-equivalent** (`total_cost_usd`). On a subscription they show up as usage-limit consumption, but the ratios still hold.
- **Same environment for both arms:** Opus coordinator, `--permission-mode auto`, the user-level orchestrator skill disabled, and the user's Sonnet subagent default and Haiku Explore/test-runner overrides active. Superpowers' Opus dispatches were explicit `model: opus` calls from its own skills.
- The hidden suite (89 tests) was written independently of the reference implementation, and the two agreed 89/89 on the first run. It checks SPEC conformance, not code quality or robustness beyond the SPEC.

## Next steps for superlite 0.2 (cost)

1. **Cut implementer output.** Try implementer effort `low` for contract tasks, and tighten the "Tests" section of writing-plans so Sonnet doesn't over-produce tests (208 own tests vs 89 hidden).
2. **Fewer, larger worker contexts.** Give each implementer 2 related modules per brief, so there are fewer fresh caches to warm (10 → about 6 dispatches).
3. **Investigate the coordinator's 20M Opus cache-read tokens over 46 turns.** That's a large context being re-sent each turn. Find what the coordinator read in the stream log and push that reading into workers.
4. **Re-run with 2–3 reps per arm, sequentially,** to firm up the speed ratio and the cost delta.
