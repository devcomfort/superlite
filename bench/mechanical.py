"""Per-task and per-run metrics for `Kind: mechanical` tasks (Haiku implementers), from a run's stream
log, plan and .superlite/ notes. Pure functions over parsed data: no network, no agents.

A task's work is a list of *assignments*: one per `task_started` system event (a resumed agent, via
SendMessage, starts a new assignment under the same task_id and Agent tool_use id). The events of an
assignment are the subagent events between its `task_started` and its `task_notification`, by stream
position. Prices come from config/models.json; every counterfactual number is an ESTIMATE."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

FAMILIES = ("haiku", "sonnet", "opus")
_TID = re.compile(r"\bT(\d+)\b")
_FIX_PROMPT = re.compile(r"\b(fix(?:es|ed|er)?|re-?dispatch|rework|kind-miss|finding)\b|\bF-T\d+-\d+", re.I)
_PRIME_PROMPT = re.compile(r"reply only\s*`?READY`?", re.I)
_STATUS = re.compile(r"\bStatus:\s*\**\s*(DONE_WITH_CONCERNS|DONE|NEEDS_CONTEXT|BLOCKED)\b", re.I)
_RED = re.compile(r"\b(?:tests?|suite)\b[^\n]{0,40}\b(?:red|failing|failed)\b|\b\d+\s+failed\b", re.I)
_CPT = 3.5  # chars per output token, used only where the stream's output_tokens snapshot is too small


def family(model: str | None) -> str | None:
    m = (model or "").lower()
    return next((f for f in FAMILIES if f in m), None)


def _ts(e: dict) -> float | None:
    s = e.get("timestamp")
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _tid(*texts: str) -> str | None:
    for t in texts:
        m = _TID.search(t or "")
        if m:
            return "T" + m.group(1)
    return None


def cost_of(tok: dict, price: tuple) -> float:
    """USD for one token dict {input, output, cache_read, cache_write_5m, cache_write_1h} at one price tuple
    (input, output, write 5m, write 1h, read), as `harness.load_prices` returns."""
    pi, po, w5, w1, pr = price
    return (tok.get("input", 0) * pi + tok.get("output", 0) * po + tok.get("cache_write_5m", 0) * w5
            + tok.get("cache_write_1h", 0) * w1 + tok.get("cache_read", 0) * pr)


def _empty_tokens() -> dict:
    return {"input": 0, "output": 0, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}


def segments(events: list[dict]) -> list[dict]:
    """Assignments with their tokens, tool calls, times and reported status."""
    stamps = [t for t in map(_ts, events) if t is not None]
    t0 = min(stamps) if stamps else 0.0
    rel: list[float | None] = []   # time of each event; system events inherit the latest earlier stamp
    last = 0.0
    for i, e in enumerate(events):
        t = _ts(e)
        last = (t - t0) if t is not None else last
        rel.append(last)
    starts = [i for i, e in enumerate(events) if e.get("type") == "system" and e.get("subtype") == "task_started"
              and e.get("task_type", "local_agent") == "local_agent"]
    parents: dict[str, set] = {}   # a resumed agent's events keep the parent id of its first Agent call
    for i in starts:
        parents.setdefault(events[i].get("task_id"), set()).add(events[i].get("tool_use_id"))
    out = []
    for n, i in enumerate(starts):
        s = events[i]
        end = len(events)
        note = None
        for j in range(i + 1, len(events)):
            e = events[j]
            if e.get("task_id") == s.get("task_id") and e.get("subtype") in ("task_notification", "task_started"):
                end = j
                note = e if e.get("subtype") == "task_notification" else None
                break
        parent = parents[s.get("task_id")]
        mine = [events[k] for k in range(i + 1, end)
                if events[k].get("parent_tool_use_id") in parent and events[k].get("type") in ("assistant", "user")]
        tok = _empty_tokens()
        models: dict[str, int] = {}
        calls: set[str] = set()
        by_msg: dict[str, dict] = {}
        stamped = [k for k in range(i + 1, end) if events[k].get("parent_tool_use_id") in parent and _ts(events[k]) is not None]
        for e in mine:
            if e.get("type") != "assistant":
                continue
            msg = e.get("message") or {}
            mid = msg.get("id") or f"anon{id(e)}"
            rec = by_msg.setdefault(mid, {"u": msg.get("usage") or {}, "model": msg.get("model") or "", "chars": 0})
            for b in msg.get("content") or []:
                if b.get("type") == "tool_use":
                    calls.add(b.get("id") or f"{mid}:{len(calls)}")
                    rec["chars"] += len(json.dumps(b.get("input") or {}))
                elif b.get("type") == "text":
                    rec["chars"] += len(b.get("text") or "")
                elif b.get("type") == "thinking":
                    rec["chars"] += len(b.get("thinking") or "")
            u = msg.get("usage") or {}
            rec["out"] = max(rec.get("out", 0), u.get("output_tokens") or 0)
        for rec in by_msg.values():
            u = rec["u"]
            cc = u.get("cache_creation") or {}
            w1 = cc.get("ephemeral_1h_input_tokens")
            w5 = cc.get("ephemeral_5m_input_tokens")
            if w1 is None and w5 is None:
                w5, w1 = u.get("cache_creation_input_tokens") or 0, 0
            tok["input"] += u.get("input_tokens") or 0
            tok["cache_read"] += u.get("cache_read_input_tokens") or 0
            tok["cache_write_5m"] += w5 or 0
            tok["cache_write_1h"] += w1 or 0
            tok["output"] += max(rec.get("out", 0), int(rec["chars"] / _CPT))
            models[family(rec["model"]) or "?"] = models.get(family(rec["model"]) or "?", 0) + 1
        fam = max((m for m in models if m != "?"), key=models.get, default=None) \
            or ("haiku" if "haiku" in (s.get("subagent_type") or "") else None)
        text = ""
        if note:
            text = (note.get("handback_report") or {}).get("text") or ""
        if not text:  # no handback: the agent's last text block
            for e in reversed(mine):
                if e.get("type") == "assistant":
                    tb = [b.get("text") or "" for b in (e.get("message") or {}).get("content") or [] if b.get("type") == "text"]
                    if tb:
                        text = tb[-1]
                        break
        sm = _STATUS.search(text)
        status = sm.group(1).upper() if sm else None
        prompt = s.get("prompt") or ""
        head = prompt[:400]
        kind = ("prime" if _PRIME_PROMPT.search(head) else
                "fix" if (_FIX_PROMPT.search(head) or "fixer" in (s.get("subagent_type") or "")) else
                "review" if "review" in (s.get("subagent_type") or "") else "build")
        out.append({
            "agent": s.get("task_id"), "subagent_type": s.get("subagent_type") or "", "kind": kind,
            "description": s.get("description") or "", "prompt_head": head,
            "tid": _tid(head, s.get("description") or ""),
            "family": fam, "status": status, "text": text, "complete": note is not None,
            "start_s": round(rel[i], 1),
            "end_s": round(rel[max(stamped)] if stamped else rel[end - 1], 1),
            "tokens": tok, "tool_calls": len(calls), "api_calls": len(by_msg),
        })
    # an agent's prime and untagged segments belong to the task id its other segments name
    default: dict[str, str] = {}
    for sg in out:
        if sg["tid"] and sg["kind"] != "prime":
            default.setdefault(sg["agent"], sg["tid"])
    for sg in out:
        sg["tid"] = sg["tid"] or default.get(sg["agent"])
    return out


def _incidents(run_dir: Path | None) -> tuple[list[dict], list[str]]:
    inc, notes = [], []
    if run_dir is None:
        return inc, notes
    log = Path(run_dir) / ".superlite" / "incidents.jsonl"
    if log.is_file():
        for ln in log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            if isinstance(e, dict):
                inc.append(e)
    fx = Path(run_dir) / ".superlite" / "fixes"
    if fx.is_dir():
        notes = [p.name + "\n" + p.read_text(encoding="utf-8", errors="replace") for p in sorted(fx.glob("*.md"))]
    return inc, notes


def _norm(p: str) -> str:
    return p.replace("\\", "/").strip().lower()


def _topo_forward(order, deps, dur, lag, start0):
    done: dict[str, float] = {}
    for t in order:
        ds = [done[d] for d in deps.get(t, []) if d in done]
        st = (max(ds) + lag.get(t, 0.0)) if ds else start0[t]
        done[t] = st + dur[t]
    return done


def task_metrics(events: list[dict], base: list[dict], plan, graph: dict, run_dir: Path | None,
                 prices: dict) -> list[dict]:
    """Extend the base task records (task_records) with the per-run measurements. `plan` is a
    plan_tools.Plan, `graph` its parse_taskgraph result ({} when the plan has none)."""
    segs = segments(events)
    incidents, fix_notes = _incidents(run_dir)
    owned = {t: {_norm(p) for p in plan.by_id[t].owns} for t in plan.by_id}
    recs = {r["task"]: dict(r) for r in base}

    def pricing(fam):
        return prices.get(fam or "sonnet") or prices["sonnet"]

    for tid, r in recs.items():
        mine = [s for s in segs if s["tid"] == tid]
        builds = [s for s in mine if s["kind"] in ("build", "prime")]
        real = [s for s in builds if s["kind"] == "build"]
        fixes = [s for s in mine if s["kind"] == "fix"]
        # a fix prompt that names no task id is attributed by the files it mentions
        for s in segs:
            if s["kind"] == "fix" and not s["tid"]:
                text = _norm(s["prompt_head"])
                if any(p and p in text for p in owned.get(tid, ())):
                    fixes.append(s)
        fam = (real[0]["family"] if real else None) or family(r.get("model"))
        r["model_plan"] = r.get("model")
        r["model"] = fam or r.get("model")
        r["dispatches"] = len(real)
        r["start_s"] = min((s["start_s"] for s in real), default=None)
        r["end_s"] = max((s["end_s"] for s in real), default=None)
        r["duration_s"] = round(sum(s["end_s"] - s["start_s"] for s in real), 1) if real else None
        tok = _empty_tokens()
        cost = 0.0
        for s in builds:
            for k in tok:
                tok[k] += s["tokens"][k]
            cost += cost_of(s["tokens"], pricing(s["family"] or fam))
        r["tokens"] = {"in": tok["input"], "out": tok["output"], "cache_read": tok["cache_read"],
                       "cache_write": tok["cache_write_5m"] + tok["cache_write_1h"],
                       "cache_write_5m": tok["cache_write_5m"], "cache_write_1h": tok["cache_write_1h"]}
        r["cost_usd"] = round(cost, 6)
        r["tool_calls"] = sum(s["tool_calls"] for s in real)
        r["output_tokens_estimated"] = True  # the stream's output_tokens is an early snapshot; see mechanical.py
        last = real[-1] if real else None
        r["status"] = last["status"] if last else None
        r["status_reason"] = None
        if last and last["status"] in ("NEEDS_CONTEXT", "BLOCKED"):
            r["status_reason"] = re.sub(r"\s+", " ", last["text"])[:240]
        r["complete"] = bool(last and last["complete"])
        # rework: fixer / re-dispatch segments, plus incidents and fix notes that name the task
        rw_s = sum(s["end_s"] - s["start_s"] for s in fixes)
        rw_cost = sum(cost_of(s["tokens"], pricing(s["family"])) for s in fixes)
        kind_miss = [i for i in incidents if str(i.get("context", "")).lower().startswith("kind-miss")
                     and (_tid(str(i.get("context", ""))) == tid or _norm(str(i.get("file", ""))) in owned.get(tid, ()))]
        note_hit = [n for n in fix_notes if re.search(rf"\bF-{tid}-\d+|\b{tid}\b", n)]
        r["rework_dispatches"] = len(fixes)
        r["kind_miss_incidents"] = len(kind_miss)
        r["fix_notes"] = len(note_hit)
        r["rework_s"] = round(rw_s, 1)
        r["rework_cost"] = round(rw_cost, 6)
        reworked = bool(fixes or kind_miss or note_hit)
        if not real or r["status"] is None:
            r["first_time_pass"] = None  # not observable: no finished build assignment
        else:
            red = bool(_RED.search(last["text"])) and r["status"] != "DONE"
            r["first_time_pass"] = r["status"] in ("DONE", "DONE_WITH_CONCERNS") and not red and not reworked
        done = max([r["end_s"]] + [s["end_s"] for s in fixes]) if real else None
        r["done_s"] = done

    # timing graph: actual critical path, slack, start lag
    known = {t: r for t, r in recs.items() if r.get("start_s") is not None and r.get("done_s") is not None}
    deps = {t: [d for d in graph.get(t, []) if d in known] for t in known}
    succ: dict[str, list[str]] = {t: [] for t in known}
    for t, ds in deps.items():
        for d in ds:
            succ[d].append(t)
    run_end = max((r["done_s"] for r in known.values()), default=0.0)
    for t, r in known.items():
        r["start_lag_s"] = round(max(0.0, r["start_s"] - max(known[d]["done_s"] for d in deps[t])), 1) if deps[t] else None
    for t, r in known.items():
        # how much later t could finish without delaying a successor (its own start lag excluded)
        gaps = [known[s]["start_s"] - r["done_s"] - (known[s]["start_lag_s"] or 0.0) for s in succ[t]]
        r["slack_s"] = round(max(0.0, min(gaps) if gaps else run_end - r["done_s"]), 1)
        r["on_critical_path"] = False
    # actual critical path: walk back from the last-finishing tasks through the latest-finishing
    # dependencies (finish times within 1 s tie, e.g. a run killed while tasks were in flight)
    todo = [t for t in known if known[t]["done_s"] >= run_end - 1.0]
    while todo:
        cur = todo.pop()
        if known[cur]["on_critical_path"]:
            continue
        known[cur]["on_critical_path"] = True
        if deps[cur]:
            top = max(known[d]["done_s"] for d in deps[cur])
            todo += [d for d in deps[cur] if known[d]["done_s"] >= top - 1.0]
    for t, r in recs.items():
        if t not in known:
            r.update({"start_lag_s": None, "slack_s": None, "on_critical_path": None})
    return sorted(recs.values(), key=lambda r: [int(x) for x in re.findall(r"\d+", r["task"])])


def mechanical_block(tasks: list[dict], graph: dict, prices: dict, speeds: dict, plan=None,
                     other_haiku: list[dict] | None = None) -> dict:
    """The per-run `mechanical` block of the score JSON."""
    n = len(tasks)
    loc_total = sum(t.get("loc") or 0 for t in tasks)

    def share(key):
        out: dict[str, dict] = {}
        for t in tasks:
            k = str(t.get(key))
            o = out.setdefault(k, {"tasks": 0, "loc": 0})
            o["tasks"] += 1
            o["loc"] += t.get("loc") or 0
        for o in out.values():
            o["task_share"] = round(o["tasks"] / n, 3) if n else None
            o["loc_share"] = round(o["loc"] / loc_total, 3) if loc_total else None
        return out

    mech = [t for t in tasks if t.get("kind") == "mechanical"]
    block: dict = {
        "plan_tasks": len(plan.by_id) if plan is not None else None,
        "plan_mechanical": (sum(1 for t in plan.by_id.values() if t.explicit_features.get("kind") == "mechanical")
                            if plan is not None else None),
        "tasks_built": n, "by_kind": share("kind"), "by_model": share("model"),
        "mechanical_by_model": {}, "haiku": None, "counterfactual_sonnet": None,
        "other_haiku_dispatches": other_haiku or [],
    }
    for t in mech:
        o = block["mechanical_by_model"].setdefault(str(t["model"]), {"tasks": 0, "time_s": 0.0, "cost_usd": 0.0})
        o["tasks"] += 1
        o["time_s"] = round(o["time_s"] + (t.get("duration_s") or 0), 1)
        o["cost_usd"] = round(o["cost_usd"] + t["cost_usd"] + t["rework_cost"], 4)
    hk = [t for t in tasks if t.get("model") == "haiku"]
    sn = [t for t in tasks if t.get("model") == "sonnet"]
    if not hk:
        block["note"] = "no Haiku tasks in this run"
        return block
    obs = [t for t in hk if t["first_time_pass"] is not None]
    passed = [t for t in obs if t["first_time_pass"]]
    stuck = [t for t in hk if t.get("status") in ("NEEDS_CONTEXT", "BLOCKED")]
    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None  # noqa: E731
    block["haiku"] = {
        "tasks": len(hk), "observed": len(obs), "first_time_pass": len(passed),
        "first_time_pass_rate": round(len(passed) / len(obs), 3) if obs else None,
        "incomplete": [t["task"] for t in hk if not t["complete"]],
        "rework_s": round(sum(t["rework_s"] for t in hk), 1),
        "rework_cost_usd": round(sum(t["rework_cost"] for t in hk), 4),
        "needs_context_or_blocked": len(stuck),
        "stuck_reasons": {t["task"]: {"status": t["status"], "reason": t["status_reason"]} for t in stuck},
        "tool_calls_per_task": avg([t["tool_calls"] for t in hk]),
        "sonnet_tool_calls_per_task": avg([t["tool_calls"] for t in sn]),
    }
    block["counterfactual_sonnet"] = counterfactual(tasks, graph, prices, speeds)
    return block


def counterfactual(tasks: list[dict], graph: dict, prices: dict, speeds: dict) -> dict:
    """ESTIMATE of the Haiku tasks had they run on Sonnet: tokens re-priced at Sonnet prices; duration =
    measured duration - Haiku generation time + the same output at Sonnet's measured speed; Sonnet is
    assumed to pass first time (no rework). Run effect: a forward pass over the task graph with the
    measured start lags, so a task with slack moves the run end by 0."""
    th = speeds.get("haiku") or 150
    ts = speeds.get("sonnet") or 80
    rows, d_cost, d_time = [], 0.0, 0.0
    cfdur: dict[str, float] = {}
    for t in tasks:
        if t.get("model") != "haiku" or not t.get("duration_s"):
            continue
        tok = t["tokens"]
        tk = {"input": tok["in"], "output": tok["out"], "cache_read": tok["cache_read"],
              "cache_write_5m": tok["cache_write_5m"], "cache_write_1h": tok["cache_write_1h"]}
        son_cost = cost_of(tk, prices["sonnet"])
        gen_h = min(tok["out"] / th, t["duration_s"])
        son_dur = t["duration_s"] - gen_h + tok["out"] / ts
        cfdur[t["task"]] = son_dur
        actual = t["cost_usd"] + t["rework_cost"]
        rows.append({"task": t["task"], "haiku_cost_usd": round(actual, 4), "sonnet_cost_usd": round(son_cost, 4),
                     "haiku_s": t["duration_s"], "sonnet_s": round(son_dur, 1)})
        d_cost += son_cost - actual
        d_time += son_dur - t["duration_s"]
    known = {t["task"]: t for t in tasks if t.get("start_s") is not None and t.get("done_s") is not None}
    deps = {t: [d for d in graph.get(t, []) if d in known] for t in known}
    order = _order(deps)
    dur, lag, st0 = {}, {}, {}
    for t, r in known.items():
        build = r["done_s"] - r["start_s"]
        dur[t] = cfdur.get(t, build)
        lag[t] = r.get("start_lag_s") or 0.0
        st0[t] = r["start_s"]
    actual_end = max((r["done_s"] for r in known.values()), default=None)
    cf_end = max(_topo_forward(order, deps, dur, lag, st0).values(), default=None)
    return {
        "LABEL": "COUNTERFACTUAL ESTIMATE, not measured: Haiku tasks re-priced and re-timed as if run on Sonnet",
        "assumes": "same tokens; Sonnet first-time pass (no rework); duration scaled by output tokens at models.json tps",
        "tasks": rows,
        "sonnet_minus_haiku_cost_usd": round(d_cost, 4),
        "haiku_saves_cost_usd": round(d_cost, 4),
        "sum_task_time_saved_s": round(d_time, 1),
        "critical_path_saved_s": round(cf_end - actual_end, 1) if cf_end is not None and actual_end is not None else None,
        "off_critical_path_tasks": [t["task"] for t in tasks if t.get("model") == "haiku" and t.get("on_critical_path") is False],
    }


def _order(deps: dict[str, list[str]]) -> list[str]:
    seen, out = set(), []

    def visit(t):
        if t in seen:
            return
        seen.add(t)
        for d in deps.get(t, []):
            visit(d)
        out.append(t)
    for t in deps:
        visit(t)
    return out


def other_haiku(events: list[dict], prices: dict, plan_tids: set[str]) -> list[dict]:
    """Haiku assignments that belong to no plan task (e.g. the Wave 0 script run): description, time, cost."""
    out = []
    for s in segments(events):
        if s["family"] == "haiku" and s["kind"] != "prime" and s["tid"] not in plan_tids:
            out.append({"description": s["description"], "status": s["status"], "duration_s": round(s["end_s"] - s["start_s"], 1),
                        "cost_usd": round(cost_of(s["tokens"], prices["haiku"]), 4), "tool_calls": s["tool_calls"]})
    return out
