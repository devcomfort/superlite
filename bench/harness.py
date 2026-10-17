"""Benchmark harness: run one arm headless, then score it against the hidden suite.

Usage (from the repo root):
    uv run --no-project python bench/harness.py run <arm> <rep> [--smoke]
    uv run --no-project python bench/harness.py score <arm> <rep>
    uv run --no-project python bench/harness.py report

Arms: superpowers (stock plugin as installed) and superlite (this repo via --plugin-dir,
superpowers disabled). Both disable the user-level orchestrator skill.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
# Outside the repo, so an arm can't wander up into hidden_tests/ or reference/.
RUNS = Path(os.environ.get("BENCH_RUNS", ROOT.parent / "superlite-bench-runs"))
RESULTS = BENCH / "results"
# BENCH_TASK picks the task: "sitegen" (bench/task + bench/hidden_tests) or a dir under bench/tasks/
# holding SPEC.md and hidden/. Non-default tasks prefix run and result names with the task name.
TASK = os.environ.get("BENCH_TASK", "sitegen")
TASK_SPEC = BENCH / "task" / "SPEC.md" if TASK == "sitegen" else BENCH / "tasks" / TASK / "SPEC.md"
TASK_HIDDEN = BENCH / "hidden_tests" if TASK == "sitegen" else BENCH / "tasks" / TASK / "hidden"
PREFIX = "" if TASK == "sitegen" else f"{TASK}-"
MARKER = "BENCHMARK-COMPLETE"
MAX_RESUMES = 6
RESUME_PROMPT = (
    "Approved. No human is available - make the decision yourself and continue "
    "until SPEC.md is fully built, tested and committed. End with the line BENCHMARK-COMPLETE."
)
SMOKE_PROMPT = (
    "List the names of the skills and agent types available to you that come from plugins "
    "(one per line, no commentary), then end with the line BENCHMARK-COMPLETE."
)

ARM_ARGS = {
    "superpowers": ["--settings", json.dumps({"skillOverrides": {"orchestrator": "off"}})],
    "superlite": [
        "--settings",
        json.dumps({
            "enabledPlugins": {"superpowers@claude-plugins-official": False},
            "skillOverrides": {"orchestrator": "off"},
        }),
        "--plugin-dir", str(ROOT),
    ],
}


def common_args(budget: str) -> list[str]:
    return [
        "--model", "opus",
        "--permission-mode", "auto",
        "--permission-prompts", "none",
        "--output-format", "stream-json", "--verbose",
        "--max-budget-usd", budget,
        "--disallowedTools", "Skill(orchestrator)",
    ]


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def read_events(log: Path) -> list[dict]:
    events = []
    if not log.exists():
        return events
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return events


def results_of(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "result"]


def clean_env() -> dict[str, str]:
    """Drop variables inherited from a host Claude session (e.g. CLAUDE_CODE_SIMPLE turns on
    bare mode, which skips plugin hooks), so each arm runs like a fresh terminal session."""
    return {k: v for k, v in os.environ.items()
            if not (k.startswith("CLAUDE") or k.startswith("ANTHROPIC"))}


def arm_env() -> dict[str, str]:
    env = clean_env()
    # Fork subagents are on by default in interactive sessions but off in -p; turn them on so
    # headless arms behave like the interactive sessions a user would actually run.
    env["CLAUDE_CODE_FORK_SUBAGENT"] = "1"
    return env


def invoke(cmd: list[str], cwd: Path, log: Path, err: Path) -> None:
    with log.open("a", encoding="utf-8") as out, err.open("a", encoding="utf-8") as er:
        subprocess.run(cmd, cwd=cwd, stdout=out, stderr=er, stdin=subprocess.DEVNULL, env=arm_env())


DECIDER_TOOLS_OFF = "Bash Edit Write Read Glob Grep Agent WebFetch WebSearch NotebookEdit Skill"


def decide(claude: str, question: str, cwd: Path) -> tuple[str, float, float]:
    """Ask the Opus decision-maker (who plays the human) to answer the arm's last message.
    Returns (answer, seconds, cost_usd). It runs tool-less, skill-less and plugin-free."""
    spec = TASK_SPEC.read_text(encoding="utf-8")
    prompt = (f"<spec>\n{spec}\n</spec>\n\n<agent_message>\n{question[-8000:]}\n</agent_message>\n\n"
              "Reply now as the product owner.")
    # Prompt via stdin and system prompt via file: the SPEC alone is ~29k chars, and Windows
    # caps a command line at 32k.
    cmd = [claude, "-p", "--model", "opus", "--output-format", "json",
           "--system-prompt-file", str(BENCH / "decider.md"),
           "--disable-slash-commands", "--disallowedTools", DECIDER_TOOLS_OFF,
           "--settings", json.dumps({"enabledPlugins": {"superpowers@claude-plugins-official": False}}),
           "--no-session-persistence", "--max-budget-usd", "2"]
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=cwd, input=prompt, capture_output=True, text=True,
                          encoding="utf-8", env=clean_env())
    secs = time.time() - t0
    try:
        out = json.loads(proc.stdout)
        return (out.get("result") or "Continue.").strip(), secs, out.get("total_cost_usd") or 0.0
    except json.JSONDecodeError:
        return "Approved. Continue, and decide anything else yourself.", secs, 0.0


def cmd_run(arm: str, rep: str, smoke: bool, human: bool = False) -> None:
    claude = shutil.which("claude") or "claude"
    name = f"{PREFIX}{arm}-{rep}" + ("-smoke" if smoke else "")
    run_dir = RUNS / name
    RESULTS.mkdir(parents=True, exist_ok=True)
    log, err = RESULTS / f"{name}.jsonl", RESULTS / f"{name}.stderr"
    if run_dir.exists():
        sys.exit(f"run dir exists: {run_dir}")
    run_dir.mkdir(parents=True)
    shutil.copy(TASK_SPEC, run_dir / "SPEC.md")
    git(run_dir, "init", "-q", "-b", "main")
    git(run_dir, "add", "SPEC.md")
    git(run_dir, "-c", "user.name=bench", "-c", "user.email=bench@local", "commit", "-qm", "Add SPEC.md")

    budget = os.environ.get("BENCH_BUDGET", "1" if smoke else "60")
    base = [claude, "-p"]
    extra = common_args(budget) + ARM_ARGS[arm]
    prompt_file = "prompt-human.md" if human else "prompt.md"
    prompt = SMOKE_PROMPT if smoke else (BENCH / prompt_file).read_text(encoding="utf-8")

    t0 = time.time()
    invoke(base + [prompt] + extra, run_dir, log, err)
    resumes, decider_s, decider_cost = 0, 0.0, 0.0
    transcript = RESULTS / f"{name}.decisions.md"
    max_resumes = 12 if human else MAX_RESUMES
    while not smoke and resumes < max_resumes:
        res = results_of(read_events(log))
        if not res or MARKER in (res[-1].get("result") or ""):
            break
        sid = res[-1].get("session_id")
        if not sid:
            break
        resumes += 1
        if human:
            question = res[-1].get("result") or ""
            answer, secs, cost = decide(claude, question, run_dir)
            decider_s, decider_cost = decider_s + secs, decider_cost + cost
            with transcript.open("a", encoding="utf-8") as f:
                f.write(f"## Stop {resumes} (decider {secs:.0f}s)\n\n### Agent asked\n\n{question[-4000:]}\n\n"
                        f"### Decider answered\n\n{answer}\n\n")
            reply = answer
        else:
            reply = RESUME_PROMPT
        invoke(base + [reply, "--resume", sid] + extra, run_dir, log, err)
    wall = time.time() - t0
    meta = {"arm": arm, "rep": rep, "smoke": smoke, "mode": "human" if human else "preapproved",
            "wall_s": round(wall, 1), "arm_wall_s": round(wall - decider_s, 1), "resumes": resumes,
            "decider_s": round(decider_s, 1), "decider_cost_usd": round(decider_cost, 3)}
    (RESULTS / f"{name}.meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta))


def stream_stats(events: list[dict]) -> dict:
    agent_calls, models, coord_tools = 0, {}, 0
    for e in events:
        if e.get("type") != "assistant":
            continue
        top = e.get("parent_tool_use_id") is None
        for block in (e.get("message") or {}).get("content") or []:
            if block.get("type") != "tool_use":
                continue
            if top:
                coord_tools += 1
            if block.get("name") in ("Agent", "Task"):
                agent_calls += 1
                m = (block.get("input") or {}).get("model") or "(default)"
                models[m] = models.get(m, 0) + 1
    return {"agent_dispatches": agent_calls, "dispatch_models": models, "coordinator_tool_calls": coord_tools}


def _ts(e: dict) -> float | None:
    s = e.get("timestamp")
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _ctx(u: dict) -> int:
    return ((u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
            + (u.get("cache_creation_input_tokens") or 0))


def dispatch_stats(events: list[dict]) -> dict:
    """Per-dispatch cache/context metrics, coordinator context, concurrency and a phase timeline.
    Assistant events are deduped by message.id; output_tokens is deliberately not used (it is an
    early-stream snapshot). Subagent events carry parent_tool_use_id == the coordinator's Agent
    tool_use id (also for SendMessage-resumed agents); an unknown parent becomes its own dispatch."""
    stamps = [t for t in map(_ts, events) if t is not None]
    t0 = min(stamps) if stamps else 0.0
    seen: set[str] = set()
    coord: list[int] = []
    agent_inputs: dict[str, dict] = {}   # Agent tool_use id -> input
    calls: dict[str, list[dict]] = {}    # dispatch id -> its API calls, in order
    span: dict[str, list[float]] = {}
    evtype: dict[str, str] = {}
    plan_write: float | None = None
    for idx, e in enumerate(events):
        if e.get("type") not in ("assistant", "user"):
            continue
        t = _ts(e)
        t = (t - t0) if t is not None else float(idx)
        parent = e.get("parent_tool_use_id")
        if parent:
            sp = span.setdefault(parent, [t, t])
            sp[1] = max(sp[1], t)
            if e.get("subagent_type"):
                evtype.setdefault(parent, e["subagent_type"])
        if e.get("type") != "assistant":
            continue
        msg = e.get("message") or {}
        # Each content block arrives as its own event sharing one message.id: scan blocks on every
        # event, but count a message's usage once.
        for b in msg.get("content") or []:
            if b.get("type") != "tool_use":
                continue
            inp = b.get("input") or {}
            if not parent and b.get("name") in ("Agent", "Task"):
                agent_inputs[b["id"]] = inp
            if (b.get("name") == "Write" and plan_write is None
                    and re.search(r"(^|/)docs/.*(plan|spec)", str(inp.get("file_path", "")).replace("\\", "/"), re.I)):
                plan_write = t
        mid = msg.get("id")
        if mid in seen or not isinstance(msg.get("usage"), dict):
            continue
        seen.add(mid)
        u = msg["usage"]
        if parent:
            calls.setdefault(parent, []).append({"model": msg.get("model") or "", "u": u})
        else:
            coord.append(_ctx(u))
    order = list(agent_inputs) + [p for p in span if p not in agent_inputs]
    order.sort(key=lambda p: span[p][0] if p in span else float("inf"))
    dispatches = []
    for did in order:
        inp = agent_inputs.get(did, {})
        cs = calls.get(did, [])
        sp = span.get(did)
        dispatches.append({
            "subagent_type": inp.get("subagent_type") or evtype.get(did) or "general-purpose",
            "model": (cs[0]["model"] if cs else inp.get("model") or "").replace("claude-", "") or None,
            "effort": inp.get("effort"),
            "description": inp.get("description"),
            "api_calls": len(cs),
            "first_call_cache_read": (cs[0]["u"].get("cache_read_input_tokens") or 0) if cs else None,
            "first_call_cache_write": (cs[0]["u"].get("cache_creation_input_tokens") or 0) if cs else None,
            "peak_context": max((_ctx(c["u"]) for c in cs), default=0),
            "total_cache_read": sum(c["u"].get("cache_read_input_tokens") or 0 for c in cs),
            "total_cache_write": sum(c["u"].get("cache_creation_input_tokens") or 0 for c in cs),
            "start_s": round(sp[0], 1) if sp else None,
            "end_s": round(sp[1], 1) if sp else None,
        })

    # Cache sharing: a sibling's first call that reads well beyond its type's bare system prefix.
    by_type: dict[str, list[dict]] = {}
    for d in dispatches:
        if d["api_calls"]:
            by_type.setdefault(d["subagent_type"], []).append(d)
    hits = total = 0
    for ds in by_type.values():
        floor = min(d["first_call_cache_read"] for d in ds)
        for d in ds[1:]:
            total += 1
            hits += d["first_call_cache_read"] > floor + 1000
    # Concurrency: sweep the dispatch intervals (ends sort before starts at the same instant).
    marks = sorted([(d["start_s"], 1) for d in dispatches if d["start_s"] is not None]
                   + [(d["end_s"], -1) for d in dispatches if d["end_s"] is not None], key=lambda m: (m[0], m[1]))
    cur = peak = 0
    for _, delta in marks:
        cur += delta
        peak = max(peak, cur)

    def kind(d: dict, word: str) -> bool:
        return word in ((d["subagent_type"] or "") + " " + (d["description"] or "")).lower()

    impls = [d for d in dispatches if d["start_s"] is not None and
             (d["subagent_type"].endswith("implementer") or re.match(r"(implement|t\d)", (d["description"] or "").lower()))]
    finals = [d for d in dispatches if d["start_s"] is not None and kind(d, "review") and kind(d, "final")
              and not kind(d, "fix") and not kind(d, "re-review")]
    final = min(finals, key=lambda d: d["start_s"]) if finals else None
    last_t = max((t - t0 for t in stamps), default=None)
    timeline = {
        "plan_write_s": round(plan_write, 1) if plan_write is not None else None,
        "first_implementer_s": min(d["start_s"] for d in impls) if impls else None,
        "last_implementer_end_s": max(d["end_s"] for d in impls) if impls else None,
        "final_review_start_s": final["start_s"] if final else None,
        "final_review_end_s": final["end_s"] if final else None,
        "last_event_s": round(last_t, 1) if last_t is not None else None,
    }
    return {
        "dispatches": dispatches,
        "sibling_first_call_hit_rate": round(hits / total, 3) if total else None,
        "fork_dispatches": sum(1 for d in dispatches if d["subagent_type"] == "fork"),
        "reviewer_dispatches": sum(1 for d in dispatches if kind(d, "review")),
        "implementer_dispatches": len(impls),
        "orchestrated": len(impls) >= 2,
        "coordinator_calls": len(coord),
        "coordinator_context_median": int(statistics.median(coord)) if coord else None,
        "coordinator_context_max": max(coord, default=None),
        "max_concurrent_agents": peak,
        "timeline": timeline,
    }


def hidden_score(run_dir: Path, suite: Path | None = None, key: str = "hidden") -> dict:
    suite = suite or TASK_HIDDEN
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "w"
        shutil.copytree(run_dir, work, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"))
        shutil.copytree(suite, work / "hidden_tests")
        junit = Path(tmp) / "junit.xml"
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(work / "src"), str(work)]))
        # A task may list extra test-only packages (e.g. playwright) in hidden/requirements.txt.
        req = TASK_HIDDEN / "requirements.txt"  # the task's extras serve every suite
        pkgs = [ln.strip() for ln in (req.read_text(encoding="utf-8").splitlines() if req.exists() else [])]
        extras = [w for pkg in pkgs if pkg and not pkg.startswith("#") for w in ("--with", pkg)]
        subprocess.run(
            ["uv", "run", "--no-project", "--with", "pytest", *extras, "python", "-m", "pytest",
             "hidden_tests", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"],
            cwd=work, env=env, capture_output=True, timeout=900,
        )
        if not junit.exists():
            return {f"{key}_passed": 0, f"{key}_total": None, f"{key}_failed_ids": ["(no junit)"]}
        total, failed, by_file = 0, [], {}
        for case in ET.parse(junit).getroot().iter("testcase"):
            total += 1
            # hidden_tests.test_api -> test_api; with suite subdirs (importlib mode) keep "suite.test_x".
            parts = (case.get("classname") or "").split(".")
            f = ".".join(parts[-2:]) if len(parts) >= 2 and parts[-2] not in ("hidden_tests",) else parts[-1]
            bucket = by_file.setdefault(f, [0, 0])
            bucket[1] += 1
            if any(child.tag in ("failure", "error", "skipped") for child in case):
                failed.append(f"{case.get('classname')}::{case.get('name')}")
            else:
                bucket[0] += 1
        return {f"{key}_passed": total - len(failed), f"{key}_total": total, f"{key}_failed_ids": failed,
                f"{key}_by_file": {k: f"{p}/{t}" for k, (p, t) in sorted(by_file.items())}}


def own_tests(run_dir: Path) -> dict:
    proc = subprocess.run(
        ["uv", "run", "--no-project", "--with", "pytest", "python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "--ignore=hidden_tests"],
        cwd=run_dir, env=dict(os.environ, PYTHONPATH=os.pathsep.join([str(run_dir / "src"), str(run_dir)])), capture_output=True, text=True, timeout=600,
    )
    tail = proc.stdout.strip().splitlines()[-1:] or [""]
    return {"own_tests_summary": tail[0]}


def cmd_score(arm: str, rep: str) -> dict:
    name = f"{PREFIX}{arm}-{rep}"
    run_dir = RUNS / name
    meta_path = RESULTS / f"{name}.meta.json"
    deadline = time.time() + 8 * 3600
    while not meta_path.exists() and time.time() < deadline:
        time.sleep(60)  # the run is still going (e.g. launched in parallel); meta is written at its end
    events = read_events(RESULTS / f"{name}.jsonl")
    res = results_of(events)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    # A session emits a result event each time the coordinator idles while background agents
    # run; cost and modelUsage in each are cumulative for the session, so keep only the last
    # result per session (resumes start new sessions). num_turns is per segment, so it sums.
    last_per_session: dict[str, dict] = {}
    for r in res:
        last_per_session[r.get("session_id") or ""] = r
    turns = sum(r.get("num_turns") or 0 for r in res)
    res_all, res = res, list(last_per_session.values())
    model_usage: dict[str, dict] = {}
    for r in res:
        for model, u in (r.get("modelUsage") or {}).items():
            agg = model_usage.setdefault(model, {})
            for k, v in u.items():
                if isinstance(v, (int, float)):
                    agg[k] = agg.get(k, 0) + v
    src_loc = sum(len(p.read_text(encoding="utf-8", errors="replace").splitlines())
                  for p in (run_dir / "src").rglob("*.py")) if (run_dir / "src").exists() else 0
    commits = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=run_dir,
                             capture_output=True, text=True).stdout.strip()
    score = {
        **meta,
        "cost_usd": round(sum(r.get("total_cost_usd") or 0 for r in res), 2),
        "turns": turns,
        "api_s": round(sum(r.get("duration_api_ms") or 0 for r in res) / 1000, 1),
        "result_events": len(res_all),
        "completed_marker": bool(res_all) and MARKER in (res_all[-1].get("result") or ""),
        "last_subtype": res_all[-1].get("subtype") if res_all else None,
        **stream_stats(events),
        **dispatch_stats(events),
        "model_usage": model_usage,
        "src_loc": src_loc,
        "commits": int(commits or 0),
        **own_tests(run_dir),
        **hidden_score(run_dir),
        # Optional beyond-SPEC robustness probes (bench/tasks/<task>/robustness/), scored separately.
        **(hidden_score(run_dir, TASK_HIDDEN.parent / "robustness", "robust")
           if (TASK_HIDDEN.parent / "robustness").is_dir() else {}),
    }
    (RESULTS / f"{name}.json").write_text(json.dumps(score, indent=2), encoding="utf-8")
    brief = {k: v for k, v in score.items() if k not in ("model_usage", "hidden_failed_ids", "dispatches")}
    print(json.dumps(brief, indent=2))
    return score


def cmd_report() -> None:
    paths = [p for p in sorted(RESULTS.glob("*-*.json"))
             if re.fullmatch(rf"{re.escape(PREFIX)}(superpowers|superlite)-[a-z]?\d+\.json", p.name)]
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    for r in rows:
        r["decisions"] = r.get("resumes") if r.get("mode") == "human" else ""
        r["arm_wall_s"] = r.get("arm_wall_s", r.get("wall_s"))
        r["sibling_hit_rate"] = r.get("sibling_first_call_hit_rate", "")
        r["coord_ctx_median"] = r.get("coordinator_context_median", "")
    cols = ["arm", "rep", "wall_s", "arm_wall_s", "cost_usd", "turns", "resumes", "decisions", "agent_dispatches",
            "coordinator_tool_calls", "sibling_hit_rate", "coord_ctx_median", "hidden_passed", "hidden_total",
            "own_tests_summary", "src_loc", "commits"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    print("\n".join(lines))


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if args[0] == "run":
        cmd_run(args[1], args[2], "--smoke" in args, "--human" in args)
    elif args[0] == "score":
        cmd_score(args[1], args[2])
    elif args[0] == "report":
        cmd_report()
    else:
        sys.exit(__doc__)
