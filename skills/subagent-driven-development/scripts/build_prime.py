#!/usr/bin/env python3
"""Build the shared agent prime: byte-identical for the same inputs.

    build_prime.py --plan P --spec S --sections "1,3,5" [--out .superlite/prime.md] [--tier haiku]

--tier haiku (any tier whose prime is `mini` in config/routing.json) builds the mini prime into
.superlite/prime-haiku.md: constraints, stub spec and the interfaces of that tier's tasks, no spec.

Prints `sha256 size`. No timestamps; CRLF becomes LF, trailing spaces are
stripped, and spec sections go in document order whatever order they are
listed in. Stdlib only.
"""
# Complexity notation:
#   B = bytes of plan + spec read, L = lines in the spec, H = headings in the spec, w = width of one line,
#   n = length of the text being processed, S = sections requested (--sections), K = sections chosen,
#   out = bytes of the prime written
import argparse  # O(1)
import hashlib  # O(1)
import re  # O(1)
import sys  # O(1)
from pathlib import Path  # O(1)

DEFAULT_OUT = ".superlite/prime.md"  # O(1)
MINI_OUT = ".superlite/prime-haiku.md"  # O(1)
DEFAULT_MAX_BYTES = 120_000  # O(1)

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

PREAMBLE_MINI = """# superlite prime (mini)

You are a lane implementer in a superlite run: you take small, fully specified tasks. This prime is
identical for every lane agent in the run; the task you are given follows it. The full plan and spec
are not in your context: your task message and this prime state everything you need.

Rules:
- Build only what your task owns (its `Owns` files). Never edit other files.
- Test first, run only the fast focused tests, code to the interfaces below. Never change a signature.
- Do not commit. Kill processes by PID only.
- Reply READY after reading this prime, then wait for your task. Finish with DONE, DONE_WITH_CONCERNS,
  BLOCKED or NEEDS_CONTEXT in at most 200 words.
"""

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")  # O(1)


def die(msg, code=2):  # O(1)
    print(f"error: {msg}", file=sys.stderr)  # O(1)
    sys.exit(code)  # O(1)


def normalize(text):  # O(n)
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")  # O(n)
    return "\n".join(ln.rstrip(" \t") for ln in text.split("\n")).strip("\n")  # O(n)


def read(path):  # O(bytes read)
    p = Path(path)  # O(1)
    if not p.is_file():  # O(1) stat
        die(f"file not found: {path}")  # O(1)
    return normalize(p.read_text(encoding="utf-8"))  # O(bytes read)


def _heading_key(text):  # O(w)
    """Leading section number of a heading (`5.`, `4.1`, `§10`), else None."""  # O(1)
    m = re.match(r"^(?:§\s*)?(\d+(?:\.\d+)*)(?=[.\s:)]|$)", text)  # O(w)
    return m.group(1) if m else None  # O(1)


def split_sections(spec):  # O(L + H^2): the inner scan is quadratic for nested headings
    """[(level, heading text, start, end)] over lines; end is exclusive."""  # O(1)
    lines = spec.split("\n")  # O(B)
    heads, fence = [], False  # O(1)
    for i, ln in enumerate(lines):  # O(L) iterations
        if ln.lstrip().startswith(("```", "~~~")):  # O(w)
            fence = not fence  # O(1)
        m = None if fence else _HEADING.match(ln)  # O(w)
        if m:  # O(1)
            heads.append((len(m.group(1)), m.group(2), i))  # O(1)
    out = []  # O(1)
    for n, (lvl, text, start) in enumerate(heads):  # O(H) iterations
        end = len(lines)  # O(1)
        for lvl2, _, s2 in heads[n + 1:]:  # O(H) iterations worst case (scan to next same-or-higher heading)
            if lvl2 <= lvl:  # O(1)
                end = s2  # O(1)
                break  # O(1)
        out.append((lvl, text, start, end))  # O(1)
    return lines, out  # O(1)


def select_sections(spec, wanted):  # O(L + H^2 + S*H*w + K^2 + out)
    lines, secs = split_sections(spec)  # O(L + H^2)
    chosen = {}  # O(1)
    for token in wanted:  # O(S) iterations
        want = token.lstrip("§").lower()  # O(w)
        hit = None  # O(1)
        for idx, (lvl, text, _, _) in enumerate(secs):  # O(H) iterations per token
            if _heading_key(text) == want or (  # O(w) regex
                    not re.fullmatch(r"\d+(?:\.\d+)*", want)  # O(w) regex
                    and text.lower().startswith(want)):  # O(w)
                hit = idx  # O(1)
                break  # O(1)
        if hit is None:  # O(1)
            die(f"spec section not found: {token}")  # O(1)
        chosen[hit] = True  # O(1)
    picked = sorted(chosen)  # O(K log K)
    # drop sections nested inside another chosen one (already included)
    keep = [i for i in picked  # O(K) iterations
            if not any(j != i and secs[j][2] <= secs[i][2] < secs[j][3]  # O(K) per iteration (any over picked)
                       for j in picked)]  # O(K) per iteration
    return ["\n".join(lines[secs[i][2]:secs[i][3]]).strip("\n") for i in keep]  # O(out)


def build(plan, spec, sections):  # O(B + out)
    parts = [normalize(PREAMBLE), "## Plan\n\n" + read(plan)]  # O(B)
    if sections:  # O(1)
        chunks = select_sections(read(spec), sections)  # O(B + H^2)
        parts.append("## Spec sections\n\n" + "\n\n".join(normalize(c) for c in chunks))  # O(out)
    return ("\n\n".join(parts) + "\n").encode("utf-8")  # O(out)


def _is_mini(tier):  # O(1)
    import routing  # O(1)
    return (routing.load_cfg().get("tiers", {}).get(tier) or {}).get("prime") == "mini"  # O(file)


def build_mini(plan, tier):  # O(B + n*s)
    """Mini prime for the lane tier: constraints, the stub spec and the interfaces of that tier's tasks, from the plan alone."""
    import plan_tools as pt  # lazy | O(1)
    import routing  # O(1)
    import wave0  # O(1)
    pl = pt.Plan.load(plan)  # O(B)
    tiers = routing.read_tiers(plan)  # O(stable.json) or a computation
    mine = [t for t in pl.tasks if tiers.get(t.id) == tier]  # O(n)
    cons = wave0.constraint_lines(pl)  # O(B)
    nl = "\n"
    parts = [normalize(PREAMBLE_MINI), "## Constraints" + nl + nl + normalize(nl.join(cons) if cons else "(the plan states none)"),  # O(B)
             "## Stub spec" + nl + nl + "```yaml" + nl + normalize(wave0.stub_spec(pl)) + nl + "```"]  # O(q*s)
    lines = []  # O(1)
    for t in mine:  # O(n) iterations
        lines.append(f"### {t.id} {t.title}")  # O(1)
        lines.append("Owns: " + ", ".join(t.owns))  # O(o)
        lines += [f"Produces: {x}" for x in t.produces] + [f"Consumes: {x}" for x in t.consumes]  # O(q)
    parts.append("## Interfaces your tasks touch" + nl + nl + normalize(nl.join(lines) if lines else "(none yet)"))  # O(n*s)
    return ((nl + nl).join(parts) + nl).encode("utf-8")  # O(out)


def main(argv=None):  # O(B + H^2 + out)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])  # O(1) parser setup
    ap.add_argument("--plan", required=True)  # O(1)
    ap.add_argument("--spec")  # O(1)
    ap.add_argument("--sections", default="")  # O(1)
    ap.add_argument("--out", default=DEFAULT_OUT)  # O(1)
    ap.add_argument("--tier", default="sonnet", help="sonnet: the full prime; a tier whose prime is `mini` (haiku): the mini prime")  # O(1)
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)  # O(1)
    a = ap.parse_args(argv)  # O(1)
    sys.path.insert(0, str(Path(__file__).resolve().parent))  # O(1)
    import orchestrator  # O(1)
    blocked = orchestrator.require(a.plan, "build_prime")  # human mode waits for approval | O(file)
    if blocked:  # O(1)
        return blocked  # O(1)
    wanted = [s.strip() for s in a.sections.split(",") if s.strip()]  # O(len(--sections))
    if wanted and not a.spec:  # O(1)
        die("--sections needs --spec")  # O(1)
    mini = a.tier != "sonnet" and _is_mini(a.tier)  # O(1)
    data = build_mini(a.plan, a.tier) if mini else build(a.plan, a.spec, wanted)  # O(B + H^2 + out)
    if len(data) > a.max_bytes:  # O(1)
        die(f"prime is {len(data)} bytes, over the {a.max_bytes} cap; "  # O(1)
            "move spec excerpts to referenced paths", 1)  # O(1)
    out = Path(MINI_OUT if mini and a.out == DEFAULT_OUT else a.out)  # O(1)
    out.parent.mkdir(parents=True, exist_ok=True)  # O(path depth) filesystem call
    out.write_bytes(data)  # O(out) file write
    print(f"{hashlib.sha256(data).hexdigest()} {len(data)}")  # O(out) sha256
    return 0  # O(1)


if __name__ == "__main__":  # O(1)
    sys.exit(main())  # O(1)
