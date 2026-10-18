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
# Optional starting repo: bench/tasks/<task>/start/ is copied into the run dir and committed before the arm starts.
TASK_START = None if TASK == "sitegen" else BENCH / "tasks" / TASK / "start"
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


def seed_run_dir(run_dir: Path) -> None:
    """Fresh git repo in run_dir holding SPEC.md and, if the task has one, its start/ tree."""
    has_start = TASK_START is not None and TASK_START.is_dir()
    if has_start:
        shutil.copytree(TASK_START, run_dir, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
    shutil.copy(TASK_SPEC, run_dir / "SPEC.md")
    git(run_dir, "init", "-q", "-b", "main")
    git(run_dir, "add", "-A" if has_start else "SPEC.md")
    git(run_dir, "-c", "user.name=bench", "-c", "user.email=bench@local", "commit", "-qm",
        "Add SPEC.md and starting repo" if has_start else "Add SPEC.md")


def cmd_run(arm: str, rep: str, smoke: bool, human: bool = False) -> None:
    claude = shutil.which("claude") or "claude"
    name = f"{PREFIX}{arm}-{rep}" + ("-smoke" if smoke else "")
    run_dir = RUNS / name
    RESULTS.mkdir(parents=True, exist_ok=True)
    log, err = RESULTS / f"{name}.jsonl", RESULTS / f"{name}.stderr"
    if run_dir.exists():
        sys.exit(f"run dir exists: {run_dir}")
    run_dir.mkdir(parents=True)
    seed_run_dir(run_dir)

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


# ---- 0.3 benchmark metrics (T7) -------------------------------------------------------------
# USD per million tokens: (input, output, cache write 5m, cache write 1h, cache read). Mirrors
# skills/subagent-driven-development/config/models.json; review_cost_usd is an estimate.
PRICES = {"opus": (4.0, 20.0, 5.0, 8.0, 0.2), "sonnet": (2.0, 10.0, 2.5, 4.0, 0.1),
          "haiku": (0.1, 0.5, 0.125, 0.2, 0.01)}
# Same patterns as hooks/block-unsafe-kill: kill by image name or pattern.
UNSAFE_KILL = re.compile(
    r"(?:^|[\s;&|(`])(?:taskkill\b[^\n]*?\s//?im(?!\w)|(?:pkill|killall)(?![\w-])"
    r"|stop-process\b[^\n]*?\s-name(?!\w)|kill\s+-9\s+-1(?!\d))", re.I)
_PRIME_RE = re.compile(r"do not act yet|\bREADY\b")
_POLL_RE = re.compile(r"relevance\s*(?:score\s*)?0\s*(?:-|–|—|to)\s*10", re.I)
_QUEUE_RE = re.compile(r"\bdo (?:this |it |these )?after\b|\bqueued? (?:behind|after)\b"
                       r"|\bafter you (?:finish|complete|are done)\b", re.I)
_FIX_RE = re.compile(r"\bfix(?:es|ed)?\b", re.I)
_TASK_KEY_RE = re.compile(r"\b(?:task|T)\s*([A-Za-z]?\d+[A-Za-z]?)\b", re.I)
_VERDICT_RE = re.compile(r"^\W*verdict\b\s*[:\-—*]", re.I | re.M)
# Implementer descriptions: "Implement ...", "T3 ...", "Task 3 ...", "Task A1 ..." (letter + digit ids).
_IMPL_DESC_RE = re.compile(r"(implement|t\d|task\s*[a-z]?\d)")
_BATCH_RE = re.compile(r"batch|package|wave|\btasks\s+\w+\s*(?:[,/&+]|and)\s*\w+", re.I)
_PRIME_HASH_RE = re.compile(r"prime[-_ ]hash\W{0,3}([0-9a-f]{8,64})", re.I)
_SEAM_RE = re.compile(r"plan_tools\.py\s+(?:contract|seam)|\bseam[-_ ]?(?:check|smoke)\b", re.I)


def _text_of(x) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        return "\n".join(_text_of(i.get("text") if isinstance(i, dict) and "text" in i else i) for i in x)
    return json.dumps(x) if x is not None else ""


def _task_key(text: str) -> str | None:
    m = _TASK_KEY_RE.search(text or "")
    return m.group(1).lower() if m else None


def _call_kind(inp: dict) -> str:
    """Classify an Agent dispatch: fix | final_review | review | test | build | other."""
    desc = inp.get("description") or ""
    words = ((inp.get("subagent_type") or "") + " " + desc).lower()
    if _FIX_RE.search(desc):
        return "fix"
    if "review" in words:
        return "final_review" if "final" in words and "re-review" not in words else "review"
    if re.search(r"test[-_ ]?runner|\brun (?:the )?(?:full )?(?:suite|tests?)\b|\bfull suite\b", words):
        return "test"
    if (inp.get("subagent_type") or "").endswith("implementer") or _IMPL_DESC_RE.match(desc.lower()):
        return "build"
    return "other"


def _plan_numbers(plan_text: str, results_text: str) -> tuple[dict, float | None, float | None]:
    """Predicted per-task Est. time (s), predicted total (s) and predicted critical path (s), read
    from the plan text and from `plan_tools.py schedule` output."""
    est: dict[str, float] = {}
    cur = None
    for line in plan_text.splitlines():
        h = re.match(r"#{2,4}\s*(?:Task|T)\s*([A-Za-z]?\d+[A-Za-z]?)\b", line, re.I)
        if h:
            cur = h.group(1).lower()
        m = re.search(r"Est\. time:?\*{0,2}\s*([\d.]+)\s*(min|s)\b", line)
        if m and cur:
            est[cur] = float(m.group(1)) * (60 if m.group(2) == "min" else 1)
    corpus = plan_text + "\n" + results_text
    tot = re.findall(r"predicted total\s*[≈~=:]*\s*([\d.]+)\s*min", corpus, re.I)
    cp = re.findall(r"critical path:[^\n(]*\(([\d.]+)\s*min\)", corpus, re.I)
    return est, (float(tot[-1]) * 60 if tot else None), (float(cp[-1]) * 60 if cp else None)


def flow_metrics(events: list[dict], t0: float, last_t: float | None, coordinator_turns: int) -> dict:
    """Agent-flow metrics from one pass over the stream: assignments to agents (idle reuse, queued
    work, polls), per-assignment segments (system task_started .. task_notification, the only
    reliable busy/idle markers), the build/review/fix tail, and 0.3 script and safety signals.
    System events carry no timestamp, so their time is the latest timestamped event before them.
    Signals whose source events don't exist in older logs (polls, seams, prime hashes, plan
    predictions) come back as None or 0 and never raise."""
    stamped = any(_ts(e) is not None for e in events)
    tf: list[float] = []
    cur = 0.0
    for i, e in enumerate(events):
        t = _ts(e)
        cur = (t - t0) if t is not None else (cur if stamped else float(i))
        tf.append(cur)

    agents: dict[str, dict] = {}
    agent_of_call: dict[str, str] = {}
    name_of_agent: dict[str, str] = {}
    calls: dict[str, dict] = {}           # coordinator Agent tool_use id -> {idx, t, inp}
    msgs: dict[str, dict] = {}            # coordinator SendMessage tool_use id -> message record
    segs: list[dict] = []
    assigns: list[dict] = []
    polls: dict[str, dict] = {}
    seen_tu: set[str] = set()
    usage: dict[str, dict] = {}
    watch: dict[str, str] = {}            # tool_use id of a command whose output we read
    results: dict[str, str] = {}
    plan_writes: list[str] = []
    incidents: dict[str, int] = {}
    unsafe = graphify = 0
    seam_ids: list[str] = []
    top_assist: list[int] = []
    notifs: list[tuple[int, dict]] = []

    def new_agent(aid: str, call: str, pseudo: bool = False) -> dict:
        ag = {"id": aid, "call": call, "tasks": 0, "ctx": 0, "open": None, "pseudo": pseudo, "n": 0}
        agents[aid] = ag
        agent_of_call[call] = aid
        return ag

    def open_seg(ag: dict, idx: int, kind: str, text: str, call: str) -> None:
        s = {"agent": ag["id"], "call": call, "kind": kind, "start": tf[idx], "end": None, "first": None,
             "last": None, "key": _task_key(text[:300]) if kind == "build" else None,
             "first_of_agent": ag["n"] == 0, "report": ""}
        ag["n"] += 1
        ag["open"] = s
        segs.append(s)

    def touch(ag: dict | None, idx: int) -> None:
        s = ag["open"] if ag else None
        if s:
            s["first"] = tf[idx] if s["first"] is None else s["first"]
            s["last"] = tf[idx]

    for idx, e in enumerate(events):
        ty, parent, sub = e.get("type"), e.get("parent_tool_use_id"), e.get("subtype")
        if ty == "system" and sub == "task_started" and e.get("task_type") == "local_agent":
            aid, cid = e.get("task_id"), e.get("tool_use_id")
            ag = agents.get(aid)
            if ag is None and cid in agent_of_call and agents[agent_of_call[cid]]["pseudo"]:
                ag = agents.pop(agent_of_call[cid])      # sub events arrived first: adopt that agent
                ag.update(id=aid, pseudo=False)
                agents[aid] = ag
                agent_of_call[cid] = aid
                if ag["open"]:
                    ag["open"]["agent"] = aid
            if ag is None:
                ag = new_agent(aid, cid)
                inp = calls.get(cid, {}).get("inp") or {}
                prompt = inp.get("prompt") or e.get("prompt") or ""
                prime = bool(_PRIME_RE.search(prompt))
                kind = "prime" if prime else _call_kind(
                    inp or {"description": e.get("description"), "subagent_type": e.get("subagent_type")})
                ag["tasks"] = 0 if prime or kind != "build" else 1
                name_of_agent[aid] = inp.get("name") or ""
                open_seg(ag, idx, kind, (inp.get("description") or e.get("description") or "") + " "
                         + prompt[:200], cid)
            elif ag["open"] is None:
                m = msgs.get(cid)
                open_seg(ag, idx, "fix" if m and m["fix"] else "build",
                         (m["summary"] + " " + m["message"]) if m else "", cid)
            continue
        if ty == "system" and sub == "task_notification":
            ag = agents.get(e.get("task_id"))
            if ag and ag["open"]:
                s = ag["open"]
                s["end"] = s["last"] if s["last"] is not None else tf[idx]
                s["report"] = _text_of((e.get("handback_report") or {}).get("text"))
                # A fresh agent's first report is READY, not DONE: that segment was the prime.
                if (s["first_of_agent"] and s["kind"] == "build" and len(s["report"]) < 800
                        and re.search(r"\bREADY\b", s["report"]) and not re.search(r"\bDONE", s["report"])):
                    s["kind"], s["key"] = "prime", None
                    if ag["tasks"] == 1:
                        ag["tasks"] = 0
                ag["open"] = None
                notifs.append((idx, s))
            continue
        if ty == "user":
            c = (e.get("message") or {}).get("content")
            for b in c if isinstance(c, list) else []:
                if b.get("type") == "tool_result" and b.get("tool_use_id") in watch:
                    results[b["tool_use_id"]] = _text_of(b.get("content"))
            if parent:
                touch(agents.get(agent_of_call.get(parent, "")), idx)
            continue
        if ty != "assistant":
            continue
        msg = e.get("message") or {}
        mid = msg.get("id")
        if parent:
            if parent not in agent_of_call:      # no task_started seen: one segment per dispatch
                inp = calls.get(parent, {}).get("inp") or {}
                open_seg(new_agent(parent, parent, pseudo=True), idx, _call_kind(inp) if inp else "other",
                         inp.get("description") or "", parent)
            ag = agents[agent_of_call[parent]]
            touch(ag, idx)
            if isinstance(msg.get("usage"), dict) and mid and mid not in usage:
                ag["ctx"] = _ctx(msg["usage"])
        else:
            top_assist.append(idx)
        if isinstance(msg.get("usage"), dict) and mid:
            rec = usage.setdefault(mid, {"parent": parent, "model": msg.get("model") or "", "u": dict(msg["usage"])})
            rec["u"]["output_tokens"] = max(rec["u"].get("output_tokens") or 0, msg["usage"].get("output_tokens") or 0)
        for b in msg.get("content") or []:
            if b.get("type") == "text" and parent and _VERDICT_RE.search(b.get("text") or ""):
                ag = agents.get(agent_of_call.get(parent, ""))
                if ag and ag["open"] and "verdict" not in ag["open"]:
                    ag["open"]["verdict"] = tf[idx]
            if b.get("type") != "tool_use" or b.get("id") in seen_tu:
                continue
            seen_tu.add(b["id"])
            inp, name = b.get("input") or {}, b.get("name")
            if name in ("Bash", "PowerShell"):
                cmd = str(inp.get("command") or "")
                unsafe += bool(UNSAFE_KILL.search(cmd))
                graphify += bool(re.search(r"\bgraphify\b", cmd, re.I))
                if re.search(r"incident\.py\s+add", cmd):
                    k = re.search(r"--kind[ =]+['\"]?([\w-]+)", cmd)
                    kind = k.group(1) if k else "unspecified"
                    incidents[kind] = incidents.get(kind, 0) + 1
                if _SEAM_RE.search(cmd):
                    watch[b["id"]] = "seam"
                    seam_ids.append(b["id"])
                elif re.search(r"build_prime\.py", cmd):
                    watch[b["id"]] = "prime"
                elif re.search(r"plan_tools\.py\s+schedule", cmd):
                    watch[b["id"]] = "schedule"
            elif name == "Write" and re.search(r"plan.*\.md$", str(inp.get("file_path", "")).replace("\\", "/"), re.I):
                plan_writes.append(str(inp.get("content") or ""))
            elif not parent and name in ("Agent", "Task"):
                calls[b["id"]] = {"idx": idx, "t": tf[idx], "inp": inp}
            elif not parent and name == "SendMessage":
                message, summary = _text_of(inp.get("message")), str(inp.get("summary") or "")
                to = str(inp.get("to") or "")
                text = summary + " " + message
                rec = {"id": b["id"], "summary": summary, "message": message,
                       "fix": bool(_FIX_RE.search(summary + " " + message[:120]))}
                msgs[b["id"]] = rec
                if _POLL_RE.search(text):
                    polls.setdefault(mid or b["id"], {"t": tf[idx], "ids": []})["ids"].append(b["id"])
                    continue
                aid = to if to in agents else next((a for a, n in name_of_agent.items() if n and n == to), None)
                if aid is None:
                    continue
                ag = agents[aid]
                busy = ag["open"] is not None
                queued = busy or bool(_QUEUE_RE.search(text))
                assigns.append({
                    "to": aid, "t": round(tf[idx], 1), "kind": "fix" if rec["fix"] else "task",
                    "busy": busy, "queued": queued, "reuse_idle": not queued and ag["tasks"] >= 1,
                    # Past 3 tasks, or an agent already beyond 80k context, is outside the reuse limits.
                    "limit_breach": ag["tasks"] >= 1 and (ag["tasks"] >= 3 or ag["ctx"] > 80000)})
                ag["tasks"] += 1

    for ag in agents.values():                   # segments still open when the log ends
        s = ag["open"]
        if s:
            s["end"] = s["last"] if s["last"] is not None else (tf[-1] if tf else 0.0)
    for s in segs:
        s["start"] = s["first"] if s["first"] is not None else s["start"]
        s["end"] = max(s["start"], s["end"] if s["end"] is not None else s["start"])
        s["dur"] = s["end"] - s["start"]

    # Schedule shape: gaps with no agent running, the backward critical chain, the build tail.
    live = sorted((s for s in segs if s["dur"] > 0), key=lambda s: s["start"])
    idle_gaps = 0.0
    crit = None
    if live:
        reach = live[0]["end"]
        for s in live[1:]:
            idle_gaps += max(0.0, s["start"] - reach)
            reach = max(reach, s["end"])
        c = max(live, key=lambda s: s["end"])
        crit = c["dur"]
        while True:
            prev = [s for s in live if s is not c and s["end"] <= c["start"] + 1.0]
            if not prev:
                break
            c = max(prev, key=lambda s: s["end"])
            crit += c["dur"]
    builds = [s for s in segs if s["kind"] == "build" and s["dur"] > 0]
    last_build_end = max((s["end"] for s in builds), default=None)

    # Final review (dispatch to verdict) and the fixes after the verdict.
    finals = sorted((s for s in segs if s["kind"] == "final_review" and s["call"] in calls),
                    key=lambda s: s["start"])
    final_review_s = final_fix_s = None
    if finals:
        final = finals[0]
        verdict = final.get("verdict", final["end"])
        final_review_s = round(verdict - calls[final["call"]]["t"], 1)
        fix_ends = [s["end"] for s in segs if s["kind"] == "fix" and s["start"] >= verdict - 1.0]
        final_fix_s = round(max(0.0, max([final["end"]] + fix_ends) - verdict), 1)

    # Predicted against actual.
    est, pred_total, pred_cp = _plan_numbers(
        plan_writes[-1] if plan_writes else "", "\n".join(results.get(i, "") for i in watch))
    errs, seen_key = [], set()
    for s in builds:
        if s["key"] in est and s["key"] not in seen_key:
            seen_key.add(s["key"])
            errs.append(abs(s["dur"] - est[s["key"]]) / est[s["key"]])

    # Reviews: count, batching and estimated cost.
    reviews = [s for s in segs if s["kind"] in ("review", "final_review") and s["call"] in calls]
    plain = [s for s in reviews if s["kind"] == "review"]
    task_count = len({s["key"] for s in builds if s["key"]}) + sum(1 for s in builds if not s["key"])
    review_calls = {s["call"] for s in reviews}
    cost = 0.0
    for rec in usage.values():
        price = next((p for k, p in PRICES.items() if k in rec["model"]), None)
        if rec["parent"] in review_calls and price:
            u = rec["u"]
            cc = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else {}
            w1 = cc.get("ephemeral_1h_input_tokens") or 0
            w5 = (u.get("cache_creation_input_tokens") or 0) - w1
            cost += ((u.get("input_tokens") or 0) * price[0] + (u.get("output_tokens") or 0) * price[1]
                     + w5 * price[2] + w1 * price[3] + (u.get("cache_read_input_tokens") or 0) * price[4]) / 1e6

    # Relevance polls: a round is one coordinator message; its latency runs to the last answer.
    poll_s = None
    if polls:
        poll_s = 0.0
        for p in polls.values():
            ends = [s["end"] for s in segs if s["call"] in p["ids"]]
            poll_s += max(0.0, max(ends) - p["t"]) if ends else 0.0

    # Seam checks and prime hashes: None while the source events don't exist.
    seam_bad = sum(1 for i in seam_ids if "MISMATCH" in results.get(i, ""))
    prime_expected = next((m.group(1) for i, k in watch.items() if k == "prime"
                           for m in [re.search(r"\b([0-9a-f]{12,64})\b", results.get(i, ""))] if m), None)
    hashes = {}
    for cid, c in calls.items():
        if _call_kind(c["inp"]) == "build":
            m = _PRIME_HASH_RE.search(str(c["inp"].get("prompt") or ""))
            hashes[cid] = m.group(1) if m else None
    prime_bad = None
    if prime_expected or any(hashes.values()):
        found = [h for h in hashes.values() if h]
        prime_expected = prime_expected or max(set(found), key=found.count)
        prime_bad = sum(1 for h in hashes.values() if h != prime_expected)

    # Report lag: the agent's last event until the coordinator's next output.
    lags = []
    for nidx, s in notifs:
        nxt = next((i for i in top_assist if i > nidx), None)
        if nxt is not None:
            lags.append(max(0.0, tf[nxt] - s["end"]))

    def r1(x):
        return round(x, 1) if x is not None else None

    return {
        "queued_assignments": sum(a["queued"] for a in assigns),
        "agent_reuse_idle": sum(a["reuse_idle"] for a in assigns),
        "relevance_polls": len(polls),
        "relevance_poll_s": r1(poll_s),
        "reuse_limit_breaches": sum(a["limit_breach"] for a in assigns),
        "idle_gaps_s": r1(idle_gaps) if live else None,
        "critical_path_s": r1(crit),
        "critical_path_actual": r1(crit),
        "critical_path_predicted": r1(pred_cp),
        "tail_after_build_s": r1(last_t - last_build_end) if None not in (last_build_end, last_t) else None,
        "last_build_end_s": r1(last_build_end),
        "incidents": {"count": sum(incidents.values()), "by_kind": incidents},
        "graphify_used": bool(graphify),
        "final_review_s": final_review_s,
        "final_fix_s": final_fix_s,
        "longest_task_s": r1(max((s["dur"] for s in builds), default=None)),
        "est_time_error": round(statistics.mean(errs), 3) if errs else None,
        "predicted_total_s": r1(pred_total),
        "actual_total_s": r1(last_t),
        "seam_checks": len(seam_ids) or None,
        "seam_mismatches": seam_bad if seam_ids else None,
        "reviews_per_task": round(len(plain) / task_count, 2) if task_count else None,
        "reviews_batched": sum(1 for s in plain if _BATCH_RE.search(calls[s["call"]]["inp"].get("description") or "")),
        "review_cost_usd": round(cost, 3),
        "prime_hash_mismatches": prime_bad,
        "coordinator_turns": coordinator_turns,
        "coordinator_report_lag_s": r1(statistics.mean(lags)) if lags else None,
        "coordinator_report_lag_max_s": r1(max(lags)) if lags else None,
        "unsafe_kill_commands": unsafe,
        "assignments": assigns,
    }


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
             (d["subagent_type"].endswith("implementer") or _IMPL_DESC_RE.match((d["description"] or "").lower()))]
    finals = [d for d in dispatches if d["start_s"] is not None and kind(d, "review") and kind(d, "final")
              and not kind(d, "fix") and not kind(d, "re-review")]
    final = min(finals, key=lambda d: d["start_s"]) if finals else None
    last_t = max((t - t0 for t in stamps), default=None)
    flow = flow_metrics(events, t0, last_t, len(coord))
    timeline = {
        "plan_write_s": round(plan_write, 1) if plan_write is not None else None,
        "first_implementer_s": min(d["start_s"] for d in impls) if impls else None,
        "last_implementer_end_s": max(d["end_s"] for d in impls) if impls else None,
        # Build tasks only: a resumed agent's span also covers its idle time and fix rounds.
        "last_build_end_s": flow["last_build_end_s"],
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
        **flow,
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
        # The stream's last event excludes decider time spent between resumes; arm_wall_s is the real clock.
        **({"actual_total_s": meta["arm_wall_s"]} if "arm_wall_s" in meta else {}),
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
    brief = {k: v for k, v in score.items() if k not in ("model_usage", "hidden_failed_ids", "dispatches", "assignments")}
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
