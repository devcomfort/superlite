#!/usr/bin/env python3
"""Run pytest, parse the junit XML, print one summary line.

    run_tests.py [--fast PATHS... | --full] [--log PATH] [--ledger PATH]

Prints `passed failed skipped seconds` (errors count as failed). Each failing
test becomes a `test-failure` incident; on a --full run each test file whose
tests all pass becomes a `verified` incident (once per distinct entry). Appends
a `tests` line to the progress ledger. Exit 0 when nothing failed, 1 when a
test failed or none ran, 2 when pytest could not run. Stdlib only.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import commit_task as ct  # noqa: E402
import next_tasks as nt  # noqa: E402


def case_file(case):
    f = case.get("file")
    if f:
        return f.replace("\\", "/")
    parts = (case.get("classname") or "").split(".")
    while parts and not Path(*parts).with_suffix(".py").exists():
        parts.pop()
    if parts:
        return Path(*parts).with_suffix(".py").as_posix()
    return case.get("name") or "unknown"


def failure_line(case, text, fallback):
    base = re.escape(Path(case_file(case)).name)
    hits = re.findall(rf"{base}:(\d+)", text or "")
    return int(hits[-1]) if hits else fallback


def parse_junit(xml_path):
    """-> (counts dict, failures [(file, line, context)], files {file: [ok, bad]})"""
    root = ET.parse(xml_path).getroot()
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    failures, files = [], {}
    for case in root.iter("testcase"):
        f = case_file(case)
        ok_bad = files.setdefault(f, [0, 0])
        bad = case.find("failure")
        if bad is None:
            bad = case.find("error")
        if bad is not None:
            counts["failed"] += 1
            ok_bad[1] += 1
            msg = (bad.get("message") or (bad.text or "").strip()).split("\n")[0]
            line = failure_line(case, bad.text, int(case.get("line") or 0) + 1)
            failures.append((f, line, f"{case.get('name')}: {msg}"))
        elif case.find("skipped") is not None:
            counts["skipped"] += 1
        else:
            counts["passed"] += 1
            ok_bad[0] += 1
    return counts, failures, files


def existing_verified(log):
    seen = set()
    p = Path(log)
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(e, dict) and e.get("kind") == "verified":
                seen.add((e.get("file"), e.get("context")))
    return seen


def add_incident(log, file, line, context, kind, resolution=None):
    nt.add_incident(log, file, line, context, kind, "run_tests", resolution)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--fast", nargs="+", metavar="PATH",
                      help="run only these test paths (comma or space separated)")
    mode.add_argument("--full", action="store_true", help="run everything (default)")
    ap.add_argument("--log", default=ct.DEFAULT_LOG)
    ap.add_argument("--ledger", default=ct.DEFAULT_LEDGER)
    a = ap.parse_args(argv)
    paths = [p for chunk in (a.fast or []) for p in nt.csv(chunk)]
    label = "fast" if paths else "full"

    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "junit.xml"
        cmd = [sys.executable, "-m", "pytest", *paths, "-q", "-p", "no:cacheprovider",
               "-o", "junit_family=xunit1", f"--junitxml={xml_path}"]
        t0 = time.monotonic()
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        seconds = time.monotonic() - t0
        if (r.returncode not in (0, 1) or not xml_path.exists()
                or xml_path.stat().st_size == 0):
            tail = (r.stdout + r.stderr).strip().splitlines()[-5:]
            print("pytest produced no results: " + " | ".join(tail), file=sys.stderr)
            print(f"0 0 0 {seconds:.1f}")
            return 1 if r.returncode == 5 else 2
        counts, failures, files = parse_junit(xml_path)

    for f, line, ctx in failures:
        add_incident(a.log, f, line, ctx, "test-failure", "open")
    if label == "full":
        seen = existing_verified(a.log)
        for f, (ok, bad) in sorted(files.items()):
            ctx = f"run_tests full: {ok} tests pass"
            if ok and not bad and (f, ctx) not in seen:
                add_incident(a.log, f, 0, ctx, "verified")

    summary = (f"{counts['passed']} {counts['failed']} {counts['skipped']} "
               f"{seconds:.1f}")
    ct.append_ledger(a.ledger, f"- tests {label} passed={counts['passed']} "
                     f"failed={counts['failed']} skipped={counts['skipped']} "
                     f"seconds={seconds:.1f}")
    print(summary)
    return 1 if counts["failed"] or not (counts["passed"] or counts["skipped"]) else 0


if __name__ == "__main__":
    sys.exit(main())
