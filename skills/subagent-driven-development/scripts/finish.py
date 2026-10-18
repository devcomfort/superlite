#!/usr/bin/env python3
"""Print the closing summary of a run.

    finish.py [--ledger .superlite/progress.md] [--log .superlite/incidents.jsonl]

Collects, from the progress ledger, every `Ruling:` line (in order), the
commits and the last test counts, plus the open incidents from the log.
Deterministic: the same files give the same text. Stdlib only.
"""
# Complexity notation:
#   R = lines in the progress ledger, I = lines in the incident log, C = commits and G = rulings found,
#   w = width of one line
import argparse  # O(1)
import json  # O(1)
import re  # O(1)
import sys  # O(1)
from pathlib import Path  # O(1)

DEFAULT_LEDGER = ".superlite/progress.md"  # O(1)
DEFAULT_LOG = ".superlite/incidents.jsonl"  # O(1)

RULING = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*)?Ruling:(?:\*\*)?\s*(.*?)\s*$")  # O(1)
COMMIT = re.compile(r"^\s*[-*+]?\s*commit\s+(T\d+[A-Za-z]?)\s+([0-9a-f]{7,40})\s*(.*?)\s*$")  # O(1)
TESTS = re.compile(r"^\s*[-*+]?\s*tests\s+(\w+)\s+passed=(\d+)\s+failed=(\d+)"  # O(1)
                   r"\s+skipped=(\d+)\s+seconds=([\d.]+)")  # O(1)


def read_ledger(path):  # O(R*w)
    p = Path(path)  # O(1)
    if not p.exists():  # O(1) stat
        return [], [], None  # O(1)
    rulings, commits, tests = [], [], None  # O(1)
    for line in p.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n"):  # O(R) iterations; read + split O(ledger bytes)
        m = RULING.match(line)  # O(w) regex
        if m:  # O(1)
            rulings.append(m.group(1))  # O(1)
            continue  # O(1)
        m = COMMIT.match(line)  # O(w) regex
        if m:  # O(1)
            commits.append(m.groups())  # O(1)
            continue  # O(1)
        m = TESTS.match(line)  # O(w) regex
        if m:  # O(1)
            tests = m.groups()  # O(1)
    return rulings, commits, tests  # O(1)


def open_incidents(path):  # O(I*w)
    p = Path(path)  # O(1)
    out = []  # O(1)
    if not p.exists():  # O(1) stat
        return out  # O(1)
    for ln in p.read_text(encoding="utf-8").splitlines():  # O(I) iterations; read O(log bytes)
        try:  # O(1)
            e = json.loads(ln)  # O(w)
        except json.JSONDecodeError:  # O(1)
            continue  # O(1)
        if (isinstance(e, dict) and "file" in e and e.get("kind") != "verified"  # O(1)
                and e.get("resolution") in (None, "open", "unresolved")):  # O(1)
            out.append(e)  # O(1)
    return out  # O(1)


def summary(ledger, log):  # O(R*w + I*w + C + G)
    rulings, commits, tests = read_ledger(ledger)  # O(R*w)
    incidents = open_incidents(log)  # O(I*w)
    out = ["# superlite run summary", ""]  # O(1)
    out.append(f"commits: {len(commits)}")  # O(1)
    out += [f"- {t} {sha[:10]} {title}".rstrip() for t, sha, title in commits]  # O(C)
    out.append("")  # O(1)
    out.append(f"rulings: {len(rulings)}")  # O(1)
    out += [f"- {r}" for r in rulings]  # O(G)
    out.append("")  # O(1)
    if tests:  # O(1)
        mode, p, f, s, sec = tests  # O(1)
        out.append(f"tests ({mode}): {p} passed, {f} failed, {s} skipped in {sec}s")  # O(1)
    else:  # O(1)
        out.append("tests: none recorded")  # O(1)
    out.append("")  # O(1)
    out.append(f"open incidents: {len(incidents)}")  # O(1)
    for e in incidents:  # O(I) iterations
        kind = e.get("kind") or "unknown"  # O(1)
        out.append(f"- {e['file']}:{e['line']} [{kind}] {e.get('context', '')}")  # O(w)
    return "\n".join(out) + "\n"  # O(R + C + G + I) join


def main(argv=None):  # O(R*w + I*w)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])  # O(1)
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)  # O(1)
    ap.add_argument("--log", default=DEFAULT_LOG)  # O(1)
    a = ap.parse_args(argv)  # O(1)
    sys.stdout.reconfigure(encoding="utf-8")  # O(1)
    sys.stdout.write(summary(a.ledger, a.log))  # O(output)
    return 0  # O(1)


if __name__ == "__main__":  # O(1)
    sys.exit(main())  # O(1)
