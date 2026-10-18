"""Isolated A/B replay of `Kind: mechanical` tasks: the same task brief, N times on implementer-haiku and
N times on the Sonnet implementer, each in a fresh git copy of the committed stub state.

    python bench/mechanical_ab.py RUN_DIR [--tasks T8,T5] [--n 3] [--cost-cap 2.0] [--timeout 300]
                                          [--commit REF] [--hidden DIR] [--verify CMD] [--setup CMD]
                                          [--out DIR] [--dry-run] [--wait]

RUN_DIR is a git repo with `docs/plans/*.md` and a committed Wave 0 / stub state (default commit: the
newest whose subject starts with "Wave 0", else HEAD); `.superlite/prime.md` and `brief.md` are copied
in if present. Tasks default to those the plan marks `Kind: mechanical`; --tasks names others (say why
in the report). Each run is `claude -p --agent <implementer>` headless with the clean-env
recipe of harness.py, a per-run cost cap (the total --cost-cap split by weight: Sonnet 4, Haiku 1) and a
hard timeout; only that run's process tree is killed, by PID. No run starts while a `harness.py run`
process is active (checked right before launching; --wait polls, otherwise exit code 3).

Scoring per run: the verify command (default from the project: pytest / vitest, `{tests}` = the task's
owned test files) and the hidden tests whose file names match the owned modules (or a hidden suite's
own run.sh). A run passes when both are green and it edited only files it owns."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
import mechanical  # noqa: E402

ROOT = harness.ROOT
AGENTS = {"haiku": "superlite:implementer-haiku", "sonnet": "superlite:implementer"}
WEIGHT = {"haiku": 1.0, "sonnet": 4.0}
PYTEST = ["uv", "run", "--no-project", "--with", "pytest", "python", "-m", "pytest"]  # hidden-suite runner
STATUS = re.compile(r"\bStatus:\s*\**\s*(DONE_WITH_CONCERNS|DONE|NEEDS_CONTEXT|BLOCKED)\b", re.I)


# ---- environment guards --------------------------------------------------------------------------
def active_harness_runs() -> list[str]:
    """Command lines of live `harness.py run` processes (so a timing-sensitive benchmark is left alone)."""
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-Command",
               "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'harness\\.py\\s+run' } "
               "| ForEach-Object { $_.CommandLine }"]
    else:
        cmd = ["sh", "-c", "ps -eo args | grep -E 'harness\\.py +run' | grep -v grep"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def kill_tree(pid: int) -> None:
    """Kill one process tree by PID (never by image name)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(pid, 9)
        except OSError:
            pass


# ---- task selection and brief --------------------------------------------------------------------
def stub_commit(run_dir: Path, ref: str | None) -> str:
    if ref:
        return ref
    log = subprocess.run(["git", "log", "--format=%H %s"], cwd=run_dir, capture_output=True, text=True).stdout.splitlines()
    for ln in log:
        if re.match(r"\w+ Wave 0", ln):
            return ln.split()[0]
    return "HEAD"


def pick_tasks(plan, names: list[str] | None) -> tuple[list, str]:
    if names:
        return [plan.by_id[n] for n in names], "named with --tasks (not marked mechanical in the plan unless it says so)"
    mech = [t for t in plan.by_id.values() if t.explicit_features.get("kind") == "mechanical"]
    return mech, "marked `Kind: mechanical` in the plan"


def owned_tests(task) -> list[str]:
    return [p for p in task.owns if re.search(r"(^|/)(tests?|__tests__)/|(^|/)test_|\.test\.|_test\.", p)]


def brief_for(task, root: Path) -> str:
    return (f"You are a superlite implementer. Project root: {root}. Read `.superlite/prime.md` (the shared plan and spec) "
            f"and `.superlite/brief.md` (common rules) in full now, if they exist. This message is both your priming and "
            f"your task, so do not reply READY: do the task now.\n\n"
            f"Task {task.id} {task.title} (plan block {task.id}). Wave 0 is committed. Owns: {', '.join(task.owns)}; "
            f"touch nothing else. Keep the data types in your stub files as they are; replace the NotImplementedError "
            f"stubs and add helpers in files you own. Review Focus cases are listed in the {task.id} block. Follow "
            f".superlite/brief.md (verify command, 200-word reply format). Do not commit.")


def default_verify(root: Path) -> tuple[str, str]:
    if (root / "package.json").is_file():
        return "npx vitest run {tests}", "npm install --no-audit --no-fund"
    return "uv run --no-project --with pytest python -m pytest {tests} -q -p no:cacheprovider", ""


# ---- one run -------------------------------------------------------------------------------------
def prepare(run_dir: Path, commit: str, dest: Path, setup: str) -> None:
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(run_dir), str(dest)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "--quiet", commit], cwd=dest, check=True, capture_output=True)
    sl = run_dir / ".superlite"
    for name in ("prime.md", "brief.md"):
        if (sl / name).is_file():
            (dest / ".superlite").mkdir(exist_ok=True)
            shutil.copy2(sl / name, dest / ".superlite" / name)
    if setup:
        subprocess.run(setup, cwd=dest, shell=True, capture_output=True, env=harness.with_node(harness.clean_env()), timeout=600)


def agent_def(model: str) -> dict:
    """The plugin's agent file as a `--agents` entry. The plugin itself is not loaded: its
    block-coordinator-edits hook rejects every edit made by a top-level session, and here the agent is the top level."""
    text = (ROOT / "agents" / f"{AGENTS[model].split(':')[1]}.md").read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    meta = dict(re.findall(r"^(\w+):\s*(.+)$", front, re.M))
    return {"description": meta.get("description", "implementer"), "prompt": body.strip(),
            "model": meta.get("model", model), "tools": [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]}


def claude_cmd(model: str, prompt: str, budget: float) -> list[str]:
    name = AGENTS[model].split(":")[1]
    meta = agent_def(model)
    effort = re.search(r"^effort:\s*(\w+)", (ROOT / "agents" / f"{name}.md").read_text(encoding="utf-8"), re.M)
    settings = {"enabledPlugins": {"superpowers@claude-plugins-official": False}}
    return [shutil.which("claude") or "claude", "-p", prompt, "--agents", json.dumps({name: meta}), "--agent", name,
            *(["--effort", effort.group(1)] if effort else []), "--settings", json.dumps(settings),
            "--permission-mode", "auto", "--output-format", "stream-json", "--verbose", "--max-budget-usd", f"{budget:.2f}"]


def score(dest: Path, task, verify: str, hidden: Path | None) -> dict:
    env = harness.with_node(dict(os.environ, PYTHONPATH=os.pathsep.join([str(dest / "src"), str(dest)])))
    tests = owned_tests(task)
    out: dict = {}
    if verify and tests:
        p = subprocess.run(verify.format(tests=" ".join(tests)), cwd=dest, shell=True, env=env, capture_output=True, text=True, timeout=300)
        tail = [ln for ln in (p.stdout + p.stderr).strip().splitlines() if ln.strip()][-1:] or [""]
        out.update(own_ok=p.returncode == 0, own_tail=tail[0][:160])
    else:
        out.update(own_ok=None, own_tail="no owned test files or verify command")
    out.update(hidden_total=None, hidden_passed=None, hidden_failed=[])
    if hidden and hidden.is_dir():
        with tempfile.TemporaryDirectory() as tmp:
            junit = Path(tmp) / "j.xml"
            hd = dest / "hidden_tests"
            shutil.copytree(hidden, hd, ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
            if (hidden / "run.sh").is_file():
                subprocess.run([harness.bash_exe(), "hidden_tests/run.sh"], cwd=dest, capture_output=True, timeout=600,
                               env=dict(env, JUNIT=str(junit), HIDDEN_DIR="hidden_tests"))
            else:
                stems = {Path(p).stem for p in task.owned_sources}
                files = [str(f.relative_to(dest)) for f in hd.rglob("*")
                         if f.is_file() and any(f.name in (f"test_{s}.py", f"{s}.test.ts", f"{s}_test.py") for s in stems)]
                if files:
                    subprocess.run([*PYTEST, *files, "-q", "-p", "no:cacheprovider", f"--junitxml={junit}"], cwd=dest, env=env, capture_output=True, timeout=300)
            if junit.is_file() and junit.stat().st_size:
                total, failed, _ = harness.junit_counts(junit)
                out.update(hidden_total=total, hidden_passed=total - len(failed), hidden_failed=failed[:5])
            shutil.rmtree(hd, ignore_errors=True)
    changed = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=dest, capture_output=True, text=True).stdout.splitlines()
    owned = {p.replace("\\", "/") for p in task.owns}
    out["out_of_scope"] = [ln[3:] for ln in changed if ln[3:].replace("\\", "/") not in owned
                           and not ln[3:].startswith((".superlite", "hidden_tests", ".pytest_cache", "node_modules", "__pycache__"))
                           and "__pycache__" not in ln][:8]
    return out


def execute(job: dict) -> dict:
    task, model, k, dest, budget = job["task"], job["model"], job["k"], job["dest"], job["budget"]
    log = job["out"] / f"{task.id}-{model}-{k}.jsonl"
    rec = {"task": task.id, "model": model, "rep": k, "budget_usd": round(budget, 3)}
    try:
        prepare(job["run_dir"], job["commit"], dest, job["setup"])
        cmd = claude_cmd(model, brief_for(task, dest), budget)
        job["gate"]()  # last look at `ps` right before the launch
        t0 = time.time()
        with log.open("w", encoding="utf-8") as lf, (job["out"] / f"{task.id}-{model}-{k}.stderr").open("w") as ef:
            proc = subprocess.Popen(cmd, cwd=dest, stdout=lf, stderr=ef, stdin=subprocess.DEVNULL, env=harness.arm_env(),
                                    creationflags=0 if os.name != "nt" else subprocess.CREATE_NEW_PROCESS_GROUP,
                                    start_new_session=os.name != "nt")
            rec["pid"] = proc.pid
            try:
                proc.wait(timeout=job["timeout"])
                rec["timed_out"] = False
            except subprocess.TimeoutExpired:
                rec["timed_out"] = True
                kill_tree(proc.pid)
                proc.wait()
        rec["duration_s"] = round(time.time() - t0, 1)
        events = harness.read_events(log)
        res = [e for e in events if e.get("type") == "result"]
        r = res[-1] if res else {}
        mu = r.get("modelUsage") or {}
        tok = {"in": sum(u.get("inputTokens", 0) for u in mu.values()), "out": sum(u.get("outputTokens", 0) for u in mu.values()),
               "cache_read": sum(u.get("cacheReadInputTokens", 0) for u in mu.values()),
               "cache_write": sum(u.get("cacheCreationInputTokens", 0) for u in mu.values())}
        calls = {b.get("id") for e in events if e.get("type") == "assistant"
                 for b in (e.get("message") or {}).get("content") or [] if b.get("type") == "tool_use"}
        text = r.get("result") or ""
        sm = STATUS.search(text)
        rec.update(tokens=tok, cost_usd=round(r.get("total_cost_usd") or sum(
            e.get("total_cost_usd") or 0 for e in res), 4), tool_calls=len(calls), turns=r.get("num_turns"),
            subtype=r.get("subtype"), status=sm.group(1).upper() if sm else None, reply=re.sub(r"\s+", " ", text)[:240],
            models=sorted(mu))
        rec.update(score(dest, task, job["verify"], job["hidden"]))
    except Exception as exc:  # noqa: BLE001 - a broken run is a data point, not a crash of the batch
        rec["error"] = f"{type(exc).__name__}: {exc}"[:240]
    rec["passed"] = bool(rec.get("own_ok") and not rec.get("timed_out") and not rec.get("out_of_scope")
                         and (rec.get("hidden_total") is None or rec.get("hidden_passed") == rec.get("hidden_total")))
    rec["fail_reason"] = None if rec["passed"] else fail_reason(rec)
    return rec


def fail_reason(r: dict) -> str:
    if r.get("error"):
        return "error: " + r["error"]
    if r.get("timed_out"):
        return "timeout"
    if r.get("subtype") and r["subtype"] != "success":
        return f"claude stopped: {r['subtype']}"
    if r.get("status") in ("NEEDS_CONTEXT", "BLOCKED"):
        return f"{r['status']}: {r.get('reply', '')[:120]}"
    if r.get("own_ok") is False:
        return "own tests red: " + r.get("own_tail", "")
    if r.get("hidden_total") and r["hidden_passed"] != r["hidden_total"]:
        return f"hidden {r['hidden_passed']}/{r['hidden_total']}: " + ", ".join(r["hidden_failed"][:3])
    if r.get("out_of_scope"):
        return "edited files it does not own: " + ", ".join(r["out_of_scope"][:3])
    return "unknown (no result event)"


# ---- aggregation and output ----------------------------------------------------------------------
def aggregate(runs: list[dict]) -> list[dict]:
    rows = []
    for tid in sorted({r["task"] for r in runs}, key=lambda t: int(re.sub(r"\D", "", t) or 0)):
        for model in ("haiku", "sonnet"):
            rs = [r for r in runs if r["task"] == tid and r["model"] == model]
            if not rs:
                continue
            med = lambda f: round(statistics.median([x for x in map(f, rs) if x is not None]), 2) if any(f(x) is not None for x in rs) else None  # noqa: E731
            rows.append({"task": tid, "model": model, "runs": len(rs), "passed": sum(r["passed"] for r in rs),
                         "pass_rate": round(sum(r["passed"] for r in rs) / len(rs), 2),
                         "median_s": med(lambda r: r.get("duration_s")), "median_cost_usd": med(lambda r: r.get("cost_usd")),
                         "median_tool_calls": med(lambda r: r.get("tool_calls")),
                         "median_out_tokens": med(lambda r: (r.get("tokens") or {}).get("out")),
                         "median_ctx_tokens": med(lambda r: sum((r.get("tokens") or {}).get(k, 0) for k in ("in", "cache_read", "cache_write")) or None),
                         "failures": [f"#{r['rep']}: {r['fail_reason']}" for r in rs if not r["passed"]]})
    return rows


def render(rows: list[dict], total_cost: float, cap: float) -> str:
    cols = ["task", "model", "pass", "median s", "median $", "tools", "out tok", "ctx tok", "failures"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join(str(x) for x in (
            r["task"], r["model"], f"{r['passed']}/{r['runs']}", r["median_s"], r["median_cost_usd"], r["median_tool_calls"],
            r["median_out_tokens"], r["median_ctx_tokens"], "; ".join(r["failures"]) or "-")) + " |")
    lines.append(f"\nTotal spend ${total_cost:.2f} (cap ${cap:.2f}). Medians over the runs of each cell; 'ctx tok' = input + cache read + cache write.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--tasks", help="comma-separated task ids (default: plan tasks marked Kind: mechanical)")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--cost-cap", type=float, default=2.0)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--commit")
    ap.add_argument("--hidden", type=Path, help="hidden test suite dir (default: bench/tasks/<TASK>/hidden or bench/hidden_tests)")
    ap.add_argument("--verify", help="verify command; {tests} = the task's owned test files")
    ap.add_argument("--setup", help="command run once in each copy (e.g. npm install)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wait", action="store_true", help="poll until no harness.py run is active instead of exiting 3")
    a = ap.parse_args(argv)

    run_dir = a.run_dir.resolve()
    plan = harness._run_plan(run_dir)
    if plan is None:
        sys.exit(f"no plan in {run_dir / 'docs' / 'plans'}")
    tasks, why = pick_tasks(plan, a.tasks.split(",") if a.tasks else None)
    if not tasks:
        sys.exit("the plan marks no task `Kind: mechanical`; pass --tasks T..,T.. with tasks a human would mark mechanical "
                 "(fully specified, small, fast tests) and say why in the report")
    commit = stub_commit(run_dir, a.commit)
    default_v, default_s = default_verify(run_dir)
    verify, setup = a.verify or default_v, a.setup if a.setup is not None else default_s
    hidden = a.hidden or (harness.TASK_HIDDEN if harness.TASK_HIDDEN.is_dir() else None)
    out = a.out or harness.RESULTS / f"mechanical-ab-{run_dir.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    combos = [(t, m, k) for t in tasks for m in ("haiku", "sonnet") for k in range(1, a.n + 1)]
    unit = a.cost_cap / sum(WEIGHT[m] for _, m, _ in combos)
    plan_txt = {"run_dir": str(run_dir), "commit": commit, "tasks": [t.id for t in tasks], "selected_because": why, "n": a.n,
                "cost_cap_usd": a.cost_cap, "timeout_s": a.timeout, "verify": verify, "hidden": str(hidden), "setup": setup,
                "per_run_cap_usd": {m: round(unit * w, 3) for m, w in WEIGHT.items()}, "out": str(out)}
    if a.dry_run:
        print(json.dumps(plan_txt, indent=2))
        return 0

    def gate() -> None:
        while (live := active_harness_runs()):
            if not a.wait:
                print("waiting: a harness.py run is active; no live run started:\n  " + "\n  ".join(live), file=sys.stderr)
                os._exit(3)
            time.sleep(30)

    gate()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="mech-ab-"))
    jobs = [{"task": t, "model": m, "k": k, "dest": work / f"{t.id}-{m}-{k}", "budget": unit * WEIGHT[m], "out": out,
             "run_dir": run_dir, "commit": commit, "verify": verify, "hidden": hidden, "setup": setup,
             "timeout": a.timeout, "gate": gate} for t, m, k in combos]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        runs = list(ex.map(execute, jobs))
    total = sum(r.get("cost_usd") or 0 for r in runs)
    rows = aggregate(runs)
    doc = {"config": plan_txt, "wall_s": round(time.time() - t0, 1), "total_cost_usd": round(total, 4), "table": rows, "runs": runs}
    (out / "results.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(render(rows, total, a.cost_cap))
    print(f"\ndata: {out / 'results.json'}")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
