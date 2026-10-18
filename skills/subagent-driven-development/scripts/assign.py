#!/usr/bin/env python3
"""Pick the idle agent for a task from the task graph and each agent's history.

    assign.py --task Tn --pool .superlite/pool.json [--plan P]

stdout is one word: `agent=<id>` (clear winner), `poll` (tie or no signal, ask
the eligible idle agents), or `fresh` (no eligible idle agent). Ineligible
agents are listed on stderr as `evict=<id> <reason>`.

pool.json: {"plan": "path (optional)", "agents": [{"id": "a1",
  "tasks": ["T1"], "files": ["src/x.py"], "context_k": 30, "idle_min": 5,
  "busy": false}]}

Scoring (D11): +5 if the agent built a task this one depends on, +3 per owned
or read file this task touches, +1 for the same package (directory). A winner
needs a margin of at least 3. Eligible: context_k + Est. context <= 80, fewer
than 3 tasks done, idle <= 50 min. Busy agents are never candidates.
"""
import argparse
import json
import posixpath
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import next_tasks as nt  # noqa: E402

MAX_CONTEXT_K = 80.0
MAX_TASKS = 3
MAX_IDLE_MIN = 50.0
MARGIN = 3
DEFAULT_CONTEXT_K = 20.0


def package(path):
    return posixpath.dirname(path.replace("\\", "/"))


def eligibility(agent, est_context):
    """None when eligible, else a short reason."""
    if float(agent.get("context_k", 0)) + est_context > MAX_CONTEXT_K:
        return "context over 80k"
    if len(agent.get("tasks", [])) >= MAX_TASKS:
        return "3 tasks done"
    if float(agent.get("idle_min", 0)) > MAX_IDLE_MIN:
        return "idle over 50 min"
    return None


def score(agent, task_id, deps, owns, info):
    s = 0
    built = set(agent.get("tasks", []))
    if built & set(deps):
        s += 5
    files = {f.replace("\\", "/") for f in agent.get("files", [])}
    for t in built:
        files.update(info.get(t, {}).get("owns", []))
    s += 3 * sum(1 for o in owns if any(nt.owns_match(f, [o]) for f in files))
    pkgs = {package(f) for f in files if package(f)}
    if any(package(o) in pkgs for o in owns if package(o)):
        s += 1
    return s


def decide(scores):
    """scores: {id: score} of eligible agents -> 'agent=<id>' | 'poll' | 'fresh'."""
    if not scores:
        return "fresh"
    ranked = sorted(scores.values(), reverse=True)
    top = ranked[0]
    second = ranked[1] if len(ranked) > 1 else 0
    if top > 0 and top - second >= MARGIN:
        winner = [k for k, v in scores.items() if v == top][0]
        return f"agent={winner}"
    return "poll"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--task", required=True)
    ap.add_argument("--pool", default=".superlite/pool.json")
    ap.add_argument("--plan")
    a = ap.parse_args(argv)
    pool_path = Path(a.pool)
    pool = json.loads(pool_path.read_text(encoding="utf-8")) if pool_path.exists() \
        else {"agents": []}
    plan = a.plan or pool.get("plan") or nt.DEFAULT_PLAN
    graph = nt.taskgraph(plan)
    info = nt.parse_plan(plan)
    if a.task not in graph and a.task not in info:
        nt.die(f"unknown task {a.task}")
    task = info.get(a.task, {})
    deps = graph.get(a.task, [])
    owns = task.get("owns", [])
    est_context = task.get("est_context") or DEFAULT_CONTEXT_K
    scores = {}
    for agent in pool.get("agents", []):
        if agent.get("busy") or agent.get("status") == "busy":
            continue
        why = eligibility(agent, est_context)
        if why:
            print(f"evict={agent['id']} {why}", file=sys.stderr)
            continue
        scores[agent["id"]] = score(agent, a.task, deps, owns, info)
    print(decide(scores))
    return 0


if __name__ == "__main__":
    sys.exit(main())
