#!/usr/bin/env python3
"""Commit one task: stage only its Owns files, block anything else.

    commit_task.py Tn [--plan P] [--ledger .superlite/progress.md]
                      [--log .superlite/incidents.jsonl] [--allow-other-tasks]

Steps: scope check (changes outside Owns block the commit and are logged as
incidents), py_compile plus an import check on each touched .py file, commit
with the task title, append the SHA to the progress ledger, then launch in the
background `sl probe_run --commit SHA` and, for every seam of the task graph
(`sl plan_tools taskgraph --format full`) that involves this task and whose both
sides are now committed per the ledger, `sl pt_review contract --plan P --seam
Ta,Tb --log LOG` (mismatches become incidents, a pass logs `verified`). Prints the
SHA, or exits 1 listing the problem files. Run it from the repository root.

Scope rules: `tests/regression/` (where probe_run writes `test_probe_*.py`) is owned
by whichever task is committing, so the task or review that fixes a defect commits
the regression test it caused. `.superlite/` is never staged and never blocks; add it
to the repo's `.git/info/exclude` at setup (`setup_exclude()` here does it, and
commit_task also does it on every run). Stdlib only.
"""
import argparse
import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import next_tasks as nt  # noqa: E402

DEFAULT_LEDGER = ".superlite/progress.md"
DEFAULT_LOG = ".superlite/incidents.jsonl"
IGNORED_PARTS = (".superlite/", "__pycache__/")  # never staged, never blocking
SHARED_OWNS = ("tests/regression/",)  # generated probe regression tests: owned by the committer
COMMIT_LINE = re.compile(r"^\s*[-*+]?\s*commit\s+(T\d+[A-Za-z]?)\s+[0-9a-f]{7,40}")
TASK_ID = re.compile(r"T\d+[A-Za-z]?")

IMPORT_DRIVER = r"""
import importlib, importlib.util, json, os, sys, traceback
sys.dont_write_bytecode = True
root = os.path.abspath(sys.argv[1])
files = sys.argv[2:]
sys.path.insert(0, root)
if os.path.isdir(os.path.join(root, "src")):
    sys.path.insert(1, os.path.join(root, "src"))
failures = []
for rel in files:
    path = os.path.join(root, rel)
    parts = rel.replace("\\", "/")[:-3].split("/")
    if parts[0] == "src" and os.path.isdir(os.path.join(root, "src")):
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    try:
        if parts and all(p.isidentifier() for p in parts):
            importlib.import_module(".".join(parts))
        else:
            name = "_slcheck_" + "_".join(p.replace("-", "_") for p in parts)
            sys.path.append(os.path.dirname(path))
            spec = importlib.util.spec_from_file_location(name, path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
    except BaseException as e:
        line = 0
        for fr in traceback.extract_tb(e.__traceback__):
            if os.path.abspath(fr.filename) == os.path.abspath(path):
                line = fr.lineno
        failures.append({"file": rel, "line": line,
                         "error": f"{type(e).__name__}: {e}"[:150]})
print(json.dumps(failures))
"""


def git(*args, check=True):
    r = subprocess.run(["git", *args], capture_output=True, text=True,
                       encoding="utf-8")
    if check and r.returncode != 0:
        nt.die(f"git {' '.join(args[:2])} failed: {(r.stderr or r.stdout).strip()}", 1)
    return r


def ignored(path):
    p = "/" + path
    return any(f"/{part}" in p for part in IGNORED_PARTS) or path.endswith(".pyc")


def changed_files():
    r = git("status", "--porcelain", "-z", "--untracked-files=all", "--no-renames")
    files = []
    for entry in r.stdout.split("\0"):
        if len(entry) > 3:
            path = entry[3:].replace("\\", "/")
            if not ignored(path):
                files.append(path)
    return sorted(set(files))


def log_incident(log, file, line, context):
    nt.add_incident(log, file, line, context, "exception", "commit_task", "open")


def syntax_errors(files):
    errors = []
    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            try:
                py_compile.compile(f, cfile=os.path.join(tmp, "x.pyc"), doraise=True)
            except py_compile.PyCompileError as e:
                exc = e.exc_value
                line = getattr(exc, "lineno", 0) or 0
                msg = getattr(exc, "msg", None) or str(e)
                errors.append((f, line, f"SyntaxError: {msg}"))
    return errors


def import_errors(files):
    if not files:
        return []
    r = subprocess.run([sys.executable, "-I", "-c", IMPORT_DRIVER, ".", *files],
                       capture_output=True, text=True, encoding="utf-8", timeout=120,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return [(files[0], 0, f"import check crashed: {r.stderr.strip()[-150:]}")]
    return [(f["file"], f["line"], f["error"]) for f in out]


def is_module(path):
    name = Path(path).name
    return (path.endswith(".py") and not name.startswith("test_")
            and not name.endswith("_test.py") and name != "conftest.py")


def append_ledger(ledger, line):
    p = Path(ledger)
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists() or p.stat().st_size == 0
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write("# Progress ledger\n\n")
        f.write(line + "\n")


def setup_exclude():
    """Add `.superlite/` to the repo's .git/info/exclude (idempotent); True if it did."""
    r = git("rev-parse", "--git-path", "info/exclude", check=False)
    if r.returncode != 0 or not r.stdout.strip():
        return False
    p = Path(r.stdout.strip())
    try:
        old = p.read_text(encoding="utf-8") if p.exists() else ""
        if any(ln.strip() in (".superlite", ".superlite/") for ln in old.splitlines()):
            return False
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8", newline="\n") as f:
            f.write(("" if not old or old.endswith("\n") else "\n") + ".superlite/\n")
    except OSError:
        return False
    return True


def spawn_background(cmd):
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, **kw)


def launch_probes(sha):
    probe = Path(os.environ.get("SUPERLITE_PROBE_RUN")
                 or nt.SCRIPTS.parent / "probes" / "probe_run.py")
    if not probe.exists():
        return False
    spawn_background(nt.sl_command("probe_run", "--commit", sha))
    return True


def committed_tasks(ledger):
    p = Path(ledger)
    if not p.exists():
        return set()
    out = set()
    for ln in p.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n"):
        m = COMMIT_LINE.match(ln)
        if m:
            out.add(m.group(1))
    return out


def seams(plan):
    """[(producer, consumer)] from `sl plan_tools taskgraph --format full`; [] on failure."""
    r = nt.run_tool("plan_tools", "taskgraph", "--plan", plan, "--format", "full")
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        print(f"warning: no seams (taskgraph failed): {(r.stderr or r.stdout).strip()[:150]}",
              file=sys.stderr)
        return []
    pairs = []
    for s in data.get("seams") or []:
        ids = TASK_ID.findall(s)
        if len(ids) == 2:
            pairs.append((ids[0], ids[1]))
    if not pairs:  # seams missing from the output: derive them from the graph edges
        for t, deps in (data.get("graph") or {}).items():
            pairs += [(d, t) for d in deps]
    return pairs


def launch_seam_checks(plan, task, ledger, log):
    """Background `pt_review contract --seam` for each seam of `task` now fully committed.

    Seams that do not involve `task` were launched when their own later side committed."""
    done = committed_tasks(ledger) | {task}
    launched = []
    for a_, b_ in seams(plan):
        if task in (a_, b_) and a_ in done and b_ in done:
            spawn_background(nt.sl_command("pt_review", "contract", "--plan", plan,
                                           "--seam", f"{a_},{b_}", "--log", log))
            launched.append(f"{a_},{b_}")
    return launched


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("task")
    ap.add_argument("--plan", default=nt.DEFAULT_PLAN)
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)
    ap.add_argument("--log", default=DEFAULT_LOG)
    ap.add_argument("--allow-other-tasks", action="store_true",
                    help="ignore (do not stage) files owned by other plan tasks")
    a = ap.parse_args(argv)

    info = nt.parse_plan(a.plan)
    if a.task not in info:
        nt.die(f"unknown task {a.task}")
    task = info[a.task]
    owns = task["owns"]
    if not owns:
        nt.die(f"{a.task} has no Owns line")
    owns = owns + [o for o in SHARED_OWNS if o not in owns]
    other = [o for t, i in info.items() if t != a.task for o in i["owns"]
             if o not in SHARED_OWNS]
    setup_exclude()

    own_files = set()  # bookkeeping files of the run itself, never in scope
    for p in (a.plan, a.ledger, a.log):
        try:
            own_files.add(Path(p).resolve().relative_to(Path.cwd().resolve()).as_posix())
        except ValueError:
            pass

    mine, out_of_scope = [], []
    for f in changed_files():
        if f in own_files and not nt.owns_match(f, owns):
            continue
        if nt.owns_match(f, owns):
            mine.append(f)
        elif a.allow_other_tasks and nt.owns_match(f, other):
            continue
        else:
            out_of_scope.append(f)

    if out_of_scope:
        for f in out_of_scope:
            print(f"out-of-scope {f}")
            log_incident(a.log, f, 0, f"{a.task}: change outside Owns blocked by "
                         f"commit_task; nothing committed")
        return 1
    if not mine:
        print(f"nothing to commit for {a.task}", file=sys.stderr)
        return 1

    present = [f for f in mine if os.path.exists(f)]
    py = [f for f in present if f.endswith(".py")]
    problems = syntax_errors(py)
    if not problems:
        problems = import_errors([f for f in py if is_module(f)])
    if problems:
        for f, line, msg in problems:
            print(f"{'syntax' if msg.startswith('SyntaxError') else 'import'} "
                  f"{f}:{line} {msg}")
            log_incident(a.log, f, line, f"{a.task}: {msg}; nothing committed")
        return 1

    git("add", "-A", "--", *mine)
    title = f"{a.task}: {task['title']}"
    r = git("commit", "-m", title, check=False)
    if r.returncode != 0:
        print((r.stderr or r.stdout).strip(), file=sys.stderr)
        return 1
    sha = git("rev-parse", "HEAD").stdout.strip()
    append_ledger(a.ledger, f"- commit {a.task} {sha[:10]} {task['title']}")
    launch_probes(sha)
    launch_seam_checks(a.plan, a.task, a.ledger, a.log)
    print(sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
