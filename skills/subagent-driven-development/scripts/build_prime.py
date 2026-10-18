#!/usr/bin/env python3
"""Build the shared agent prime: byte-identical for the same inputs.

    build_prime.py --plan P --spec S --sections "1,3,5" [--out .superlite/prime.md]

Prints `sha256 size`. No timestamps; CRLF becomes LF, trailing spaces are
stripped, and spec sections go in document order whatever order they are
listed in. Stdlib only.
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

DEFAULT_OUT = ".superlite/prime.md"
DEFAULT_MAX_BYTES = 120_000

PREAMBLE = """\
# superlite prime

You are an implementer subagent in a superlite run. This prime is identical
for every agent in the run; the task you are given follows it.

Rules:
- Build only what your task owns (its `Owns` files). Never edit other files.
- Test first: write the failing test, run it, implement, run it again.
- Run only fast, focused tests. Slow suites run later through run_tests.py.
- Code to the interface stubs and the plan's Consumes and Produces lines.
  Never change a signature without a coordinator ruling.
- Log every unexpected failure, workaround or guess with incident.py add.
- Do not commit. The coordinator commits through commit_task.py.
- Kill processes by PID only. Never use taskkill /IM, pkill or killall.
- Reply READY after reading this prime, then wait for your task.
- Finish with DONE, DONE_WITH_CONCERNS, BLOCKED or NEEDS_CONTEXT, in at most
  200 words, with no file contents or logs.
"""

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def die(msg, code=2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def normalize(text):
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(ln.rstrip(" \t") for ln in text.split("\n")).strip("\n")


def read(path):
    p = Path(path)
    if not p.is_file():
        die(f"file not found: {path}")
    return normalize(p.read_text(encoding="utf-8"))


def _heading_key(text):
    """Leading section number of a heading (`5.`, `4.1`, `§10`), else None."""
    m = re.match(r"^(?:§\s*)?(\d+(?:\.\d+)*)(?=[.\s:)]|$)", text)
    return m.group(1) if m else None


def split_sections(spec):
    """[(level, heading text, start, end)] over lines; end is exclusive."""
    lines = spec.split("\n")
    heads, fence = [], False
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith(("```", "~~~")):
            fence = not fence
        m = None if fence else _HEADING.match(ln)
        if m:
            heads.append((len(m.group(1)), m.group(2), i))
    out = []
    for n, (lvl, text, start) in enumerate(heads):
        end = len(lines)
        for lvl2, _, s2 in heads[n + 1:]:
            if lvl2 <= lvl:
                end = s2
                break
        out.append((lvl, text, start, end))
    return lines, out


def select_sections(spec, wanted):
    lines, secs = split_sections(spec)
    chosen = {}
    for token in wanted:
        want = token.lstrip("§").lower()
        hit = None
        for idx, (lvl, text, _, _) in enumerate(secs):
            if _heading_key(text) == want or (
                    not re.fullmatch(r"\d+(?:\.\d+)*", want)
                    and text.lower().startswith(want)):
                hit = idx
                break
        if hit is None:
            die(f"spec section not found: {token}")
        chosen[hit] = True
    picked = sorted(chosen)
    # drop sections nested inside another chosen one (already included)
    keep = [i for i in picked
            if not any(j != i and secs[j][2] <= secs[i][2] < secs[j][3]
                       for j in picked)]
    return ["\n".join(lines[secs[i][2]:secs[i][3]]).strip("\n") for i in keep]


def build(plan, spec, sections):
    parts = [normalize(PREAMBLE), "## Plan\n\n" + read(plan)]
    if sections:
        chunks = select_sections(read(spec), sections)
        parts.append("## Spec sections\n\n" + "\n\n".join(normalize(c) for c in chunks))
    return ("\n\n".join(parts) + "\n").encode("utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plan", required=True)
    ap.add_argument("--spec")
    ap.add_argument("--sections", default="")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    a = ap.parse_args(argv)
    wanted = [s.strip() for s in a.sections.split(",") if s.strip()]
    if wanted and not a.spec:
        die("--sections needs --spec")
    data = build(a.plan, a.spec, wanted)
    if len(data) > a.max_bytes:
        die(f"prime is {len(data)} bytes, over the {a.max_bytes} cap; "
            "move spec excerpts to referenced paths", 1)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"{hashlib.sha256(data).hexdigest()} {len(data)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
