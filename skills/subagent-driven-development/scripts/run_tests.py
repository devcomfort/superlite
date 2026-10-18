#!/usr/bin/env python3
"""Run pytest, parse the junit XML, print one summary line.

    run_tests.py [--fast PATHS... | --full] [--log PATH] [--ledger PATH]
                 [--summary PATH]

Prints `passed failed skipped seconds` (errors count as failed). Each failing
test becomes a `test-failure` incident; on a --full run each test file whose
tests all pass becomes a `verified` incident (once per distinct entry). Appends
a `tests` line to the progress ledger. On every run it also writes
`.superlite/test-summary.json` (--summary), the file `pt_review packet` reads:
`{"passed": N, "failed": N, "skipped": N, "seconds": S, "mode": "fast|full",
"failures": ["file::test: message", ...], "skipped_tests": ["file::test", ...]}`
(a run where pytest produced nothing records failed=1 and the reason). Exit 0 when nothing failed, 1 when a
test failed or none ran, 2 when pytest could not run. Stdlib only.
"""
# Complexity notation:
#   T = testcases in the junit XML, X = bytes of the XML, F = distinct test files, k = failing tests,
#   sk = skipped tests, I = lines in the incident log (B = its bytes), d = depth of a dotted classname,
#   p = pytest path args, O = bytes of pytest output, c = length of an incident context, w = width of one line
import argparse  # O(1)
import json  # O(1)
import re  # O(1)
import subprocess  # O(1)
import sys  # O(1)
import tempfile  # O(1)
import time  # O(1)
import xml.etree.ElementTree as ET  # O(1)
from pathlib import Path  # O(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))  # O(path list)
import _pyrun as pyrun  # noqa: E402  # O(1) module load
import commit_task as ct  # noqa: E402  # O(1) module load
import next_tasks as nt  # noqa: E402  # O(1) module load


DEFAULT_SUMMARY = ".superlite/test-summary.json"  # O(1)


def case_file(case):  # O(d) stats, O(d^2) path work (stats are uncached)
    f = case.get("file")  # O(1)
    if f:  # O(1)
        return f.replace("\\", "/")  # O(len(f))
    parts = (case.get("classname") or "").split(".")  # O(d)
    while parts and not Path(*parts).with_suffix(".py").exists():  # O(d) iterations; Path join + stat O(d) each
        parts.pop()  # O(1)
    if parts:  # O(d)
        return Path(*parts).with_suffix(".py").as_posix()  # O(d)
    return case.get("name") or "unknown"  # O(1)


def failure_line(case, text, fallback):  # O(len(text) + d)
    base = re.escape(Path(case_file(case)).name)  # O(d) stats + O(len)
    hits = re.findall(rf"{base}:(\d+)", text or "")  # O(len(text))
    return int(hits[-1]) if hits else fallback  # O(1)


def parse_junit(xml_path):  # O(X + T*(d + len(failure text)))
    """-> (counts dict, failures [(file, line, context)], files {file: [ok, bad]});
    skipped test ids are in counts["skipped_tests"]"""
    root = ET.parse(xml_path).getroot()  # O(X) XML parse
    counts = {"passed": 0, "failed": 0, "skipped": 0, "skipped_tests": []}  # O(1)
    failures, files = [], {}  # O(1)
    for case in root.iter("testcase"):  # O(T) iterations
        f = case_file(case)  # O(d) stats per testcase (uncached; repeated in failure_line)
        ok_bad = files.setdefault(f, [0, 0])  # O(1)
        bad = case.find("failure")  # O(1)
        if bad is None:  # O(1)
            bad = case.find("error")  # O(1)
        if bad is not None:  # O(1)
            counts["failed"] += 1  # O(1)
            ok_bad[1] += 1  # O(1)
            msg = (bad.get("message") or (bad.text or "").strip()).split("\n")[0]  # O(len(failure text))
            line = failure_line(case, bad.text, int(case.get("line") or 0) + 1)  # O(len(failure text) + d)
            failures.append((f, line, f"{case.get('name')}: {msg}"))  # O(1)
        elif case.find("skipped") is not None:  # O(1)
            counts["skipped"] += 1  # O(1)
            counts["skipped_tests"].append(f"{f}::{case.get('name')}")  # O(1)
        else:  # O(1)
            counts["passed"] += 1  # O(1)
            ok_bad[0] += 1  # O(1)
    return counts, failures, files  # O(1)


def existing_verified(log):  # O(B)
    seen = set()  # O(1)
    p = Path(log)  # O(1)
    if p.exists():  # O(1)
        for ln in p.read_text(encoding="utf-8").splitlines():  # O(I) iterations; read O(B)
            try:  # O(1)
                e = json.loads(ln)  # O(w)
            except json.JSONDecodeError:  # O(1)
                continue  # O(1)
            if isinstance(e, dict) and e.get("kind") == "verified":  # O(1)
                seen.add((e.get("file"), e.get("context")))  # O(1)
    return seen  # O(1)


def write_summary(path, mode, counts, failures, seconds, error=None):  # O(k + sk) + file write
    """Write the test summary `pt_review packet` reads (atomically)."""  # O(1)
    data = {"passed": counts["passed"], "failed": counts["failed"] + (1 if error else 0),  # O(1)
            "skipped": counts["skipped"], "seconds": round(seconds, 1), "mode": mode,  # O(1)
            "failures": [f"{f}::{ctx}"[:200] for f, _line, ctx in failures]  # O(k)
            + ([error[:200]] if error else []),  # O(k) list concat
            "skipped_tests": counts["skipped_tests"]}  # O(1)
    p = Path(path)  # O(1)
    p.parent.mkdir(parents=True, exist_ok=True)  # O(1)
    tmp = p.with_name(p.name + ".tmp")  # O(1)
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")  # O(k + sk) dumps + write
    tmp.replace(p)  # O(1) rename


def add_incidents(log, items):  # O(total c) + one locked append (no spawn in process)
    """items: (file, line, context, kind, resolution)."""
    nt.add_incidents(log, [(f, line, ctx, kind, "run_tests", res)  # O(k)
                           for f, line, ctx, kind, res in items])


def main(argv=None):  # O(X + T*d + B + F log F) + pytest run + one incident append
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])  # O(1)
    mode = ap.add_mutually_exclusive_group()  # O(1)
    mode.add_argument("--fast", nargs="+", metavar="PATH",  # O(1)
                      help="run only these test paths (comma or space separated)")  # O(1)
    mode.add_argument("--full", action="store_true", help="run everything (default)")  # O(1)
    ap.add_argument("--log", default=ct.DEFAULT_LOG)  # O(1)
    ap.add_argument("--ledger", default=ct.DEFAULT_LEDGER)  # O(1)
    ap.add_argument("--summary", default=DEFAULT_SUMMARY,  # O(1)
                    help="test summary JSON for pt_review packet (default %(default)s)")  # O(1)
    a = ap.parse_args(argv)  # O(1)
    paths = [p for chunk in (a.fast or []) for p in nt.csv(chunk)]  # O(p)
    label = "fast" if paths else "full"  # O(1)

    with tempfile.TemporaryDirectory() as tmp:  # O(1) mkdtemp
        xml_path = Path(tmp) / "junit.xml"  # O(1)
        try:  # O(1)
            base = pyrun.pytest_cmd()  # O(1) + at most one probe spawn
        except pyrun.PytestUnavailable as e:  # O(1)
            print(f"run_tests: {e}", file=sys.stderr)  # O(1)
            print("0 0 0 0.0")  # O(1)
            return 2  # O(1)
        cmd = [*base, *paths, "-q", "-p", "no:cacheprovider",  # O(p)
               "-o", "junit_family=xunit1", f"--junitxml={xml_path}"]  # O(1)
        t0 = time.monotonic()  # O(1)
        r = pyrun.run_tree(cmd, capture_output=True, text=True, encoding="utf-8",  # O(O) + process spawn (pytest run time dominates)
                           errors="replace")  # O(1)
        seconds = time.monotonic() - t0  # O(1)
        if (r.returncode not in (0, 1) or not xml_path.exists()  # O(1)
                or xml_path.stat().st_size == 0):  # O(1)
            tail = (r.stdout + r.stderr).strip().splitlines()[-5:]  # O(O)
            reason = "pytest produced no results: " + " | ".join(tail)  # O(1)
            print(reason, file=sys.stderr)  # O(1)
            write_summary(a.summary, label, {"passed": 0, "failed": 0, "skipped": 0,  # O(1)
                                             "skipped_tests": []}, [], seconds,  # O(1)
                          error=reason if r.returncode != 5 else None)  # O(1)
            print(f"0 0 0 {seconds:.1f}")  # O(1)
            return 1 if r.returncode == 5 else 2  # O(1)
        counts, failures, files = parse_junit(xml_path)  # O(X + T*d)

    write_summary(a.summary, label, counts, failures, seconds)  # O(k + sk)
    items = [(f, line, ctx, "test-failure", "open") for f, line, ctx in failures]  # O(k)
    if label == "full":  # O(1)
        seen = existing_verified(a.log)  # O(B)
        for f, (ok, bad) in sorted(files.items()):  # O(F log F) sort; O(F) iterations
            ctx = f"run_tests full: {ok} tests pass"  # O(1)
            if ok and not bad and (f, ctx) not in seen:  # O(1) set lookup
                items.append((f, 0, ctx, "verified", None))  # O(1)
    add_incidents(a.log, items)  # O(k + F) one append

    summary = (f"{counts['passed']} {counts['failed']} {counts['skipped']} "  # O(1)
               f"{seconds:.1f}")  # O(1)
    ct.append_ledger(a.ledger, f"- tests {label} passed={counts['passed']} "  # O(1)
                     f"failed={counts['failed']} skipped={counts['skipped']} "  # O(1)
                     f"seconds={seconds:.1f}")  # O(1)
    print(summary)  # O(1)
    return 1 if counts["failed"] or not (counts["passed"] or counts["skipped"]) else 0  # O(1)


if __name__ == "__main__":  # O(1)
    sys.exit(main())  # O(1)
