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
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
# Outside the repo, so an arm can't wander up into hidden_tests/ or reference/.
RUNS = Path(os.environ.get("BENCH_RUNS", ROOT.parent / "superlite-bench-runs"))
RESULTS = BENCH / "results"
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


def invoke(cmd: list[str], cwd: Path, log: Path, err: Path) -> None:
    with log.open("a", encoding="utf-8") as out, err.open("a", encoding="utf-8") as er:
        subprocess.run(cmd, cwd=cwd, stdout=out, stderr=er, stdin=subprocess.DEVNULL)


def cmd_run(arm: str, rep: str, smoke: bool) -> None:
    claude = shutil.which("claude") or "claude"
    name = f"{arm}-{rep}" + ("-smoke" if smoke else "")
    run_dir = RUNS / name
    RESULTS.mkdir(parents=True, exist_ok=True)
    log, err = RESULTS / f"{name}.jsonl", RESULTS / f"{name}.stderr"
    if run_dir.exists():
        sys.exit(f"run dir exists: {run_dir}")
    run_dir.mkdir(parents=True)
    shutil.copy(BENCH / "task" / "SPEC.md", run_dir / "SPEC.md")
    git(run_dir, "init", "-q", "-b", "main")
    git(run_dir, "add", "SPEC.md")
    git(run_dir, "-c", "user.name=bench", "-c", "user.email=bench@local", "commit", "-qm", "Add SPEC.md")

    budget = os.environ.get("BENCH_BUDGET", "1" if smoke else "60")
    base = [claude, "-p"]
    extra = common_args(budget) + ARM_ARGS[arm]
    prompt = SMOKE_PROMPT if smoke else (BENCH / "prompt.md").read_text(encoding="utf-8")

    t0 = time.time()
    invoke(base + [prompt] + extra, run_dir, log, err)
    resumes = 0
    while not smoke and resumes < MAX_RESUMES:
        res = results_of(read_events(log))
        if not res or MARKER in (res[-1].get("result") or ""):
            break
        sid = res[-1].get("session_id")
        if not sid:
            break
        resumes += 1
        invoke(base + [RESUME_PROMPT, "--resume", sid] + extra, run_dir, log, err)
    wall = time.time() - t0
    meta = {"arm": arm, "rep": rep, "smoke": smoke, "wall_s": round(wall, 1), "resumes": resumes}
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


def hidden_score(run_dir: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "w"
        shutil.copytree(run_dir, work, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"))
        shutil.copytree(BENCH / "hidden_tests", work / "hidden_tests")
        junit = Path(tmp) / "junit.xml"
        env = dict(os.environ, PYTHONPATH=str(work / "src"))
        subprocess.run(
            ["uv", "run", "--no-project", "--with", "pytest", "python", "-m", "pytest",
             "hidden_tests", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"],
            cwd=work, env=env, capture_output=True, timeout=600,
        )
        if not junit.exists():
            return {"hidden_passed": 0, "hidden_total": None, "hidden_failed_ids": ["(no junit)"]}
        total, failed = 0, []
        for case in ET.parse(junit).getroot().iter("testcase"):
            total += 1
            if any(child.tag in ("failure", "error", "skipped") for child in case):
                failed.append(f"{case.get('classname')}::{case.get('name')}")
        return {"hidden_passed": total - len(failed), "hidden_total": total, "hidden_failed_ids": failed}


def own_tests(run_dir: Path) -> dict:
    proc = subprocess.run(
        ["uv", "run", "--no-project", "--with", "pytest", "python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "--ignore=hidden_tests"],
        cwd=run_dir, env=dict(os.environ, PYTHONPATH=str(run_dir / "src")), capture_output=True, text=True, timeout=600,
    )
    tail = proc.stdout.strip().splitlines()[-1:] or [""]
    return {"own_tests_summary": tail[0]}


def cmd_score(arm: str, rep: str) -> dict:
    name = f"{arm}-{rep}"
    run_dir = RUNS / name
    events = read_events(RESULTS / f"{name}.jsonl")
    res = results_of(events)
    meta = json.loads((RESULTS / f"{name}.meta.json").read_text(encoding="utf-8"))
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
        "turns": sum(r.get("num_turns") or 0 for r in res),
        "api_s": round(sum(r.get("duration_api_ms") or 0 for r in res) / 1000, 1),
        "completed_marker": bool(res) and MARKER in (res[-1].get("result") or ""),
        "last_subtype": res[-1].get("subtype") if res else None,
        **stream_stats(events),
        "model_usage": model_usage,
        "src_loc": src_loc,
        "commits": int(commits or 0),
        **own_tests(run_dir),
        **hidden_score(run_dir),
    }
    (RESULTS / f"{name}.json").write_text(json.dumps(score, indent=2), encoding="utf-8")
    brief = {k: v for k, v in score.items() if k not in ("model_usage", "hidden_failed_ids")}
    print(json.dumps(brief, indent=2))
    return score


def cmd_report() -> None:
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RESULTS.glob("*-[0-9].json"))]
    cols = ["arm", "rep", "wall_s", "cost_usd", "turns", "resumes", "agent_dispatches",
            "coordinator_tool_calls", "hidden_passed", "hidden_total", "own_tests_summary", "src_loc", "commits"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    print("\n".join(lines))


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if args[0] == "run":
        cmd_run(args[1], args[2], "--smoke" in args)
    elif args[0] == "score":
        cmd_score(args[1], args[2])
    elif args[0] == "report":
        cmd_report()
    else:
        sys.exit(__doc__)
