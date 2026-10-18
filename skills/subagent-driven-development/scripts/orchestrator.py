#!/usr/bin/env python3
"""Who orchestrates: a human (approves the plan before it runs) or an AI (does everything itself).

    orchestrator.py set human|ai [--by NAME] [--ruling TEXT]
    orchestrator.py approve [--by NAME]
    orchestrator.py status [--plan P]

State: `.superlite/orchestrator.json` {mode, approved, by, time}. In human mode `plan_tools lint --stable`, `dispatch`,
`wave0` and `build_prime` refuse to run (exit 4, one line) until `approve` has been recorded; `schedule --insert` and
`prune` stay allowed so the plan can be shown whole with its Gantt. In AI mode nothing is gated. With no file nothing is
gated (existing runs behave as before). `--ruling` on `set ai` also appends a `Ruling:` line to `.superlite/progress.md`
(for a headless run where no human can answer). Library: gate(plan_or_dir, tool) -> message or None,
require(plan_or_dir, tool) -> exit code (prints the message), read_state, summary_line. Stdlib only.
"""
# Complexity notation:
#   everything here is O(1) file work
import argparse  # O(1)
import json  # O(1)
import sys  # O(1)
from datetime import datetime  # O(1)
from pathlib import Path  # O(1)

FILE = "orchestrator.json"  # O(1)
EXIT_BLOCKED = 4  # exit 3 already means "no Python" for sl | O(1)
BLOCK = ("BLOCKED: human orchestrator selected, show the plan, ask for approval, then run sl orchestrator approve")  # O(1)


def sl_dir(plan_or_dir=None) -> Path:  # O(1)
    """The `.superlite` folder: the argument itself when it is one, else next to a plan (the plan's repo root), else ./.superlite."""
    if plan_or_dir is None:  # O(1)
        return Path(".superlite")  # O(1)
    p = Path(plan_or_dir).resolve()  # O(1)
    if p.name == ".superlite":  # O(1)
        return p  # O(1)
    if p.is_dir():  # O(1)
        return p / ".superlite" if p.name != ".superlite" else p  # O(1)
    root = p.parent  # O(1)
    if root.name == ".superlite":  # O(1)
        return root  # O(1)
    if root.name == "plans" and root.parent.name == "docs":  # O(1)
        return root.parent.parent / ".superlite"  # O(1)
    return root / ".superlite"  # O(1)


def read_state(plan_or_dir=None):  # O(file)
    f = sl_dir(plan_or_dir) / FILE  # O(1)
    try:  # O(1)
        d = json.loads(f.read_text(encoding="utf-8"))  # O(file)
    except (OSError, ValueError):  # O(1)
        return None  # O(1)
    return d if isinstance(d, dict) and d.get("mode") in ("human", "ai") else None  # O(1)


def write_state(plan_or_dir, state: dict) -> None:  # O(1)
    d = sl_dir(plan_or_dir)  # O(1)
    d.mkdir(parents=True, exist_ok=True)  # O(1)
    (d / FILE).write_text(json.dumps(state, indent=1) + chr(10), encoding="utf-8")  # O(1)


def gate(plan_or_dir=None, tool: str = "") -> str | None:  # O(file)
    """None when the tool may run, else the one-line reason. Only human mode without an approval blocks."""
    st = read_state(plan_or_dir)  # O(file)
    if st and st["mode"] == "human" and not st.get("approved"):  # O(1)
        return BLOCK  # O(1)
    return None  # O(1)


def require(plan_or_dir=None, tool: str = "") -> int:  # O(file)
    """0 to go on; prints the reason to stderr and returns EXIT_BLOCKED when the gate is shut."""
    msg = gate(plan_or_dir, tool)  # O(file)
    if msg:  # O(1)
        print(msg, file=sys.stderr)  # O(1)
        return EXIT_BLOCKED  # O(1)
    return 0  # O(1)


def summary_line(plan_or_dir=None) -> str:  # O(file)
    st = read_state(plan_or_dir)  # O(file)
    if not st:  # O(1)
        return "orchestrator: not set (ungated)"  # O(1)
    if st["mode"] == "ai":  # O(1)
        return f"orchestrator: AI (set {st.get('time', '?')} by {st.get('by', '?')})"  # O(1)
    if st.get("approved"):  # O(1)
        return f"orchestrator: human, approved {st.get('approved_time') or st.get('time')} by {st.get('approved_by') or st.get('by')}"  # O(1)
    return f"orchestrator: human, awaiting approval (set {st.get('time', '?')})"  # O(1)


def now() -> str:  # O(1)
    return datetime.now().isoformat(timespec="seconds")  # O(1)


def main(argv=None):  # O(1)
    ap = argparse.ArgumentParser(description=__doc__.split(chr(10))[0])  # O(1)
    sub = ap.add_subparsers(dest="cmd", required=True)  # O(1)
    s = sub.add_parser("set")  # O(1)
    s.add_argument("mode", choices=["human", "ai"])  # O(1)
    s.add_argument("--by", default="user")  # O(1)
    s.add_argument("--ruling", help="with ai: also record a Ruling: line in .superlite/progress.md")  # O(1)
    a_ = sub.add_parser("approve")  # O(1)
    a_.add_argument("--by", default="human")  # O(1)
    st = sub.add_parser("status")  # O(1)
    for p in (s, a_, st):  # O(1)
        p.add_argument("--plan", help="plan path (locates .superlite); default ./.superlite")  # O(1)
    a = ap.parse_args(argv)  # O(1)
    if a.cmd == "set":  # O(1)
        write_state(a.plan, {"mode": a.mode, "approved": a.mode == "ai", "by": a.by, "time": now()})  # O(1)
        if a.mode == "ai" and a.ruling:  # O(1)
            f = sl_dir(a.plan) / "progress.md"  # O(1)
            with f.open("a", encoding="utf-8") as fh:  # O(1)
                fh.write(f"Ruling: {a.ruling}" + chr(10))  # O(1)
        print(summary_line(a.plan))  # O(1)
        return 0  # O(1)
    cur = read_state(a.plan)  # O(file)
    if a.cmd == "approve":  # O(1)
        if not cur or cur["mode"] != "human":  # O(1)
            print("orchestrator: approve applies to human mode only; run: sl orchestrator set human", file=sys.stderr)  # O(1)
            return 2  # O(1)
        cur.update(approved=True, approved_by=a.by, approved_time=now())  # O(1)
        write_state(a.plan, cur)  # O(1)
    print(summary_line(a.plan))  # O(1)
    return 0  # O(1)


if __name__ == "__main__":  # O(1)
    sys.exit(main())  # O(1)
