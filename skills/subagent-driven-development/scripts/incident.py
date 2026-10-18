#!/usr/bin/env python3
"""Append-only incident log: add, hotspots, summary. Stdlib only."""
# Complexity notation:
#   i = entries in the log, B = bytes of the log, f = distinct files in the log, d = distinct values of one field,
#   k = entries printed (--max), c = length of the context text, w = width of one log line, a = length of --files
import argparse  # O(1)
import json  # O(1)
import os  # O(1)
import sys  # O(1)
import time  # O(1)
from collections import Counter  # O(1)
from pathlib import Path  # O(1)

DEFAULT_LOG = ".superlite/incidents.jsonl"  # O(1)
KINDS = ("test-failure", "exception", "workaround", "spec-ambiguity",  # O(1)
         "assumption", "flaky", "perf", "unsure", "verified")  # O(1)
CONFIDENCE = ("low", "medium", "high")  # O(1)
MAX_CONTEXT = 200  # O(1)

if os.name == "nt":  # O(1)
    import msvcrt  # O(1)

    def _lock(f):  # O(1) per attempt
        f.seek(0)  # O(1)
        while True:  # O(1) per attempt: retries until the lock is free (contention wait)
            try:  # O(1)
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)  # O(1)
                return  # O(1)
            except OSError:  # O(1)
                time.sleep(0.01)  # O(1) 10 ms sleep per retry

    def _unlock(f):  # O(1)
        f.seek(0)  # O(1)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)  # O(1)
else:  # O(1)
    import fcntl  # O(1)

    def _lock(f):  # O(1)
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # O(1) + blocks until the lock is free

    def _unlock(f):  # O(1)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)  # O(1)


def _die(msg):  # O(1)
    print(f"error: {msg}", file=sys.stderr)  # O(1)
    sys.exit(2)  # O(1)


def cmd_add(a):  # O(c) + file append O(c) + fsync
    if a.line < 0:  # O(1)
        _die("line must be >= 0")  # O(1)
    if a.kind is not None and a.kind not in KINDS:  # O(1)
        _die(f"kind must be one of: {', '.join(KINDS)}")  # O(1)
    if a.confidence is not None and a.confidence not in CONFIDENCE:  # O(1)
        _die(f"confidence must be one of: {', '.join(CONFIDENCE)}")  # O(1)
    if not a.file or not a.context:  # O(1)
        _die("file and context are required")  # O(1)
    ctx = a.context  # O(1)
    if len(ctx) > MAX_CONTEXT:  # O(1)
        ctx = ctx[:MAX_CONTEXT - 1] + "…"  # O(c)
    entry = {"file": a.file, "line": a.line, "context": ctx}  # O(c)
    for key in ("agent", "kind", "resolution", "confidence"):  # O(1)
        val = getattr(a, key)  # O(1)
        if val is not None:  # O(1)
            entry[key] = val  # O(1)
    entry["time"] = time.strftime("%H:%M:%S")  # O(1)
    data = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")  # O(c)
    path = Path(a.log)  # O(1)
    path.parent.mkdir(parents=True, exist_ok=True)  # O(1)
    with open(path, "ab+") as f:  # O(1)
        _lock(f)  # O(1)
        try:  # O(1)
            f.seek(0, os.SEEK_END)  # O(1)
            f.write(data)  # O(c) append
            f.flush()  # O(1)
            os.fsync(f.fileno())  # O(c) I/O flush
        finally:  # O(1)
            _unlock(f)  # O(1)
    return 0  # O(1)


def _read(log):  # O(B)
    path = Path(log)  # O(1)
    if not path.exists():  # O(1)
        return []  # O(1)
    out = []  # O(1)
    with open(path, encoding="utf-8") as f:  # O(1) open
        for ln in f:  # O(i) iterations
            ln = ln.strip()  # O(w)
            if not ln:  # O(1)
                continue  # O(1)
            try:  # O(1)
                e = json.loads(ln)  # O(w)
            except json.JSONDecodeError:  # O(1)
                continue  # O(1)
            if isinstance(e, dict) and "file" in e and "line" in e:  # O(1)
                out.append(e)  # O(1)
    return out  # O(1)


def _norm(p):  # O(len(path))
    return str(p).replace("\\", "/")  # O(len(path))


def cmd_hotspots(a):  # O(B + i log i)
    entries = _read(a.log)  # O(B)
    if a.files:  # O(1)
        wanted = {_norm(x.strip()) for x in a.files.split(",") if x.strip()}  # O(a + f)
        entries = [e for e in entries if _norm(e["file"]) in wanted]  # O(i)
    counts = Counter((_norm(e["file"]), e["line"]) for e in entries  # O(i) Counter
                     if e.get("kind") != "verified")  # O(1)

    def key(e):  # O(1) per call
        loc = (_norm(e["file"]), e["line"])  # O(1)
        verified = e.get("kind") == "verified"  # O(1)
        repeated = not verified and counts[loc] > 1  # O(1)
        unresolved = not verified and e.get("resolution") in (None, "open")  # O(1)
        low = e.get("confidence") == "low"  # O(1)
        return (0 if repeated else 1, 0 if unresolved else 1,  # O(1)
                0 if low else 1, loc[0], loc[1])  # O(1)

    entries.sort(key=key)  # O(i log i)
    for e in entries[:a.max]:  # O(min(i, k)) iterations
        print(json.dumps(e, ensure_ascii=False))  # O(w)
    return 0  # O(1)


def cmd_summary(a):  # O(B + i + d log d + f)
    entries = _read(a.log)  # O(B)
    print(f"total: {len(entries)}")  # O(1)
    for name in ("kind", "resolution"):  # O(1) iterations (2)
        c = Counter(e.get(name, "-") for e in entries)  # O(i)
        print(f"{name}: " + ", ".join(f"{k}={v}" for k, v in sorted(c.items())))  # O(d log d)
    c = Counter(_norm(e["file"]) for e in entries)  # O(i)
    print("files: " + ", ".join(f"{k}={v}" for k, v in c.most_common(10)))  # O(f) most_common(10)
    return 0  # O(1)


def main(argv=None):  # O(1) parser setup + command cost
    p = argparse.ArgumentParser(prog="incident.py")  # O(1)
    sub = p.add_subparsers(dest="cmd", required=True)  # O(1)
    s = sub.add_parser("add")  # O(1)
    s.add_argument("--file", required=True)  # O(1)
    s.add_argument("--line", type=int, required=True)  # O(1)
    s.add_argument("--context", required=True)  # O(1)
    s.add_argument("--agent")  # O(1)
    s.add_argument("--kind")  # O(1)
    s.add_argument("--resolution")  # O(1)
    s.add_argument("--confidence")  # O(1)
    s.add_argument("--log", default=DEFAULT_LOG)  # O(1)
    s.set_defaults(fn=cmd_add)  # O(1)
    s = sub.add_parser("hotspots")  # O(1)
    s.add_argument("--files")  # O(1)
    s.add_argument("--log", default=DEFAULT_LOG)  # O(1)
    s.add_argument("--max", type=int, default=30)  # O(1)
    s.set_defaults(fn=cmd_hotspots)  # O(1)
    s = sub.add_parser("summary")  # O(1)
    s.add_argument("--log", default=DEFAULT_LOG)  # O(1)
    s.set_defaults(fn=cmd_summary)  # O(1)
    a = p.parse_args(argv)  # O(len(argv))
    return a.fn(a)  # O(cmd cost)


if __name__ == "__main__":  # O(1)
    sys.exit(main())  # O(1)
