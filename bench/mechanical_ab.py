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
import taskmetrics as mechanical  # noqa: E402

ROOT = harness.ROOT
AGENTS = {"haiku": "superlite:implementer-haiku", "sonnet": "superlite:implementer"}
WEIGHT = {"haiku": 1.0, "sonnet": 4.0}


def weight_of(model: str) -> float:
    """Share of the cost cap an arm's run gets: the legacy weights, else Sonnet's 4 scaled by output price."""
    if model in WEIGHT:
        return WEIGHT[model]
    cfg = json.loads((harness.MODELS_JSON).read_text(encoding="utf-8"))["models"]
    return round(4.0 * cfg[model]["output"] / cfg["sonnet"]["output"], 2)


def agent_names() -> list[str]:
    return sorted(p.stem for p in (ROOT / "agents").glob("*.md"))


def parse_arms(spec: str | None, models: list[str], primes: list[str]) -> list[tuple[str, str, str]]:
    """Arms as (agent, model, prime). `agent:model[:prime],...` names any agent file in agents/ (implementers, fixers,
    reviewers) and any model with an entry in models.json; without --arms the legacy models x primes grid is used
    (haiku -> implementer-haiku, sonnet -> implementer)."""
    known = set(harness.PRICES)
    arms = []
    if spec:
        for part in spec.split(","):
            bits = part.strip().split(":")
            if len(bits) not in (2, 3):
                raise ValueError(f"arm {part!r}: use agent:model[:prime]")
            agent, model, prime = bits[0].split("/")[-1], bits[1], (bits[2] if len(bits) == 3 else "full")
            if agent not in agent_names():
                raise ValueError(f"arm {part!r}: no agents/{agent}.md (have: {', '.join(agent_names())})")
            if model not in known:
                raise ValueError(f"arm {part!r}: model {model!r} has no entry in models.json (have: {', '.join(sorted(known))})")
            if prime not in ("full", "mini"):
                raise ValueError(f"arm {part!r}: prime must be full or mini")
            arms.append((agent, model, prime))
    else:
        for m in models:
            if m not in AGENTS:
                raise ValueError(f"model {m!r} has no default agent; use --arms agent:model")
            arms += [(AGENTS[m].split(":")[1], m, pr) for pr in primes]
    return arms
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


def pick_tasks(plan, names: list[str] | None, select: str | None = None) -> tuple[list, str]:
    if names:
        return [plan.by_id[n] for n in names], "named with --tasks (not marked mechanical in the plan unless it says so)"
    if select:
        pred = mechanical.parse_select(select)
        rules = mechanical.load_rules(harness.ROUTING_JSON)
        out = []
        for t in plan.by_id.values():
            f = t.explicit_features
            kind = f.get("kind", "design")
            rec = {"task": t.id, "kind": kind, "tier_planned": mechanical.planned_tier(t, "", rules, kind)[0],
                   "model": f.get("model"), "agent_type": None}
            if pred(rec):
                out.append(t)
        return out, f"selected by --select {select!r}"
    mech = [t for t in plan.by_id.values() if t.explicit_features.get("kind") == "mechanical"]
    return mech, "marked `Kind: mechanical` in the plan"


def owned_tests(task) -> list[str]:
    return [p for p in task.owns if re.search(r"(^|/)(tests?|__tests__)/|(^|/)test_|\.test\.|_test\.", p)]


def brief_for(task, root: Path, template: str | None = None) -> str:
    if template:  # a fixer or reviewer arm needs its own brief: {task_id} {title} {owns} {root}
        return Path(template).read_text(encoding="utf-8").format(task_id=task.id, title=task.title, owns=", ".join(task.owns), root=root)
    return (f"You are a superlite implementer. Project root: {root}. Read `.superlite/prime.md` (the shared plan and spec) "
            f"and `.superlite/brief.md` (common rules) in full now, if they exist. This message is both your priming and "
            f"your task, so do not reply READY: do the task now.\n\n"
            f"Task {task.id} {task.title} (plan block {task.id}). Wave 0 is committed. Owns: {', '.join(task.owns)}; "
            f"touch nothing else. Keep the data types in your stub files as they are; replace the NotImplementedError "
            f"stubs and add helpers in files you own. Review Focus cases are listed in the {task.id} block. Follow "
            f".superlite/brief.md (verify command, 200-word reply format). Do not commit.")


def section(text: str, head_re: str, level: str = "##") -> str:
    """The `head_re` heading's block up to the next heading of the same or a higher level."""
    m = re.search(rf"^{level} +{head_re}.*$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(rf"^#{{1,{len(level)}}} ", rest, re.M)
    return m.group(0) + (rest[:nxt.start()] if nxt else rest)


def mini_prime(plan, task, dest: Path) -> str:
    """3-5k tokens for a Haiku agent: the plan's goal/constraints, this task's block, the stub files it owns and the
    SPEC sections it cites (`A§n` / `B§n`, Part A / Part B headings) instead of the whole plan."""
    text = plan.to_text()
    parts = ["# superlite mini prime (this task only)", chr(10).join(text.splitlines()[:8]), section(text, "Global constraints")]
    parts.append(f"## Your task block{chr(10)}{chr(10)}{task.text.strip()}")
    for p in task.owned_sources:
        f = dest / p
        if f.is_file():
            parts.append(f"## Stub: {p}{chr(10)}```{chr(10)}{f.read_text(encoding='utf-8')}{chr(10)}```")
    spec = dest / "SPEC.md"
    if spec.is_file():
        st = spec.read_text(encoding="utf-8")
        for part, n in dict.fromkeys(re.findall(r"([AB])§(\d+)", task.text)):
            body = section(st, f"Part {part}:", "#")
            sec = section(body, rf"{n}\.", "##")
            if sec:
                parts.append(f"## SPEC Part {part} section {n}\n\n{sec.strip()}")
    return (chr(10) * 2).join(x for x in parts if x.strip()) + chr(10)


def default_verify(root: Path) -> tuple[str, str]:
    if (root / "package.json").is_file():
        return "npx vitest run {tests}", "npm install --no-audit --no-fund"
    return "uv run --no-project --with pytest python -m pytest {tests} -q -p no:cacheprovider", ""


# ---- one run -------------------------------------------------------------------------------------
def prepare(run_dir: Path, commit: str, dest: Path, setup: str, mini: tuple | None = None) -> None:
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(run_dir), str(dest)], check=True, capture_output=True)
    subprocess.run(["git", "checkout", "--quiet", commit], cwd=dest, check=True, capture_output=True)
    sl = run_dir / ".superlite"
    for name in ("prime.md", "brief.md"):
        if (sl / name).is_file():
            (dest / ".superlite").mkdir(exist_ok=True)
            shutil.copy2(sl / name, dest / ".superlite" / name)
    if mini:  # (plan, task): replace the full prime with the task's mini prime
        (dest / ".superlite").mkdir(exist_ok=True)
        (dest / ".superlite" / "prime.md").write_text(mini_prime(*mini, dest), encoding="utf-8")
    if setup:
        subprocess.run(setup, cwd=dest, shell=True, capture_output=True, env=harness.with_node(harness.clean_env()), timeout=600)


def agent_def(model: str, agent: str | None = None) -> dict:
    """The plugin's agent file as a `--agents` entry. The plugin itself is not loaded: its
    block-coordinator-edits hook rejects every edit made by a top-level session, and here the agent is the top level."""
    text = (ROOT / "agents" / f"{agent or AGENTS[model].split(':')[1]}.md").read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    meta = dict(re.findall(r"^(\w+):\s*(.+)$", front, re.M))
    return {"description": meta.get("description", "implementer"), "prompt": body.strip(),
            "model": model, "tools": [t.strip() for t in meta.get("tools", "").split(",") if t.strip()]}


def claude_cmd(model: str, prompt: str, budget: float, agent: str | None = None) -> list[str]:
    name = agent or AGENTS[model].split(":")[1]
    meta = agent_def(model, name)
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
    agent = job.get("agent") or AGENTS[model].split(":")[1]
    tag = f"{task.id}-{agent}-{model}-{job['prime']}-{k}"
    log = job["out"] / f"{tag}.jsonl"
    rec = {"task": task.id, "agent": agent, "model": model, "prime": job["prime"], "arm": f"{agent}:{model}:{job['prime']}", "rep": k, "budget_usd": round(budget, 3)}
    try:
        prepare(job["run_dir"], job["commit"], dest, job["setup"], (job["plan"], task) if job["prime"] == "mini" else None)
        rec["prime_tokens_est"] = len((dest / ".superlite" / "prime.md").read_text(encoding="utf-8")) // 4 if (dest / ".superlite" / "prime.md").is_file() else 0
        cmd = claude_cmd(model, brief_for(task, dest, job.get("template")), budget, agent)
        job["gate"]()  # last look at `ps` right before the launch
        t0 = time.time()
        with log.open("w", encoding="utf-8") as lf, (job["out"] / f"{tag}.stderr").open("w") as ef:
            proc = subprocess.Popen(cmd, cwd=dest, stdout=lf, stderr=ef, stdin=subprocess.DEVNULL, env=harness.arm_env(),
                                    creationflags=0 if os.name != "nt" else subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
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
        stamps = [mechanical._ts(e) for e in events if mechanical._ts(e) is not None]
        first_tool = next((mechanical._ts(e) for e in events if e.get("type") == "assistant" and mechanical._ts(e) is not None and any(
            b.get("type") == "tool_use" for b in (e.get("message") or {}).get("content") or [])), None)
        rec["first_tool_s"] = round(first_tool - min(stamps), 1) if first_tool is not None and stamps else None  # launch -> first tool call
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
        dflt = lambda r: r.get("agent") or AGENTS.get(r["model"], ":" + r["model"]).split(":")[1]  # noqa: E731
        for agent, model, prime in sorted({(dflt(r), r["model"], r.get("prime", "full")) for r in runs if r["task"] == tid},
                                          key=lambda x: (x[1] != "haiku", x[1], x[0], x[2])):
            rs = [r for r in runs if r["task"] == tid and r["model"] == model and r.get("prime", "full") == prime and dflt(r) == agent]
            med = lambda f: round(statistics.median([x for x in map(f, rs) if x is not None]), 2) if any(f(x) is not None for x in rs) else None  # noqa: E731
            rows.append({"task": tid, "agent": agent, "model": model, "prime": prime, "arm": f"{agent}:{model}:{prime}", "runs": len(rs),
                         "median_prime_tokens": med(lambda r: r.get("prime_tokens_est")),
                         "median_first_tool_s": med(lambda r: r.get("first_tool_s")), "passed": sum(r["passed"] for r in rs),
                         "pass_rate": round(sum(r["passed"] for r in rs) / len(rs), 2),
                         "median_s": med(lambda r: r.get("duration_s")), "median_cost_usd": med(lambda r: r.get("cost_usd")),
                         "median_tool_calls": med(lambda r: r.get("tool_calls")),
                         "median_out_tokens": med(lambda r: (r.get("tokens") or {}).get("out")),
                         "median_ctx_tokens": med(lambda r: sum((r.get("tokens") or {}).get(k, 0) for k in ("in", "cache_read", "cache_write")) or None),
                         "failures": [f"#{r['rep']}: {r['fail_reason']}" for r in rs if not r["passed"]]})
    return rows


def render(rows: list[dict], total_cost: float, cap: float) -> str:
    cols = ["task", "agent", "model", "prime", "pass", "1st tool s", "prime tok", "median s", "median $", "tools", "out tok", "ctx tok", "failures"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        lines.append("| " + " | ".join(str(x) for x in (
            r["task"], r.get("agent", "-"), r["model"], r["prime"], f"{r['passed']}/{r['runs']}", r["median_first_tool_s"], r["median_prime_tokens"], r["median_s"], r["median_cost_usd"], r["median_tool_calls"],
            r["median_out_tokens"], r["median_ctx_tokens"], "; ".join(r["failures"]) or "-")) + " |")
    lines.append(f"\nTotal spend ${total_cost:.2f} (cap ${cap:.2f}). Medians over the runs of each cell; 'ctx tok' = input + cache read + cache write.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--tasks", help="comma-separated task ids (default: plan tasks marked Kind: mechanical)")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--models", default="haiku,sonnet", help="legacy grid: comma-separated models (haiku -> implementer-haiku, sonnet -> implementer)")
    ap.add_argument("--arms", help="agent:model[:prime],... any agents/*.md and any model in models.json; overrides --models/--prime")
    ap.add_argument("--select", help="task selector: kind=mechanical (default), tier=haiku, model=opus, ids=T1,T4, all; join with ;")
    ap.add_argument("--prompt-template", help="brief file for non-implementer arms ({task_id} {title} {owns} {root})")
    ap.add_argument("--prime", default="full", help="full (the run's .superlite/prime.md), mini (task-only prime) or full,mini (both arms)")
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
    tasks, why = pick_tasks(plan, a.tasks.split(",") if a.tasks else None, a.select)
    if not tasks:
        sys.exit("the plan marks no task `Kind: mechanical`; pass --tasks T..,T.. with tasks a human would mark mechanical "
                 "(fully specified, small, fast tests) and say why in the report")
    commit = stub_commit(run_dir, a.commit)
    default_v, default_s = default_verify(run_dir)
    verify, setup = a.verify or default_v, a.setup if a.setup is not None else default_s
    hidden = a.hidden or (harness.TASK_HIDDEN if harness.TASK_HIDDEN.is_dir() else None)
    out = a.out or harness.RESULTS / f"mechanical-ab-{run_dir.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    models, primes = a.models.split(","), a.prime.split(",")
    try:
        arms = parse_arms(a.arms, models, primes)
    except ValueError as exc:
        sys.exit(str(exc))
    combos = [(t, ag, m, pr, k) for t in tasks for ag, m, pr in arms for k in range(1, a.n + 1)]
    unit = a.cost_cap / sum(weight_of(m) for _, _, m, _, _ in combos)
    plan_txt = {"run_dir": str(run_dir), "commit": commit, "tasks": [t.id for t in tasks], "selected_because": why, "n": a.n, "models": sorted({m for _, m, _ in arms}), "primes": sorted({p for _, _, p in arms}),
                "arms": [f"{ag}:{m}:{pr}" for ag, m, pr in arms],
                "cost_cap_usd": a.cost_cap, "timeout_s": a.timeout, "verify": verify, "hidden": str(hidden), "setup": setup,
                "per_run_cap_usd": {f"{ag}:{m}:{pr}": round(unit * weight_of(m), 3) for ag, m, pr in arms}, "out": str(out)}
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
    jobs = [{"task": t, "agent": ag, "model": m, "k": k, "prime": pr, "plan": plan, "template": a.prompt_template,
             "dest": work / f"{t.id}-{ag}-{m}-{pr}-{k}", "budget": unit * weight_of(m), "out": out,
             "run_dir": run_dir, "commit": commit, "verify": verify, "hidden": hidden, "setup": setup,
             "timeout": a.timeout, "gate": gate} for t, ag, m, pr, k in combos]
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
