#!/usr/bin/env python3
"""Print the ready tasks, longest predicted Est. time first, within the cap.

    next_tasks.py --plan P --committed T1,T3 --running T2 [--cap 10]

Also hosts the small plan-parsing helpers the other run scripts import
(plan sections, Owns expansion, task graph via plan_tools). Stdlib only.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
DEFAULT_PLAN = ".superlite/plan.md"
DEFAULT_TIME = 1.0

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_TASK_HEADING = re.compile(r"^###\s+(T\d+[A-Za-z]?)\b(.*)$")


def die(msg, code=2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def sl_command(tool, *args):
    """Command line that runs another superlite tool through the `sl` launcher (D18).

    SUPERLITE_SL replaces the launcher (tests); SUPERLITE_BASH picks the bash."""
    launcher = os.environ.get("SUPERLITE_SL") or str(SCRIPTS / "sl")
    return [os.environ.get("SUPERLITE_BASH") or "bash", launcher, tool,
            *map(str, args)]


def run_tool(tool, *args):
    return subprocess.run(sl_command(tool, *args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def taskgraph(plan):
    """Task -> dependencies, from `plan_tools taskgraph` (through sl)."""
    r = run_tool("plan_tools", "taskgraph", "--plan", plan)
    if r.returncode != 0:
        die(f"taskgraph failed: {(r.stderr or r.stdout).strip()}", r.returncode)
    try:
        graph = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        die(f"taskgraph printed invalid JSON: {e}")
    return {k: list(v) for k, v in graph.items()}


def add_incident(log, file, line, context, kind, agent, resolution=None):
    """Log one incident through `sl incident add`; failures only warn."""
    cmd = ["add", "--file", file, "--line", line, "--context", context,
           "--agent", agent, "--kind", kind, "--log", log]
    if resolution:
        cmd += ["--resolution", resolution]
    r = run_tool("incident", *cmd)
    if r.returncode != 0:
        print(f"warning: incident not logged: {(r.stderr or r.stdout).strip()}",
              file=sys.stderr)


def read_text(path):
    p = Path(path)
    if not p.exists():
        die(f"file not found: {path}")
    return p.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")


def parse_plan(plan):
    """{task id: info}, in plan order.

    info: title, est_time (min), est_context (k tokens), owns (list), body.
    """
    lines = read_text(plan).split("\n")
    tasks, cur = {}, None
    for line in lines:
        m = _TASK_HEADING.match(line)
        if m:
            cur = {"id": m.group(1), "head": m.group(2), "body": []}
            tasks[cur["id"]] = cur
            continue
        if _HEADING.match(line) and len(_HEADING.match(line).group(1)) <= 3:
            cur = None
            continue
        if cur is not None:
            cur["body"].append(line)
    out = {}
    for tid, t in tasks.items():
        body = "\n".join(t["body"])
        head = t["head"]
        parts = [p.strip() for p in head.split("·")]
        if parts and parts[0] == "":
            parts = parts[1:]
        title = re.sub(r"\s+", " ", parts[0]) if parts else ""
        out[tid] = {
            "id": tid,
            "title": title or tid,
            "est_time": _num(r"Est\.?\s*time:?\*{0,2}\s*([\d.]+)\s*min", head, body),
            "est_context": _num(r"Est\.?\s*context:?\*{0,2}\s*([\d.]+)\s*k", head, body),
            "owns": parse_owns(_field(body, "Owns")),
            "body": body,
        }
    return out


def _num(pattern, head, body):
    for text in (head, body):
        m = re.search(pattern, text, re.I)
        if m:
            return float(m.group(1))
    return None


def _field(body, name):
    m = re.search(rf"^\*\*{name}:\*\*[ \t]*(.*)$", body, re.M)
    return m.group(1) if m else ""


def split_top(text, sep=","):
    """Split on `sep` outside braces, parentheses and backtick spans."""
    parts, depth, tick, cur = [], 0, False, []
    for ch in text:
        if ch == "`":
            tick = not tick
        elif not tick and ch in "{(":
            depth += 1
        elif not tick and ch in "})":
            depth -= 1
        if ch == sep and depth == 0 and not tick:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def brace_expand(s):
    m = re.search(r"\{([^{}]*)\}", s)
    if not m:
        return [s]
    out = []
    for alt in m.group(1).split(","):
        out.extend(brace_expand(s[:m.start()] + alt.strip() + s[m.end():]))
    return out


def parse_owns(text):
    """Owned paths from an `**Owns:**` line. A trailing `/` means a directory."""
    text = re.sub(r"\([^()]*\)", "", text)  # parenthetical notes and children
    paths = []
    for part in split_top(text):
        part = part.replace("`", "").strip().rstrip(".;").strip()
        if not part:
            continue
        for p in brace_expand(part):
            p = p.strip().replace("\\", "/")
            if p:
                paths.append(p)
    return paths


def owns_match(path, owns):
    path = path.replace("\\", "/")
    for o in owns:
        if o.endswith("/"):
            if path.startswith(o):
                return True
        elif path == o or path.startswith(o + "/"):
            return True
    return False


def csv(value):
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def ready_tasks(graph, times, committed, running, cap):
    free = cap - len(running)
    if free <= 0:
        return []
    done, busy = set(committed), set(running)
    ready = [t for t, deps in graph.items()
             if t not in done and t not in busy and all(d in done for d in deps)]
    order = {t: i for i, t in enumerate(graph)}
    ready.sort(key=lambda t: (-times.get(t, DEFAULT_TIME), order[t]))
    return ready[:free]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plan", default=DEFAULT_PLAN)
    ap.add_argument("--committed", default="")
    ap.add_argument("--running", default="")
    ap.add_argument("--cap", type=int, default=10)
    a = ap.parse_args(argv)
    graph = taskgraph(a.plan)
    info = parse_plan(a.plan)
    times = {t: (info[t]["est_time"] if t in info and info[t]["est_time"] is not None
                 else DEFAULT_TIME) for t in graph}
    for t in ready_tasks(graph, times, csv(a.committed), csv(a.running), a.cap):
        print(t)
    return 0


if __name__ == "__main__":
    sys.exit(main())
