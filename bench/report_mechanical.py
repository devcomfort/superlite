"""Compact report on mechanical (Haiku) tasks across runs.

    python bench/report_mechanical.py bench/results/combo-superlite-x1.mechanical.json bench/results/*.json

Each input is a score JSON (or a `<name>.mechanical.json`) with `tasks` and `mechanical` keys, as
`harness.py score` / `harness.py rescore-tasks <arm> <rep>` write them. Prints one row per run, a
per-task table of the Haiku tasks, and a combined summary. Counterfactual columns are ESTIMATES."""
from __future__ import annotations

import json
import sys
from pathlib import Path


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


def run_row(r: dict) -> list:
    m = r["mechanical"]
    h = m.get("haiku")
    cf = m.get("counterfactual_sonnet") or {}
    mech = (m.get("by_kind") or {}).get("mechanical") or {}
    if not h:
        return [r["run"], m.get("tasks_built", 0), f"{mech.get('tasks', 0)} ({_f(mech.get('loc_share'), 2)} loc)", 0,
                "-", "-", "-", "-", "-", "-", m.get("note") or "no Haiku tasks"]
    mm = (m.get("mechanical_by_model") or {}).get("haiku") or {}
    return [r["run"], m["tasks_built"], f"{mech.get('tasks', 0)} ({_f(mech.get('loc_share'), 2)} loc)", h["tasks"],
            f"{h['first_time_pass']}/{h['observed']}", _f(h["rework_cost_usd"], 3, "$"), _f(mm.get("time_s")),
            _f(mm.get("cost_usd"), 3, "$"), _f(cf.get("haiku_saves_cost_usd"), 3, "$"), _f(cf.get("critical_path_saved_s")),
            ("incomplete: " + ",".join(h["incomplete"])) if h["incomplete"] else ""]


def summary(runs: list[dict]) -> dict:
    hk = [t for r in runs for t in r["tasks"] if t.get("model") == "haiku"]
    sn = [t for r in runs for t in r["tasks"] if t.get("model") == "sonnet"]
    obs = [t for t in hk if t.get("first_time_pass") is not None]
    cfs = [r["mechanical"].get("counterfactual_sonnet") for r in runs if r["mechanical"].get("counterfactual_sonnet")]
    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None  # noqa: E731
    return {
        "runs": len(runs), "runs_with_haiku": sum(1 for r in runs if r["mechanical"].get("haiku")),
        "haiku_tasks": len(hk), "observed": len(obs), "first_time_pass": sum(1 for t in obs if t["first_time_pass"]),
        "first_time_pass_rate": round(sum(1 for t in obs if t["first_time_pass"]) / len(obs), 3) if obs else None,
        "rework_cost_usd": round(sum(t.get("rework_cost") or 0 for t in hk), 4),
        "rework_s": round(sum(t.get("rework_s") or 0 for t in hk), 1),
        "haiku_cost_usd": round(sum(t.get("cost_usd") or 0 for t in hk), 4),
        "needs_context_or_blocked": sum(1 for t in hk if t.get("status") in ("NEEDS_CONTEXT", "BLOCKED")),
        "tool_calls_per_haiku_task": avg([t["tool_calls"] for t in hk]),
        "tool_calls_per_sonnet_task": avg([t["tool_calls"] for t in sn]),
        "cf_cost_saved_usd": round(sum(c["haiku_saves_cost_usd"] for c in cfs), 4),
        "cf_critical_path_saved_s": round(sum(c["critical_path_saved_s"] or 0 for c in cfs), 1),
    }


def render(runs: list[dict]) -> str:
    out = ["## Per run (mechanical block)",
           table([run_row(r) for r in runs],
                 ["run", "built", "mechanical", "haiku", "1st-pass", "rework$", "haiku_s", "haiku$", "cf cost saved*",
                  "cf crit-path saved s*", "note"])]
    rows = []
    for r in runs:
        for t in r["tasks"]:
            if t.get("model") == "haiku":
                rows.append([r["run"], t["task"], t.get("kind"), t.get("loc"), t.get("dispatches"), _f(t.get("duration_s")),
                             t["tokens"]["in"] + t["tokens"]["cache_read"] + t["tokens"]["cache_write"], t["tokens"]["out"],
                             _f(t.get("cost_usd"), 4, "$"), t.get("tool_calls"), t.get("status") or "(none)",
                             {True: "yes", False: "NO", None: "n/a"}[t.get("first_time_pass")],
                             _f(t.get("rework_s")), _f(t.get("rework_cost"), 4, "$"),
                             {True: "yes", False: "no", None: "-"}[t.get("on_critical_path")], _f(t.get("slack_s")),
                             _f(t.get("start_lag_s"))])
    out += ["", "## Haiku tasks",
            table(rows, ["run", "task", "kind", "loc", "disp", "dur_s", "ctx tok", "out tok~", "cost", "tools", "status",
                         "1st-pass", "rework_s", "rework$", "crit", "slack_s", "lag_s"]) if rows else "(none)"]
    s = summary(runs)
    out += ["", "## Combined", json.dumps(s, indent=1), "",
            "* COUNTERFACTUAL ESTIMATE, not measured: Haiku tasks re-priced at Sonnet prices and re-timed at models.json "
            "output speeds, assuming Sonnet passes first time. 'out tok~' is estimated (the stream's output_tokens is an "
            "early snapshot). Unfinished tasks (killed runs) have no status and no first-time-pass."]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    runs = load(argv)
    if not runs:
        print("no score JSON with a `mechanical` block among the inputs", file=sys.stderr)
        return 1
    print(render(runs))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
