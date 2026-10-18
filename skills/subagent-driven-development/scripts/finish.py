#!/usr/bin/env python3
"""Print the closing summary of a run.

    finish.py [--ledger .superlite/progress.md] [--log .superlite/incidents.jsonl]

Collects, from the progress ledger, every `Ruling:` line (in order), the
commits and the last test counts, plus the open incidents from the log.
Deterministic: the same files give the same text. Stdlib only.
"""
import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_LEDGER = ".superlite/progress.md"
DEFAULT_LOG = ".superlite/incidents.jsonl"

RULING = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*)?Ruling:(?:\*\*)?\s*(.*?)\s*$")
COMMIT = re.compile(r"^\s*[-*+]?\s*commit\s+(T\d+[A-Za-z]?)\s+([0-9a-f]{7,40})\s*(.*?)\s*$")
TESTS = re.compile(r"^\s*[-*+]?\s*tests\s+(\w+)\s+passed=(\d+)\s+failed=(\d+)"
                   r"\s+skipped=(\d+)\s+seconds=([\d.]+)")


def read_ledger(path):
    p = Path(path)
    if not p.exists():
        return [], [], None
    rulings, commits, tests = [], [], None
    for line in p.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n"):
        m = RULING.match(line)
        if m:
            rulings.append(m.group(1))
            continue
        m = COMMIT.match(line)
        if m:
            commits.append(m.groups())
            continue
        m = TESTS.match(line)
        if m:
            tests = m.groups()
    return rulings, commits, tests


def open_incidents(path):
    p = Path(path)
    out = []
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if (isinstance(e, dict) and "file" in e and e.get("kind") != "verified"
                and e.get("resolution") in (None, "open", "unresolved")):
            out.append(e)
    return out


def summary(ledger, log):
    rulings, commits, tests = read_ledger(ledger)
    incidents = open_incidents(log)
    out = ["# superlite run summary", ""]
    out.append(f"commits: {len(commits)}")
    out += [f"- {t} {sha[:10]} {title}".rstrip() for t, sha, title in commits]
    out.append("")
    out.append(f"rulings: {len(rulings)}")
    out += [f"- {r}" for r in rulings]
    out.append("")
    if tests:
        mode, p, f, s, sec = tests
        out.append(f"tests ({mode}): {p} passed, {f} failed, {s} skipped in {sec}s")
    else:
        out.append("tests: none recorded")
    out.append("")
    out.append(f"open incidents: {len(incidents)}")
    for e in incidents:
        kind = e.get("kind") or "unknown"
        out.append(f"- {e['file']}:{e['line']} [{kind}] {e.get('context', '')}")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)
    ap.add_argument("--log", default=DEFAULT_LOG)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(summary(a.ledger, a.log))
    return 0


if __name__ == "__main__":
    sys.exit(main())
