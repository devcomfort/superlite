"""Compact report on tasks by (agent type, model) group across runs: first-time pass, rework, time, cost, slack.

    python bench/report_mechanical.py bench/results/combo-superlite-x1.mechanical.json bench/results/*.json
    python bench/report_mechanical.py --history ~/.superlite/history.jsonl [--focus opus,haiku] [--baseline sonnet]

Each input is a score JSON (or a `<name>.mechanical.json`) with `tasks` and `mechanical` keys, as
`harness.py score` / `harness.py rescore-tasks <arm> <rep>` write them; `--history` reads the append-only
history store instead (see bench/history_import.py). Prints one row per (run, group), a per-task table for the
focus groups (default: every model except the baseline, which is Sonnet unless the run says otherwise), the
misses, pool honesty, and a combined summary. Counterfactual columns are ESTIMATES that re-price tokens only."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import taskmetrics as tm  # noqa: E402


def load(paths: list[str]) -> list[dict]:
    runs = []
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        if "mechanical" not in d:
            continue
        runs.append({"run": d.get("run") or Path(p).stem.replace(".mechanical", ""), "tasks": d.get("tasks") or [],
                     "mechanical": d["mechanical"]})
    return runs


def _f(x, nd=1, pre=""):
    return "-" if x is None else f"{pre}{x:.{nd}f}" if isinstance(x, float) else f"{pre}{x}"


def table(rows: list[list], header: list[str]) -> str:
    cells = [header] + [[str(c) for c in r] for r in rows]
    w = [max(len(r[i]) for r in cells) for i in range(len(header))]
    line = lambda r: "| " + " | ".join(c.ljust(w[i]) for i, c in enumerate(r)) + " |"  # noqa: E731
    return "\n".join([line(cells[0]), "|" + "|".join("-" * (x + 2) for x in w) + "|"] + [line(r) for r in cells[1:]])


def baseline_of(r: dict, override: str | None = None) -> str:
    return override or r["mechanical"].get("baseline") or "sonnet"


def _group(t: dict) -> str:
    return t.get("group") or f"{t.get('agent_type') or 'agent'}:{t.get('model')}"


def groups_of(r: dict) -> dict[str, dict]:
    """Group stats of a run: the stored `groups`, else computed from the task records (older score JSONs)."""
    g = r["mechanical"].get("groups")
    if g:
        return g
    by: dict[str, list[dict]] = {}
    for t in r["tasks"]:
        by.setdefault(_group(t), []).append(t)
    return {k: tm.group_stats(v) for k, v in sorted(by.items())}


def is_focus(t: dict, base: str, focus: set[str] | None) -> bool:
    return (t.get("model") in focus) if focus else t.get("model") != base


def run_rows(r: dict, base: str, focus: set[str] | None) -> list[list]:
    m = r["mechanical"]
    cf = m.get("counterfactual") or m.get("counterfactual_sonnet") or {}
    rows = []
    for label, g in groups_of(r).items():
        model = label.rsplit(":", 1)[-1]
        mark = "" if (model in focus if focus else model != base) else "(baseline) "
        rows.append([r["run"], label, g["tasks"], f"{g['first_time_pass']}/{g['observed']}", _f(g["rework_cost_usd"], 3, "$"),
                     _f(g["time_s"]), _f(g["cost_usd"], 3, "$"), g.get("on_critical_path", "-"), _f(g.get("slack_s_mean")),
                     (mark + ("incomplete: " + ",".join(g["incomplete"]) if g["incomplete"] else "")).strip()])
    if not rows or m.get("note"):
        rows.append([r["run"], "-", 0, "-", "-", "-", "-", "-", "-", m.get("note") or "no tasks"])
    if cf:
        rows.append([r["run"], f"cf: subject -> {cf.get('baseline', 'sonnet')}*", len(cf.get("tasks", [])), "-", "-",
                     _f(cf.get("sum_task_time_saved_s")), _f(cf.get("saves_cost_usd", cf.get("haiku_saves_cost_usd")), 3, "$"),
                     "-", "-", f"run end {_f(cf.get('critical_path_saved_s'))} s later on baseline"])
    return rows


def summary(runs: list[dict], base: str | None = None, focus: set[str] | None = None) -> dict:
    allt = [(r, t) for r in runs for t in r["tasks"]]
    hk = [t for _, t in allt if t.get("model") == "haiku"]
    sn = [t for _, t in allt if t.get("model") == "sonnet"]
    obs = [t for t in hk if t.get("first_time_pass") is not None]
    cfs = [r["mechanical"].get("counterfactual") or r["mechanical"].get("counterfactual_sonnet") for r in runs]
    cfs = [c for c in cfs if c]
    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None  # noqa: E731
    by: dict[str, list[dict]] = {}
    for _, t in allt:
        by.setdefault(_group(t), []).append(t)
    return {
        "baseline": base or "sonnet",
        "groups": {k: tm.group_stats(v) for k, v in sorted(by.items())},
        "runs": len(runs), "runs_with_haiku": sum(1 for r in runs if any(t.get("model") == "haiku" for t in r["tasks"])),
        "haiku_tasks": len(hk), "observed": len(obs), "first_time_pass": sum(1 for t in obs if t["first_time_pass"]),
        "first_time_pass_rate": round(sum(1 for t in obs if t["first_time_pass"]) / len(obs), 3) if obs else None,
        "rework_cost_usd": round(sum(t.get("rework_cost") or 0 for t in hk), 4),
        "rework_s": round(sum(t.get("rework_s") or 0 for t in hk), 1),
        "haiku_cost_usd": round(sum(t.get("cost_usd") or 0 for t in hk), 4),
        "needs_context_or_blocked": sum(1 for t in hk if t.get("status") in ("NEEDS_CONTEXT", "BLOCKED")),
        "tool_calls_per_haiku_task": avg([t["tool_calls"] for t in hk]),
        "tool_calls_per_sonnet_task": avg([t["tool_calls"] for t in sn]),
        "pool_violations": sum((r["mechanical"].get("pool") or {}).get("pool_violations", 0) for r in runs),
        "haiku_on_critical_path": sum((r["mechanical"].get("pool") or {}).get("haiku_on_critical_path", 0) for r in runs),
        "cf_cost_saved_usd": round(sum(c.get("saves_cost_usd", c.get("haiku_saves_cost_usd", 0)) for c in cfs), 4),
        "cf_critical_path_saved_s": round(sum(c["critical_path_saved_s"] or 0 for c in cfs), 1),
    }


def render(runs: list[dict], baseline: str | None = None, focus: set[str] | None = None) -> str:
    rows = [row for r in runs for row in run_rows(r, baseline_of(r, baseline), focus)]
    out = ["## Per run and group (agent type:model)",
           table(rows, ["run", "group", "tasks", "1st-pass", "rework$", "time_s", "cost$", "crit", "slack_s", "note"])]
    trows = []
    for r in runs:
        base = baseline_of(r, baseline)
        for t in r["tasks"]:
            if is_focus(t, base, focus):
                trows.append([r["run"], t["task"], _group(t), t.get("kind"), t.get("loc"), t.get("dispatches"),
                              _f(t.get("duration_s")), t["tokens"]["in"] + t["tokens"]["cache_read"] + t["tokens"]["cache_write"],
                              t["tokens"]["out"], _f(t.get("cost_usd"), 4, "$"), t.get("tool_calls"), t.get("status") or "(none)",
                              {True: "yes", False: "NO", None: "n/a"}[t.get("first_time_pass")],
                              _f(t.get("rework_s")), _f(t.get("rework_cost"), 4, "$"),
                              {True: "yes", False: "no", None: "-"}[t.get("on_critical_path")], _f(t.get("slack_s")),
                              _f(t.get("start_lag_s"))])
    out += ["", "## Tasks of the focus groups (every model except the baseline unless --focus)",
            table(trows, ["run", "task", "group", "kind", "loc", "disp", "dur_s", "ctx tok", "out tok~", "cost", "tools", "status",
                          "1st-pass", "rework_s", "rework$", "crit", "slack_s", "lag_s"]) if trows else "(none)"]
    miss = [(r["run"], t) for r in runs for t in r["tasks"] if is_focus(t, baseline_of(r, baseline), focus) and t.get("first_time_pass") is False]
    unobs = [f"{r['run']} {t['task']}" for r in runs for t in r["tasks"] if is_focus(t, baseline_of(r, baseline), focus) and t.get("first_time_pass") is None]
    n_f = sum(1 for r in runs for t in r["tasks"] if is_focus(t, baseline_of(r, baseline), focus))
    out += ["", f"## Misses: {len(miss)} of {n_f} focus tasks failed first time" + (f" (unobserved: {', '.join(unobs)})" if unobs else "")]
    if miss:
        def why(t):
            st = (t.get("status") or "").upper()
            return st if st in ("NEEDS_CONTEXT", "BLOCKED") else ("red tests" if t.get("kind_miss_incidents") or t.get("rework_dispatches") else "wrong output")
        out.append(table([[r, t["task"], _group(t), why(t), (t.get("status_reason") or "")[:70], t.get("rework_dispatches"),
                           _f(t.get("rework_s")), _f(t.get("rework_cost"), 4, "$")] for r, t in miss],
                         ["run", "task", "group", "why", "reason", "fixer dispatches", "rework_s", "rework$"]))
    else:
        out.append("(none observed)")
    prow = []
    for r in runs:
        po = r["mechanical"].get("pool")
        if po:
            lag = ", ".join(f"{m}:{v['mean']}s(n={v['n']})" for m, v in sorted(po["start_lag_s_by_model"].items())) or "-"
            outside = "; ".join(f"{v['task']}: planned {v['planned']}, ran on {v['ran_on']}" for v in po.get("violations", [])) or "-"
            prow.append([r["run"], po["pool_violations"], outside, po.get("haiku_on_critical_path", 0),
                         po.get("lane_reuse", po.get("haiku_lane_reuse", 0)), lag, ",".join(po["tier_sources"]) or "-"])
    out += ["", "## Pool honesty (a task ran on an agent outside its planned tier; should be 0)",
            table(prow, ["run", "violations", "outside planned tier", "haiku_on_critical_path", "lane reuse", "start lag by model", "tier from"]) if prow else "(none)"]
    s = summary(runs, baseline, focus)
    out += ["", "## Combined", json.dumps(s, indent=1), "",
            "* COUNTERFACTUAL ESTIMATE, not measured: subject tasks re-priced at the baseline model's prices and re-timed at models.json "
            "output speeds, assuming the baseline passes first time. It re-prices tokens only: a different model also changes the number of steps. "
            "'out tok~' is estimated (the stream's output_tokens is an early snapshot). Unfinished tasks (killed runs) have no status and no first-time-pass."]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--history", help="read the history store (JSONL) instead of score JSONs")
    ap.add_argument("--baseline", help="baseline model (default: what each run recorded, else sonnet)")
    ap.add_argument("--focus", help="comma-separated models to list task by task (default: every model except the baseline)")
    a = ap.parse_args(argv)
    if a.history:
        import history_import
        runs = history_import.runs_from_history(Path(a.history))
    else:
        runs = load(a.paths)
    if not runs:
        print("no score JSON (or history rows) with a `mechanical` block among the inputs", file=sys.stderr)
        return 1
    print(render(runs, a.baseline, set(a.focus.split(",")) if a.focus else None))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
