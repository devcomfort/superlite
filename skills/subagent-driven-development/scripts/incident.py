#!/usr/bin/env python3
"""Append-only incident log: add, hotspots, summary. Stdlib only."""
import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

DEFAULT_LOG = ".superlite/incidents.jsonl"
KINDS = ("test-failure", "exception", "workaround", "spec-ambiguity",
         "assumption", "flaky", "perf", "unsure", "verified")
CONFIDENCE = ("low", "medium", "high")
MAX_CONTEXT = 200

if os.name == "nt":
    import msvcrt

    def _lock(f):
        f.seek(0)
        while True:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:
                time.sleep(0.01)

    def _unlock(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

    def _unlock(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def cmd_add(a):
    if a.line < 0:
        _die("line must be >= 0")
    if a.kind is not None and a.kind not in KINDS:
        _die(f"kind must be one of: {', '.join(KINDS)}")
    if a.confidence is not None and a.confidence not in CONFIDENCE:
        _die(f"confidence must be one of: {', '.join(CONFIDENCE)}")
    if not a.file or not a.context:
        _die("file and context are required")
    ctx = a.context
    if len(ctx) > MAX_CONTEXT:
        ctx = ctx[:MAX_CONTEXT - 1] + "…"
    entry = {"file": a.file, "line": a.line, "context": ctx}
    for key in ("agent", "kind", "resolution", "confidence"):
        val = getattr(a, key)
        if val is not None:
            entry[key] = val
    entry["time"] = time.strftime("%H:%M:%S")
    data = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    path = Path(a.log)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab+") as f:
        _lock(f)
        try:
            f.seek(0, os.SEEK_END)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        finally:
            _unlock(f)
    return 0


def _read(log):
    path = Path(log)
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                e = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if isinstance(e, dict) and "file" in e and "line" in e:
                out.append(e)
    return out


def _norm(p):
    return str(p).replace("\\", "/")


def cmd_hotspots(a):
    entries = _read(a.log)
    if a.files:
        wanted = {_norm(x.strip()) for x in a.files.split(",") if x.strip()}
        entries = [e for e in entries if _norm(e["file"]) in wanted]
    counts = Counter((_norm(e["file"]), e["line"]) for e in entries
                     if e.get("kind") != "verified")

    def key(e):
        loc = (_norm(e["file"]), e["line"])
        verified = e.get("kind") == "verified"
        repeated = not verified and counts[loc] > 1
        unresolved = not verified and e.get("resolution") in (None, "open")
        low = e.get("confidence") == "low"
        return (0 if repeated else 1, 0 if unresolved else 1,
                0 if low else 1, loc[0], loc[1])

    entries.sort(key=key)
    for e in entries[:a.max]:
        print(json.dumps(e, ensure_ascii=False))
    return 0


def cmd_summary(a):
    entries = _read(a.log)
    print(f"total: {len(entries)}")
    for name in ("kind", "resolution"):
        c = Counter(e.get(name, "-") for e in entries)
        print(f"{name}: " + ", ".join(f"{k}={v}" for k, v in sorted(c.items())))
    c = Counter(_norm(e["file"]) for e in entries)
    print("files: " + ", ".join(f"{k}={v}" for k, v in c.most_common(10)))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="incident.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add")
    s.add_argument("--file", required=True)
    s.add_argument("--line", type=int, required=True)
    s.add_argument("--context", required=True)
    s.add_argument("--agent")
    s.add_argument("--kind")
    s.add_argument("--resolution")
    s.add_argument("--confidence")
    s.add_argument("--log", default=DEFAULT_LOG)
    s.set_defaults(fn=cmd_add)
    s = sub.add_parser("hotspots")
    s.add_argument("--files")
    s.add_argument("--log", default=DEFAULT_LOG)
    s.add_argument("--max", type=int, default=30)
    s.set_defaults(fn=cmd_hotspots)
    s = sub.add_parser("summary")
    s.add_argument("--log", default=DEFAULT_LOG)
    s.set_defaults(fn=cmd_summary)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
