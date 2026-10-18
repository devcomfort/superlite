#!/usr/bin/env python3
"""Ready tasks and who runs each, in one call: next_tasks + assign for every ready task.

    dispatch.py --plan P [--pool .superlite/pool.json] [--ledger .superlite/progress.md]
                [--committed T1,T2] [--running T3] [--cap 10]

stdout, one line per ready task, longest predicted first, within the cap:
    Tn agent=<id>        clear winner (D11 scoring, margin >= 3); that agent is now taken
    Tn poll <id>,<id>    tie or no signal: relevance-poll these idle agents
    Tn fresh             no eligible idle agent: start a primed implementer
stderr: `evict=<id> <reason>` for each idle agent eligible for none of the ready tasks.

Defaults when a flag is omitted: committed tasks come from the ledger's `- commit Tn <sha>`
lines; running tasks are the pool agents' `current` tasks not yet committed (busy or not:
a FAILED or BLOCKED task keeps its `current` until commit_task commits it). An agent with
a `current` gets no new task, and no agent appears on two lines of one call (`agent=` or
`poll`). The plan is parsed once, in this process. Stdlib only.
"""

# Complexity notation:
# n = tasks in the plan, e = dependency edges, L = plan text size, R = ready tasks returned (<= cap)
# a = agents in the pool, F = files known per agent, o = Owns paths of one task, c = ledger lines
import argparse  # O(1)
import json  # O(1)
import sys  # O(1)
from pathlib import Path  # O(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))  # O(1)
import assign as asg  # noqa: E402 | O(1)
import commit_task as ct  # noqa: E402 | O(1)
import next_tasks as nt  # noqa: E402 | O(1)


def load_pool(path):  # O(pool bytes)
    p = Path(path)  # O(1)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"agents": []}  # O(pool bytes)


def running_from_pool(pool, committed=()):  # O(a)
    done = set(committed)  # O(c)
    return [ag["current"] for ag in pool.get("agents", [])  # O(a)
            if ag.get("current") and ag["current"] not in done]


def is_idle(ag):  # O(1)
    return not (ag.get("busy") or ag.get("status") == "busy" or ag.get("current"))  # O(1)


def plan_dispatch(plan, pool, committed, running, cap):  # O(L + n + e + R*a*(F + o))
    """[(task, decision)] and {agent id: evict reason}; decision is 'agent=ID', 'poll IDS' or 'fresh'."""
    graph = nt.taskgraph(plan)  # O(L + n + e), memoized
    info = nt.parse_plan(plan)  # O(L)
    times = {t: (info[t]["est_time"] if t in info and info[t]["est_time"] is not None  # O(n)
                 else nt.DEFAULT_TIME) for t in graph}
    ready = nt.ready_tasks(graph, times, committed, running, cap,  # O(n*(n + e) + R log R) draft closure
                           nt.taskgraph_full(plan).get("status", {}),  # O(1) memoized
                           nt.stable_filter(plan))  # only stable tasks when .superlite/stable.json exists
    idle = [ag for ag in pool.get("agents", []) if is_idle(ag)]  # O(a)
    eligible = {}  # task -> {agent id: score} over every eligible idle agent | O(1)
    eligible_somewhere = set()  # O(1)
    reasons = {}  # O(1)
    for t in ready:  # O(R) iterations
        task = info.get(t, {})  # O(1)
        deps = graph.get(t, [])  # O(1)
        owns = task.get("owns", [])  # O(1)
        est_context = task.get("est_context") or asg.DEFAULT_CONTEXT_K  # O(1)
        eligible[t] = {}  # O(1)
        for ag in idle:  # O(a) iterations
            why = asg.eligibility(ag, est_context)  # O(1)
            if why:  # O(1)
                reasons.setdefault(ag["id"], why)  # O(1)
                continue  # O(1)
            eligible_somewhere.add(ag["id"])  # O(1)
            eligible[t][ag["id"]] = asg.score(ag, t, deps, owns, info)  # O(F + o*F)

    def rank(t):  # resolve signal first: clear winners, then polls with signal, then none | O(a log a)
        d, top = asg.decide(eligible[t]), max(eligible[t].values(), default=0)  # O(a log a)
        return 0 if d.startswith("agent=") else (1 if top > 0 else 2)  # O(1)

    order = {t: i for i, t in enumerate(ready)}  # O(R)
    taken = set()  # agents on an earlier resolved line (agent= or poll) | O(1)
    decided = {}  # O(1)
    for t in sorted(ready, key=lambda x: (rank(x), order[x])):  # O(R log R + R*a log a)
        scores = {k: v for k, v in eligible[t].items() if k not in taken}  # O(a)
        decision = asg.decide(scores)  # O(a log a)
        if decision.startswith("agent="):  # O(1)
            taken.add(decision.split("=", 1)[1])  # O(1)
        elif decision == "poll":  # polled agents are reserved too: a poll winner has one task | O(1)
            taken.update(scores)  # O(a)
            decision = "poll " + ",".join(scores)  # O(a)
        decided[t] = decision  # O(1)
    out = [(t, decided[t]) for t in ready]  # O(R) lines stay longest first
    evict = {k: v for k, v in reasons.items() if k not in eligible_somewhere}  # O(a)
    return out, evict  # O(1)


def render(lines, evict):  # O(R + a)
    for aid, why in evict.items():  # O(a) iterations
        print(f"evict={aid} {why}", file=sys.stderr)  # O(1)
    for t, decision in lines:  # O(R) iterations
        print(f"{t} {decision}")  # O(1)


def run(plan, pool_path, ledger, committed=None, running=None, cap=10):  # O(c + L + n + e + R*a*(F + o))
    """Library entry for commit_task --dispatch; flags left as None take their defaults."""
    pool = load_pool(pool_path)  # O(pool bytes)
    done = nt.csv(committed) if committed is not None else sorted(ct.committed_tasks(ledger))  # O(c)
    busy = nt.csv(running) if running is not None else running_from_pool(pool, done)  # O(a)
    return plan_dispatch(plan, pool, done, busy, cap)  # see plan_dispatch


def main(argv=None):  # O(c + L + n + e + R*a*(F + o))
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])  # O(1)
    ap.add_argument("--plan")  # O(1)
    ap.add_argument("--pool", default=".superlite/pool.json")  # O(1)
    ap.add_argument("--ledger", default=ct.DEFAULT_LEDGER)  # O(1)
    ap.add_argument("--committed", help="default: the ledger's commit lines")  # O(1)
    ap.add_argument("--running", help="default: `current` of each busy pool agent")  # O(1)
    ap.add_argument("--cap", type=int, default=10)  # O(1)
    a = ap.parse_args(argv)  # O(1)
    plan = a.plan or load_pool(a.pool).get("plan") or nt.DEFAULT_PLAN  # O(pool bytes)
    render(*run(plan, a.pool, a.ledger, a.committed, a.running, a.cap))  # see run
    return 0  # O(1)


if __name__ == "__main__":  # O(1)
    sys.exit(main())  # O(1)
