"""Routing evidence: per-feature-band outcomes by model, startup cost per model, and a rules recommendation.

    python bench/routing_evidence.py [--write]     # --write: bench/results/routing-recommendation.{md,json}

Inputs are everything measured so far: per-task records of the score JSONs (plan features joined to
mechanical.py metrics), the stream transcripts (startup), and the mechanical_ab results dirs. Bands with
no Haiku sample say so; thresholds are conservative extrapolations from what was measured."""
from __future__ import annotations

import glob
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
import mechanical  # noqa: E402

RES = harness.RESULTS


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 3) if xs else None


def load_samples() -> list[dict]:
    pt = harness._load_plan_tools()
    out = []
    for p in sorted(glob.glob(str(RES / "*.json"))):
        name = Path(p).name
        if name.endswith(".meta.json") or "recommendation" in name or "results" == Path(p).stem:
            continue
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        run = d.get("run") or name.replace(".mechanical.json", "").replace(".json", "")
        if not d.get("tasks") or "tokens" not in d["tasks"][0]:
            continue
        plan = harness._run_plan(harness.RUNS / run)
        focus = pt.review_focus_cases(plan) if plan is not None else {}
        for t in d["tasks"]:
            task = plan.by_id.get(t["task"]) if plan is not None else None
            reasons = pt.not_mechanical_reasons(task, focus) if task is not None else []
            out.append({"source": "run", "run": run, "task": t["task"], "model": t["model"], "loc": t["loc"],
                        "components": t["components"], "tests": t["tests"], "kind": t["kind"],
                        "hard_focus": any(r.startswith("Review Focus") for r in reasons), "lint_reasons": reasons,
                        "duration_s": t.get("duration_s"), "cost_usd": t.get("cost_usd"), "tool_calls": t.get("tool_calls"),
                        "ftp": t.get("first_time_pass"), "critical": t.get("on_critical_path"), "slack_s": t.get("slack_s")})
    for p in sorted(glob.glob(str(RES / "mechanical-ab-*" / "results.json"))):
        if "INVALID" in p:
            continue
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        for r in d["runs"]:
            if r.get("error") or r.get("duration_s") is None:
                continue
            tid = r["task"]
            plan = harness._run_plan(Path(d["config"]["run_dir"]))
            task = plan.by_id[tid]
            f = task.explicit_features
            out.append({"source": "ab:" + Path(p).parent.name + ":" + r.get("prime", "full"), "run": "A/B replay", "task": tid,
                        "model": r["model"], "loc": f.get("loc"), "components": f.get("components", 1), "tests": f.get("tests", "fast"),
                        "kind": f.get("kind", "design"), "hard_focus": False, "lint_reasons": [], "duration_s": r["duration_s"],
                        "cost_usd": r["cost_usd"], "tool_calls": r["tool_calls"], "ftp": r["passed"], "critical": None, "slack_s": None,
                        "prime": r.get("prime", "full")})
    return out


BANDS = {
    "loc": [("<=100", lambda s: s["loc"] is not None and s["loc"] <= 100), ("101-150", lambda s: s["loc"] and 100 < s["loc"] <= 150),
            ("151-300", lambda s: s["loc"] and 150 < s["loc"] <= 300), (">300", lambda s: s["loc"] and s["loc"] > 300)],
    "components": [("1", lambda s: s["components"] == 1), ("2", lambda s: s["components"] == 2), ("3+", lambda s: s["components"] >= 3)],
    "tests": [("fast", lambda s: s["tests"] == "fast"), ("slow", lambda s: s["tests"] == "slow")],
    "hard_review_focus": [("none", lambda s: not s["hard_focus"]), ("deep/numeric/state/protocol", lambda s: s["hard_focus"])],
    "critical_path": [("on", lambda s: s["critical"] is True), ("off", lambda s: s["critical"] is False)],
}


def band_table(samples: list[dict]) -> list[dict]:
    rows = []
    for feat, bands in BANDS.items():
        for label, pred in bands:
            for model in ("haiku", "sonnet", "opus"):
                ss = [s for s in samples if s["model"] == model and pred(s)]
                obs = [s for s in ss if s["ftp"] is not None]
                rows.append({"feature": feat, "band": label, "model": model, "n": len(ss), "n_observed_pass": len(obs),
                             "first_time_pass": sum(1 for s in obs if s["ftp"]), "median_s": med(s["duration_s"] for s in ss),
                             "median_cost_usd": med(s["cost_usd"] for s in ss), "median_tool_calls": med(s["tool_calls"] for s in ss),
                             "note": "NO DATA" if not ss else ("n<5" if len(ss) < 5 else "")})
    return rows


def wilson_lower(k: int, n: int, z: float = 1.96) -> float | None:
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    return round((p + z * z / (2 * n) - z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5) / d, 3)


def fixer_stats() -> dict:
    """What one miss costs: the fixer-sonnet assignments in the transcripts (duration and dollars)."""
    secs, cost = [], []
    for f in sorted(glob.glob(str(RES / "*superlite*.jsonl"))):
        for s in mechanical.segments(harness.read_events(Path(f))):
            if s["kind"] == "fix" and s["family"] == "sonnet" and s["complete"]:
                secs.append(s["end_s"] - s["start_s"])
                cost.append(mechanical.cost_of(s["tokens"], harness.PRICES["sonnet"]))
    return {"n": len(secs), "median_s": med(secs), "median_cost_usd": med(cost)}


BUDGETS_S = (15, 30, 60)


def economics(samples: list[dict], fixer: dict, slack: dict | None = None) -> list[dict]:
    """Per Haiku-eligible band: cost saved and extra seconds per task versus Sonnet, break-even first-time pass
    rate under +15/+30/+60 s budgets, and the recommended minimum. Base penalty and the Sonnet reference come from
    the A/B replay (same task, same brief); a miss costs one fixer-sonnet assignment on top (measured median)."""
    def ab(m):
        return [x for x in samples if x["source"].startswith("ab:") and x["model"] == m and x.get("prime", "full") == "full"]
    son_s, son_c = med(x["duration_s"] for x in ab("sonnet")), med(x["cost_usd"] for x in ab("sonnet"))
    R, Rc = fixer["median_s"], fixer["median_cost_usd"]
    out = []
    for label, lo, hi in (("<=100", 0, 100), ("101-150", 100, 150)):
        hs = [x for x in samples if x["model"] == "haiku" and x["loc"] is not None and lo < x["loc"] <= hi]
        obs = [x for x in hs if x["ftp"] is not None]
        k = sum(1 for x in obs if x["ftp"])
        row = {"band": label, "haiku_n": len(hs), "observed": len(obs), "first_time_pass": k,
               "wilson_95_lower": wilson_lower(k, len(obs)), "misses": len(obs) - k}
        if hs and son_s is not None:
            variants = {}
            for prime in ("full", "mini"):
                h = [x for x in hs if x["source"].startswith("ab:") and x.get("prime", "full") == prime]
                if not h:
                    continue
                base = round(med(x["duration_s"] for x in h) - son_s, 1)
                saved = round(son_c - med(x["cost_usd"] for x in h), 4)
                be = {}
                for b in BUDGETS_S:
                    room = b - base
                    be[f"+{b}s"] = 1.0 if room <= 0 else (None if not R else round(max(0.0, min(1.0, 1 - room / R)), 3))
                variants[prime] = {
                    "base_penalty_s": base, "cost_saved_per_task_usd": saved,
                    "usd_saved_per_extra_second": {f"+{b}s": round(saved / b, 5) for b in BUDGETS_S},
                    "usd_per_second_at_base": round(saved / base, 5) if base > 0 else "not slower than Sonnet: saves cost and time",
                    "break_even_first_time_pass": be,
                    "expected_extra_s_at_pass_rate_0.9": round(base + 0.1 * (R or 0), 1),
                    "expected_cost_saved_at_pass_rate_0.9_usd": round(saved - 0.1 * (Rc or 0), 4)}
            if variants.get("full"):
                v0 = variants["full"]
                p_cost = round((Rc or 0) / (v0["cost_saved_per_task_usd"] + (Rc or 0)), 3) if (Rc is not None and v0["cost_saved_per_task_usd"] + Rc) else None
                row["cost_break_even_first_time_pass"] = p_cost
                row["time_budget_break_even_secondary"] = v0["break_even_first_time_pass"]
            row["vs_sonnet"] = variants
            row["sonnet_reference"] = {"median_s": son_s, "median_cost_usd": son_c, "n": len(ab("sonnet"))}
            row["miss_cost"] = {"extra_s": R, "extra_usd": Rc,
                                "basis": "median fixer-sonnet assignment in the transcripts (n=%d); no Haiku miss has occurred" % fixer["n"]}
            # Off the critical path the time hit is absorbed by slack, so the gate is cost: p*saved >= (1-p)*miss cost, and a miss
            # whose rework (base + fixer s) exceeds the typical slack turns into run time: cap its expected run-time hit at 15 s.
            slack_med = (slack or {}).get("proxy_all_tasks", {}).get("median_slack_s_of_off_path") or 0
            overflow = max(0.0, (variants.get("full", {}).get("base_penalty_s", 0) + (R or 0)) - slack_med)
            p_time = 0.0 if overflow <= 0 else 1 - 15.0 / overflow
            floor = None if p_cost is None else min(0.95, max(0.5, math.ceil(max(p_cost, p_time) / 0.05 - 1e-9) * 0.05))
            row["time_overflow_p"] = round(p_time, 3)
            row["min_first_time_pass"] = None if floor is None else round(floor, 2)
            row["decidable"] = bool(floor is not None and row["wilson_95_lower"] is not None and row["wilson_95_lower"] >= floor)
            row["evidence_note"] = "%d/%d first-time passes (Wilson 95%% lower bound %s) vs required %s: %s" % (
                k, len(obs), row["wilson_95_lower"], row["min_first_time_pass"],
                "sample is enough" if row["decidable"] else "SAMPLE TOO SMALL to confirm; provisional")
        else:
            row["min_first_time_pass"] = None
            row["decidable"] = False
            row["evidence_note"] = "NO HAIKU DATA in this band: no break-even can be anchored; use Sonnet until measured"
        out.append(row)
    return out


def misses(samples: list[dict]) -> dict:
    """Haiku tasks that did not pass first time, with reason and rework cost, plus unobserved ones."""
    recs = []
    for p in sorted(glob.glob(str(RES / "*.json"))):
        if "recommendation" in p or p.endswith(".meta.json"):
            continue
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        for t in d.get("tasks") or []:
            if t.get("model") == "haiku":
                recs.append({"run": Path(p).stem, **{k: t.get(k) for k in (
                    "task", "status", "status_reason", "first_time_pass", "rework_s", "rework_cost", "rework_dispatches", "kind_miss_incidents")}})
    for p in sorted(glob.glob(str(RES / "mechanical-ab-*" / "results.json"))):
        if "INVALID" in p:
            continue
        for r in json.loads(Path(p).read_text(encoding="utf-8"))["runs"]:
            if r["model"] == "haiku":
                recs.append({"run": "A/B %s %s #%s" % (Path(p).parent.name, r.get("prime", "full"), r["rep"]), "task": r["task"],
                             "status": r.get("status"), "status_reason": r.get("fail_reason"), "first_time_pass": r["passed"],
                             "rework_s": 0, "rework_cost": 0, "rework_dispatches": 0, "kind_miss_incidents": 0})
    failed = [r for r in recs if r["first_time_pass"] is False]
    reasons: dict[str, int] = {}
    for r in failed:
        st = (r["status"] or "").upper()
        why = st if st in ("NEEDS_CONTEXT", "BLOCKED") else ("red tests" if "red" in str(r["status_reason"]).lower() else "wrong output / other")
        r["why"] = why
        reasons[why] = reasons.get(why, 0) + 1
    return {"haiku_tasks": len(recs), "failed_first_time": len(failed), "by_reason": reasons, "failures": failed,
            "unobserved": [r["run"] + " " + r["task"] for r in recs if r["first_time_pass"] is None],
            "rework_s": round(sum(r["rework_s"] or 0 for r in failed), 1),
            "rework_cost_usd": round(sum(r["rework_cost"] or 0 for r in failed), 4)}


SLACK_STEPS = (0, 60, 120)


def slack_stats(samples: list[dict], fixer: dict, base_penalty: float | None) -> dict:
    """How often work is off the critical path, per run, and how the slack compares with Haiku's extra time and a miss.
    Strict set = lint-eligible or Kind: mechanical tasks (only x1 has any, and x1 was killed so its slack is meaningless);
    proxy sets = all tasks, and tasks whose only lint reason is LOC, in the runs that finished."""
    runs: dict[str, list[dict]] = {}
    for x in samples:
        if x["source"] == "run" and x.get("slack_s") is not None and x.get("critical") is not None:
            runs.setdefault(x["run"], []).append(x)
    killed = {"combo-superlite-x1.mechanical", "combo-superlite-x1"}

    def share(ts, step):
        return round(sum(1 for t in ts if t["critical"] is False and t["slack_s"] > step) / len(ts), 3) if ts else None

    def block(pred):
        per = {}
        for run, ts in runs.items():
            ts = [t for t in ts if pred(t)]
            if ts and run not in killed:
                per[run] = {"n": len(ts), **{f"slack>{k}s": share(ts, k) for k in SLACK_STEPS}}
        pooled = [t for run, ts in runs.items() if run not in killed for t in ts if pred(t)]
        return {"per_run": per, "pooled": {"n": len(pooled), **{f"slack>{k}s": share(pooled, k) for k in SLACK_STEPS}},
                "median_slack_s_of_off_path": med(t["slack_s"] for t in pooled if t["critical"] is False)}

    strict = [x for x in samples if x["source"] == "run" and (x["kind"] == "mechanical" or not x["lint_reasons"])]
    loc_only = lambda t: all(r.startswith("LOC owned") for r in t["lint_reasons"])  # noqa: E731
    R = fixer.get("median_s") or 0
    pen = base_penalty or 0
    return {
        "strict_mechanical_or_lint_eligible": {"n": len(strict), "runs": sorted({x["run"] for x in strict}),
                                               "note": "all from killed run x1: no usable slack data"},
        "proxy_all_tasks": block(lambda t: True),
        "proxy_only_loc_over_limit": block(loc_only),
        "haiku_extra_s_pass_case": pen, "miss_extra_s": R,
        "slack_needed_to_absorb_pass_s": max(0.0, pen),
        "slack_needed_to_absorb_miss_s": round(max(0.0, pen + R), 1),
    }


def min_slack(stats: dict) -> dict:
    need_miss = stats["slack_needed_to_absorb_miss_s"]
    need_pass = stats["slack_needed_to_absorb_pass_s"]
    rec = int(math.ceil(need_miss / 30.0) * 30)
    pooled = stats["proxy_all_tasks"]["pooled"]
    kept = {f"slack>{k}s": pooled.get(f"slack>{k}s") for k in SLACK_STEPS}
    return {"min_slack_s": rec, "absorbs": "a median first-time miss (base penalty + fixer time), so a miss does not become run time",
            "pass_only_alternative_s": int(math.ceil(max(need_pass, 1.0) / 15.0) * 15),
            "share_of_tasks_retained_proxy": kept,
            "evidence": "Haiku pass case +%.1f s; median miss adds %.1f s (fixer-sonnet); needing %.0f s of slack to absorb a miss. "
                        "Shares are over ALL tasks of finished combo runs (proxy: no finished run has Haiku-eligible tasks)." % (
                            need_pass, stats["miss_extra_s"], need_miss)}


def money_left(samples: list[dict], ms: int, ratio: float | None) -> dict:
    """Mechanical or lint-eligible tasks the critical-path / slack rule keeps off Haiku, and what Haiku would have saved."""
    rows, left = [], 0.0
    for x in samples:
        if x["source"] != "run" or not (x["kind"] == "mechanical" or not x["lint_reasons"]):
            continue
        on = x["critical"] is True or (x["slack_s"] is not None and x["slack_s"] < ms)
        if not on:
            continue
        if x["model"] == "haiku":
            rows.append({"run": x["run"], "task": x["task"], "ran_on": "haiku", "cost_usd": x["cost_usd"], "saved_usd": 0.0,
                         "note": "was on Haiku although on the critical path: a violation under the rule"})
            continue
        est = round((x["cost_usd"] or 0) * (ratio or 0), 4)
        saved = round((x["cost_usd"] or 0) - est, 4)
        left += saved
        rows.append({"run": x["run"], "task": x["task"], "ran_on": x["model"], "cost_usd": x["cost_usd"], "est_haiku_cost_usd": est, "saved_usd": saved})
    return {"excluded_tasks": len(rows), "money_left_on_table_usd": round(left, 4),
            "haiku_to_sonnet_cost_ratio": ratio, "ratio_basis": "A/B replay median cost, Haiku / Sonnet (full prime)", "rows": rows,
            "caveat": "x1 was killed: its critical-path flags are all ties, so every candidate there counts as excluded"}


def startup() -> dict:
    """Prime assignments (dispatch -> READY) per model from the transcripts that use the prime protocol."""
    rows = []
    for f in sorted(glob.glob(str(RES / "*superlite*.jsonl"))):
        segs = mechanical.segments(harness.read_events(Path(f)))
        for s in segs:
            if s["kind"] == "prime" and s["family"]:
                price = harness.PRICES[s["family"]]
                rows.append({"run": Path(f).stem, "model": s["family"], "seconds": round(s["end_s"] - s["start_s"], 1),
                             "first_tool_s": s["first_tool_s"], "tool_calls": s["tool_calls"],
                             "first_call_ctx": s["first_call_ctx"], "cache_write": s["first_call_cache_write"], "cache_read": s["first_call_cache_read"],
                             "total_ctx_tokens": sum(s["tokens"][k] for k in ("input", "cache_read", "cache_write_5m", "cache_write_1h")),
                             "cost_usd": round(mechanical.cost_of(s["tokens"], price), 5)})
    out = {}
    for m in ("haiku", "sonnet"):
        rs = [r for r in rows if r["model"] == m]
        out[m] = {"n": len(rs), "prime_seconds_median": med(r["seconds"] for r in rs), "first_tool_s_median": med(r["first_tool_s"] for r in rs),
                  "first_call_cache_write_tokens_median": med(r["cache_write"] for r in rs),
                  "first_call_cache_read_tokens_median": med(r["cache_read"] for r in rs),
                  "prime_ctx_tokens_median": med(r["total_ctx_tokens"] for r in rs), "prime_cost_usd_median": med(r["cost_usd"] for r in rs)}
    out["_rows"] = rows
    return out


def prime_ab() -> dict:
    p = RES / "mechanical-ab-prime-size-x1" / "results.json"
    if not p.is_file():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    out = {}
    for pr in ("full", "mini"):
        rs = [r for r in d["runs"] if r.get("prime") == pr]
        out[pr] = {"n": len(rs), "passed": sum(r["passed"] for r in rs), "prime_tokens_est": med(r.get("prime_tokens_est") for r in rs),
                   "median_s": med(r["duration_s"] for r in rs), "median_cost_usd": med(r["cost_usd"] for r in rs),
                   "median_tool_calls": med(r["tool_calls"] for r in rs),
                   "median_ctx_tokens": med(sum(r["tokens"][k] for k in ("in", "cache_read", "cache_write")) for r in rs)}
    return out


def recommendation(samples, bands, start, pab, econ, miss, fixer, slack, ms, left) -> dict:
    ab = {m: [s for s in samples if s["source"].startswith("ab:") and s["model"] == m and s.get("prime", "full") == "full"] for m in ("haiku", "sonnet")}
    return {
        "generated_from": "bench/routing_evidence.py",
        "evidence_summary": {
            "haiku_samples": sum(1 for s in samples if s["model"] == "haiku"),
            "haiku_samples_all_on_task": "combo T8 (refs, 80 LOC, 1 component, fast tests, no hard Review Focus)",
            "sonnet_design_samples": sum(1 for s in samples if s["model"] == "sonnet" and s["source"] == "run"),
            "ab_full_prime": {m: {"n": len(v), "pass": sum(s["ftp"] for s in v), "median_s": med(s["duration_s"] for s in v),
                                  "median_cost_usd": med(s["cost_usd"] for s in v), "median_tool_calls": med(s["tool_calls"] for s in v)}
                              for m, v in ab.items()},
            "prime_size_ab_haiku": pab,
        },
        "rules": {
            "table": [
                {"when": {"loc_max": 100, "components_max": 2, "tests": "fast", "kind_mechanical": True}, "tier": "haiku",
                 "min_first_time_pass": econ[0]["min_first_time_pass"], "min_slack_s": ms["min_slack_s"], "off_critical_path": True,
                 "evidence": "Haiku 9/9 pass on the one measured task (80 LOC; 6 full-prime + 3 mini-prime replays); nothing measured above 100 LOC"},
            ],
            "default_tier": "sonnet",
            "critical_path_rule": {"applies": True, "never_haiku_on_critical_path": True, "min_slack_s": ms["min_slack_s"],
                                   "note": "user ruling: Haiku only for mechanical tasks off the critical path; ties and unknown slack count as on-path"},
            "min_slack_s": ms,
            "min_first_time_pass": {e["band"]: {"value": e["min_first_time_pass"], "decidable": e["decidable"], "evidence": e["evidence_note"]} for e in econ},
            "reuse_limits": {
                "haiku": {"max_tasks_per_agent": 3, "max_context_k": 40,
                          "basis": "POLICY, not measured: a Haiku agent holds about 27k context after one task (x1 T8 peak 26.7k)"},
                "sonnet": {"max_tasks_per_agent": 4, "max_context_k": 80,
                           "basis": "POLICY, not measured: Sonnet agents measured at 18-25k per task, none reused beyond 2 tasks"},
            },
            "mini_prime": {"haiku": "task block + Global constraints + stub files + cited SPEC sections; ~1.0k tokens measured on T8 vs 4.6k full; "
                                    "3/3 pass, -12% time, -31% cost, -25% tool calls (n=3)"},
        },
        "slack_analysis": slack, "money_left_on_table": left, "economics": econ, "misses": miss, "fixer_miss_cost": fixer,
        "start_lag_note": "start lag by model is reported per run by report_mechanical.py (pool block)",
    }


def fmt(v):
    return "-" if v is None else v


def markdown(samples, bands, start, pab, rec, econ, miss, fixer, slack, ms, left) -> str:
    L = ["# Routing recommendation (generated by bench/routing_evidence.py)", "",
         "Evidence base: %d task samples (%d Haiku). **Haiku evidence is one task**: combo T8 `refs` (80 LOC, 1 component, fast tests, "
         "no hard Review Focus) = x1 (killed, unfinished) + 6 A/B replays + 3 mini-prime replays. Everything else about Haiku is untested." %
         (len(samples), sum(1 for s in samples if s["model"] == "haiku")), "", "## Recommended rules table", "",
         "| Condition | Tier |", "|---|---|",
         "| `Kind: mechanical` AND LOC <= 100 AND components <= 2 AND tests fast AND no deep/numeric/state/protocol Review Focus | **haiku** |",
         "| mechanical, LOC 101-150 | sonnet until Haiku data there clears its min first-time pass (about 10+ passes) |",
         "| anything else (design, slow tests, hard Review Focus, > 2 components, > 150 LOC) | **sonnet** |",
         "", "Critical path: **never Haiku on the critical path**, and only with `min_slack_s` = **%s s** of slack (absorbs a median miss; "
          "%s s would absorb only the pass case). Ties and unknown slack count as on-path." % (ms["min_slack_s"], ms["pass_only_alternative_s"]), "",
         "Reuse limits (policy, unmeasured): Haiku 3 tasks / 40k context per agent; Sonnet 4 tasks / 80k. Retire an agent past either limit.", "",
         "## Outcomes by feature band and model", "",
         "| feature | band | model | n | 1st-pass | median s | median $ | median tools | note |", "|---|---|---|---|---|---|---|---|---|"]
    for r in bands:
        if r["model"] == "opus" and not r["n"]:
            continue
        L.append(f"| {r['feature']} | {r['band']} | {r['model']} | {r['n']} | {r['first_time_pass']}/{r['n_observed_pass']} | {fmt(r['median_s'])} | "
                 f"{fmt(r['median_cost_usd'])} | {fmt(r['median_tool_calls'])} | {r['note']} |")
    L += ["", "## How often mechanical work is off the critical path", "",
          "Strict set (Kind mechanical or lint-eligible): n=%d, all from run(s) %s, which was killed, so its slack says nothing. "
          "Proxies below use every task of the finished combo runs (`slack>X` = share of tasks off the critical path with more than X s of slack)." % (
              slack["strict_mechanical_or_lint_eligible"]["n"], ", ".join(slack["strict_mechanical_or_lint_eligible"]["runs"])), "",
          "| set | run | n | slack>0 | slack>60 s | slack>120 s |", "|---|---|---|---|---|---|"]
    for key, label in (("proxy_all_tasks", "all tasks"), ("proxy_only_loc_over_limit", "only-LOC-over-limit")):
        for run, v in slack[key]["per_run"].items():
            L.append(f"| {label} | {run} | {v['n']} | {v['slack>0s']} | {v['slack>60s']} | {v['slack>120s']} |")
        v = slack[key]["pooled"]
        L.append(f"| {label} | **pooled** | {v['n']} | {v['slack>0s']} | {v['slack>60s']} | {v['slack>120s']} |")
    L += ["", "Slack vs Haiku time: Haiku's extra time is %+.1f s when it passes (full prime) and a miss adds about %.1f s (fixer-sonnet median), "
          "so a miss needs about %.0f s of slack to stay invisible in run time. Median slack of off-path tasks: %s s. "
          "**Recommended `min_slack_s` = %s** (pass-only alternative %s)." % (
              slack["haiku_extra_s_pass_case"], slack["miss_extra_s"], slack["slack_needed_to_absorb_miss_s"],
              slack["proxy_all_tasks"]["median_slack_s_of_off_path"], ms["min_slack_s"], ms["pass_only_alternative_s"]), "",
          "## Money left on the table by the critical-path rule", "",
          "Mechanical or lint-eligible tasks kept off Haiku: **%d**; Haiku would have saved about **$%s** (Haiku/Sonnet cost ratio %s from the A/B). %s" % (
              left["excluded_tasks"], left["money_left_on_table_usd"], left["haiku_to_sonnet_cost_ratio"], left["caveat"]), "",
          "| run | task | ran on | cost $ | est. Haiku $ | saved $ |", "|---|---|---|---|---|---|"]
    L += [f"| {r['run']} | {r['task']} | {r['ran_on']} | {r['cost_usd']} | {r.get('est_haiku_cost_usd', '-')} | {r['saved_usd']} |" for r in left["rows"]]
    L += ["", "## Economics (off the critical path: gate = first-time pass; time budgets are secondary)", "",
          "A miss costs one extra fixer-sonnet assignment: median %ss and $%s (n=%s transcripts). No Haiku miss has happened yet, so this is the "
          "price of a miss, not an observed one. Gate: p x saved >= (1-p) x miss cost (cost break-even), and a miss that overflows the typical slack must not add more than 15 s of expected run time. The +15/+30/+60 s columns are the old time-budget view." % (
              fixer["median_s"], fixer["median_cost_usd"], fixer["n"]), "",
          "| band | haiku n | 1st-pass (obs) | Wilson low | prime | cost saved/task | extra s vs Sonnet (base) | $ per extra s | break-even +15s | +30s | +60s | **min 1st-pass** | decidable |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for e in econ:
        if "vs_sonnet" not in e:
            L.append(f"| {e['band']} | {e['haiku_n']} | - | - | - | NO DATA | - | - | - | - | - | - | no |")
            continue
        for prime, v in e["vs_sonnet"].items():
            be = v["break_even_first_time_pass"]
            L.append(f"| {e['band']} | {e['haiku_n']} | {e['first_time_pass']}/{e['observed']} | {e['wilson_95_lower']} | {prime} | ${v['cost_saved_per_task_usd']} | "
                     f"{v['base_penalty_s']:+} | {v['usd_per_second_at_base']} | {be['+15s']} | {be['+30s']} | {be['+60s']} | {e['min_first_time_pass']} | "
                     f"{'yes' if e['decidable'] else 'NO: sample too small'} |")
    L += ["", "Dollars saved per extra second if the full budget were used (full prime): " + "; ".join(
        f"{k} -> ${v}/s" for k, v in econ[0].get("vs_sonnet", {}).get("full", {}).get("usd_saved_per_extra_second", {}).items()) + ".",
          "A base penalty <= 0 (mini prime) means Haiku is not slower on this task, so no time is bought. `min first-pass` = max(cost break-even, run-time overflow cap) rounded up to 0.05, never below 0.5. Cost break-even is about 0.48 (a miss costs about as much as one Haiku saving), and the `min_slack_s` gate already absorbs a median miss, so the floor is cost-driven. At a 0.8 pass rate the expected net saving is $%s per task. The 101-150 band has no Haiku data." % round(0.8 * econ[0].get("vs_sonnet", {}).get("full", {}).get("cost_saved_per_task_usd", 0) - 0.2 * (fixer["median_cost_usd"] or 0), 3), "",
          "## Misses (Haiku tasks that did not pass first time)", "",
          "Haiku tasks measured: %d; failed first time: **%d**; unobserved (killed before reporting): %s. Rework so far: %ss, $%s." % (
              miss["haiku_tasks"], miss["failed_first_time"], ", ".join(miss["unobserved"]) or "none", miss["rework_s"], miss["rework_cost_usd"]), ""]
    if miss["failures"]:
        L += ["| run | task | why | status | reason | rework s | rework $ |", "|---|---|---|---|---|---|---|"]
        L += [f"| {r['run']} | {r['task']} | {r['why']} | {r['status']} | {str(r['status_reason'])[:80]} | {r['rework_s']} | {r['rework_cost']} |" for r in miss["failures"]]
    else:
        L += ["No Haiku miss has been observed, so there is no measured reason or rework cost yet (reasons tracked: NEEDS_CONTEXT, BLOCKED, red tests, wrong output)."]
    L += ["", "Haiku rows other than `loc <= 100`, `components 1`, `tests fast`, `hard_review_focus none` are NO DATA. Sonnet has no sample at <= 100 LOC "
          "except x1's unfinished tasks, so cross-model comparison inside a band exists only through the A/B replay.", "",
          "## Haiku vs Sonnet, same task (A/B replay, combo T8, full prime; Haiku n=6, Sonnet n=3)", "", "| model | pass | median s | median $ | median tools |", "|---|---|---|---|---|"]
    for m, v in rec["evidence_summary"]["ab_full_prime"].items():
        L.append(f"| {m} | {v['pass']}/{v['n']} | {v['median_s']} | {v['median_cost_usd']} | {v['median_tool_calls']} |")
    L += ["", "## Startup cost per model (prime assignments in the transcripts, dispatch to READY)", "",
          "| model | n | prime s | first tool s | cache write tok | cache read tok | ctx tok | prime $ |", "|---|---|---|---|---|---|---|---|"]
    for m in ("haiku", "sonnet"):
        v = start[m]
        L.append(f"| {m} | {v['n']} | {fmt(v['prime_seconds_median'])} | {fmt(v['first_tool_s_median'])} | {fmt(v['first_call_cache_write_tokens_median'])} | "
                 f"{fmt(v['first_call_cache_read_tokens_median'])} | {fmt(v['prime_ctx_tokens_median'])} | {fmt(v['prime_cost_usd_median'])} |")
    L += ["", "Only x1 used the READY prime protocol: 7 Sonnet primes and 1 Haiku prime (the single cold Haiku prime). Per-model caches are not "
          "shared, so the first Haiku agent of a run pays its own cache write; one sample cannot show how large that penalty is.", "",
          "## Prime size A/B (Haiku, T8, n=3 each)", "", "| prime | tokens (est) | pass | median s | median $ | tools | ctx tok |", "|---|---|---|---|---|---|---|"]
    for pr, v in pab.items():
        L.append(f"| {pr} | {v['prime_tokens_est']} | {v['passed']}/{v['n']} | {v['median_s']} | {v['median_cost_usd']} | {v['median_tool_calls']} | {v['median_ctx_tokens']} |")
    L += ["", "## Caveats", "",
          "- The x1 prime is ~4.6k tokens (18.7 KB), not 15k; the mini prime is ~1.0k, below the 3-5k target, because T8's block is tiny.",
          "- One task, one project (Python, combo/minisheet). Nothing here is language-specific, but nothing is measured for other languages: "
          "the ts-wordstat/ts-textkit/ts-logflow runs used Sonnet batch dispatches and have no per-task plan records, so they add no band data.",
          "- First-time pass for Sonnet tasks comes from handback status and rework markers; DONE_WITH_CONCERNS counts as a pass unless rework followed.",
          "- Critical-path and slack come from the actual times of runs whose last wave was killed or clustered; treat slack > 300 s as 'off path'.",
          "- A/B timings include model latency noise of a few seconds; with n=3 a 10 s difference is suggestive, not significant.",
          "- Reuse limits are policy defaults, not measured. The miss price is the measured fixer-sonnet median, not an observed Haiku miss."]
    return "\n".join(L) + "\n"


def main() -> int:
    samples = load_samples()
    bands = band_table(samples)
    start, pab = startup(), prime_ab()
    fixer = fixer_stats()
    ab_full = lambda m: [x for x in samples if x["source"].startswith("ab:") and x["model"] == m and x.get("prime", "full") == "full"]  # noqa: E731
    base = None
    if ab_full("haiku") and ab_full("sonnet"):
        base = round(med(x["duration_s"] for x in ab_full("haiku")) - med(x["duration_s"] for x in ab_full("sonnet")), 1)
    slack = slack_stats(samples, fixer, base)
    ms = min_slack(slack)
    econ, miss = economics(samples, fixer, slack), misses(samples)
    ratio = round(med(x["cost_usd"] for x in ab_full("haiku")) / med(x["cost_usd"] for x in ab_full("sonnet")), 3) if base is not None else None
    left = money_left(samples, ms["min_slack_s"], ratio)
    rec = recommendation(samples, bands, start, pab, econ, miss, fixer, slack, ms, left)
    doc = {"recommendation": rec, "rules": rec["rules"], "bands": bands, "startup": start, "prime_ab": pab,
           "samples": len(samples)}
    md = markdown(samples, bands, start, pab, rec, econ, miss, fixer, slack, ms, left)
    if "--write" in sys.argv:
        (RES / "routing-recommendation.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
        (RES / "routing-recommendation.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
