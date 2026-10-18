#!/usr/bin/env python3
"""plan_tools: mechanical tooling for superlite plans (D17).

Subcommands implemented here: taskgraph, stubs, schedule, lint.
Subcommands adapter, packet and contract live in pt_review.py (lazy import).

Exit codes: 0 ok, 1 findings (stubs import failure, lint issues), 2 bad plan or usage.
Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = SCRIPT_DIR.parent / "config"
REVIEW_COMMANDS = ("adapter", "packet", "contract")
IMPLEMENTER_PREFIX = 18000
CTX_CEILING = 80000
MERGE_MIN_VARIABLE = 18000
MERGE_MIN_MINUTES = 1.0
DEFAULT_CAP = 10
DEFAULT_MAX_TASK_MIN = 3.0
DEFAULT_MAX_CHARS = 15000

TASK_ID = r"T\d+[a-z]*"
TASK_ID_RE = re.compile(rf"^{TASK_ID}$")
HEADING_RE = re.compile(rf"^#{{3,4}}\s+({TASK_ID})\b(.*)$")
ANY_HEADING_RE = re.compile(r"^#{1,4}\s")
FIELD_RE = re.compile(r"^\*\*([^*:]+?)(?:\s*\([^)]*\))?:\*\*\s*(.*)$")
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")


class PlanError(Exception):
    def __init__(self, message: str, code: int = 2):
        super().__init__(message)
        self.code = code


def nkey(tid: str):
    m = re.match(r"T(\d+)([a-z]*)$", tid)
    return (int(m.group(1)), m.group(2)) if m else (10**9, tid)


# --------------------------------------------------------------------------
# Plan parsing
# --------------------------------------------------------------------------

@dataclass
class FenceBlock:
    start: int  # index of opening fence line
    end: int  # index of closing fence line (or last line if unterminated)
    info: str
    content: list[str]


def scan_fences(lines: list[str]):
    """Return (fenced flags per line, top-level fence blocks)."""
    flags: list[bool] = []
    blocks: list[FenceBlock] = []
    opened = None  # (char, length, info, start)
    for i, ln in enumerate(lines):
        m = FENCE_RE.match(ln)
        if opened is None:
            if m:
                opened = (m.group(1)[0], len(m.group(1)), m.group(2).strip(), i)
                flags.append(True)
            else:
                flags.append(False)
        else:
            flags.append(True)
            if m and m.group(1)[0] == opened[0] and len(m.group(1)) >= opened[1] and not m.group(2).strip():
                blocks.append(FenceBlock(opened[3], i, opened[2], lines[opened[3] + 1:i]))
                opened = None
    if opened is not None:
        blocks.append(FenceBlock(opened[3], len(lines) - 1, opened[2], lines[opened[3] + 1:]))
    return flags, blocks


def expand_braces(s: str) -> list[str]:
    m = re.search(r"\{([^{}]*)\}", s)
    if not m:
        return [s]
    out: list[str] = []
    for alt in m.group(1).split(","):
        out.extend(expand_braces(s[:m.start()] + alt.strip() + s[m.end():]))
    return out


def split_top_level(s: str, sep: str = ",") -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch in "{([":
            depth += 1
        elif ch in "})]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def strip_ticks(s: str) -> str:
    return s.strip().strip("`").strip()


@dataclass
class Task:
    id: str
    title: str = ""
    heading: str = ""
    line: int = 0
    fields: dict[str, list[str]] = field(default_factory=dict)
    text: str = ""  # whole section text
    synthetic: bool = False

    def field_text(self, name: str) -> str:
        return " ".join(x for x in self.fields.get(name, []) if x).strip()

    @property
    def owns(self) -> list[str]:
        out: list[str] = []
        for raw in self.fields.get("owns", []):
            for part in split_top_level(raw):
                part = strip_ticks(part.lstrip("-* ").strip())
                if part:
                    out.extend(expand_braces(part))
        return out

    @property
    def owned_sources(self) -> list[str]:
        res = []
        for p in self.owns:
            q = p.replace("\\", "/")
            name = q.rsplit("/", 1)[-1]
            if q.endswith(".py") and not q.startswith("tests/") and "/tests/" not in q and not name.startswith("test_"):
                res.append(q)
        return res

    def _items(self, name: str) -> list[str]:
        items: list[str] = []
        for raw in self.fields.get(name, []):
            raw = raw.strip()
            if not raw:
                continue
            for part in re.split(r"\s+·\s+", raw):
                part = strip_ticks(part.lstrip("-* ").strip())
                if part:
                    items.append(part)
        return items

    @property
    def produces(self) -> list[str]:
        return self._items("produces")

    @property
    def consumes(self) -> list[str]:
        return self._items("consumes")

    @property
    def contract_text(self) -> str:
        return self.field_text("contract") or self.field_text("notes")

    @property
    def stated_time(self) -> float | None:
        m = re.search(r"Est\.\s*time[:\s]+~?\s*(\d+(?:\.\d+)?)\s*min", self.heading)
        if m:
            return float(m.group(1))
        m = re.match(r"~?\s*(\d+(?:\.\d+)?)\s*min", self.field_text("est. time"))
        return float(m.group(1)) if m else None

    @property
    def stated_context(self) -> int | None:
        m = re.search(r"Est\.\s*context[:\s]+~?\s*(\d+(?:\.\d+)?)\s*k", self.heading)
        if not m:
            m = re.match(r"~?\s*(\d+(?:\.\d+)?)\s*k", self.field_text("est. context"))
        return int(round(float(m.group(1)) * 1000)) if m else None

    @property
    def complexity(self) -> int | None:
        m = re.search(r"Complexity\s+(\d+)", self.heading)
        return int(m.group(1)) if m else None

    @property
    def features(self) -> dict:
        """Measurable features incl. the legacy Est. time parenthetical as a fallback."""
        return self._features(True)

    @property
    def explicit_features(self) -> dict:
        """Only what the plan states as fields: **Features:** or **Components/LOC owned/Tests/Model:**."""
        return self._features(False)

    @property
    def has_features(self) -> bool:
        """True when the coordinator wrote features; then the predictor's value wins over Est. time."""
        return bool(set(self.explicit_features) & {"components", "loc", "tests"})

    def _features(self, parenthetical: bool) -> dict:
        f: dict = {}

        def take(text: str):
            for key, pat in (
                ("components", r"components?\s*[=:]?\s*(\d+)|(\d+)\s+components?"),
                ("loc", r"\bloc(?:\s+owned)?\s*[=:]?\s*~?(\d+)|(?:about\s+|~)?(\d+)\s*loc\b"),
                ("docs_chars", r"docs?(?:\s+chars)?\s*[=:]\s*(\d+)"),
                ("reads_loc", r"reads?(?:\s+loc)?\s*[=:]\s*(\d+)"),
            ):
                if key in f:
                    continue
                m = re.search(pat, text, re.I)
                if m:
                    f[key] = int(next(g for g in m.groups() if g))
            if "tests" not in f:
                m = re.search(r"tests?\s*[=:]\s*(fast|slow)|\b(fast|slow)\s+tests?\b", text, re.I)
                if m:
                    f["tests"] = (m.group(1) or m.group(2)).lower()
            if "model" not in f:
                m = re.search(r"model\s*[=:]\s*([A-Za-z][\w.\-]*)", text, re.I)
                if m:
                    f["model"] = m.group(1).lower()

        take(self.field_text("features"))
        for name, key in (("components", "components"), ("loc owned", "loc"), ("loc", "loc"),
                          ("model", "model"), ("tests", "tests"), ("test speed", "tests")):
            val = self.field_text(name)
            if val and key not in f:
                take(f"{key}={val}")
        if parenthetical and ("loc" not in f or "components" not in f or "tests" not in f):
            m = re.search(r"\(([^)]*)\)", self.field_text("est. time"))
            if m:
                take(m.group(1))
        return f


class Plan:
    def __init__(self, text: str, path: Path | None = None):
        self.path = path
        self.eol = "\r\n" if "\r\n" in text else "\n"
        self.text = text.replace("\r\n", "\n")
        self.lines = self.text.split("\n")
        self.fenced, self.blocks = scan_fences(self.lines)
        self.tasks: list[Task] = self._parse_tasks()
        self.by_id = {t.id: t for t in self.tasks}

    @classmethod
    def load(cls, path: str) -> "Plan":
        p = Path(path)
        if not p.is_file():
            raise PlanError(f"plan not found: {path}")
        return cls(p.read_bytes().decode("utf-8-sig"), p)

    def _parse_tasks(self) -> list[Task]:
        tasks: list[Task] = []
        cur: Task | None = None
        cur_field: str | None = None
        body: list[str] = []

        def close():
            if cur is not None:
                cur.text = "\n".join(body)

        for i, ln in enumerate(self.lines):
            if not self.fenced[i]:
                m = HEADING_RE.match(ln)
                if m:
                    close()
                    title = m.group(2).strip().lstrip("·").strip()
                    title = re.split(r"\s+·\s+|\s{2,}", title)[0].strip()
                    cur = Task(id=m.group(1), title=title, heading=ln, line=i)
                    tasks.append(cur)
                    cur_field, body = None, [ln]
                    continue
                if ANY_HEADING_RE.match(ln):
                    close()
                    cur, cur_field, body = None, None, []
                    continue
            if cur is None:
                continue
            body.append(ln)
            if self.fenced[i]:
                continue
            fm = FIELD_RE.match(ln.strip())
            if fm:
                cur_field = fm.group(1).strip().lower()
                cur.fields.setdefault(cur_field, []).append(fm.group(2).strip())
            elif cur_field and re.match(r"^\s*[-*]\s+", ln):
                cur.fields[cur_field].append(ln.strip())
            elif not ln.strip():
                cur_field = None
            elif cur_field and ln.startswith((" ", "\t")):
                cur.fields[cur_field].append(ln.strip())
            else:
                cur_field = None
        close()
        return tasks

    def mermaid_blocks(self) -> list[FenceBlock]:
        return [b for b in self.blocks if b.info.lower().startswith("mermaid")]

    def header_target(self) -> float | None:
        m = re.search(r"^\*\*Target(?:[-\s]*(?:min|minutes|time))?:\*\*\s*~?\s*(\d+(?:\.\d+)?)", self.text, re.M)
        return float(m.group(1)) if m else None

    def non_fenced_text(self) -> str:
        return "\n".join(ln for ln, f in zip(self.lines, self.fenced) if not f)

    def to_text(self) -> str:
        return "\n".join(self.lines).replace("\n", self.eol) if self.eol != "\n" else "\n".join(self.lines)


# --------------------------------------------------------------------------
# Task graph
# --------------------------------------------------------------------------

def find_taskgraph_blocks(plan: Plan) -> list[tuple[FenceBlock, int]]:
    found = []
    for b in plan.mermaid_blocks():
        for j, ln in enumerate(b.content):
            if re.match(r"^\s*%%\s*taskgraph\b", ln):
                found.append((b, j))
                break
    return found


def _node_token(part: str) -> str:
    cleaned = re.sub(r'\[[^\]]*\]|\([^)]*\)|\{[^}]*\}|"[^"]*"', "", part).strip()
    m = re.match(r"[A-Za-z_][\w\-]*", cleaned)
    return m.group(0) if m else cleaned


def parse_taskgraph(plan: Plan) -> dict[str, list[str]]:
    blocks = find_taskgraph_blocks(plan)
    if not blocks:
        raise PlanError("no '%% taskgraph' block found in plan")
    deps: dict[str, set[str]] = {}
    mentioned: list[str] = []
    skip = ("flowchart", "graph", "subgraph", "end", "direction", "classdef", "style", "class", "click", "linkstyle")
    for block, j in blocks:
        for raw in block.content[j + 1:]:
            ln = raw.strip()
            if not ln or ln.startswith("%%"):
                continue
            if ln.split()[0].lower() in skip:
                continue
            parts = re.split(r"\s*-->\s*(?:\|[^|]*\|\s*)?", ln)
            groups: list[list[str]] = []
            for part in parts:
                ids = [_node_token(p) for p in part.split("&") if p.strip()]
                groups.append(ids)
            for ids in groups:
                for tid in ids:
                    if not TASK_ID_RE.match(tid):
                        raise PlanError(f"unknown task id {tid!r} in taskgraph")
                    deps.setdefault(tid, set())
                    if tid not in mentioned:
                        mentioned.append(tid)
            for left, right in zip(groups, groups[1:]):
                for b_ in right:
                    for a_ in left:
                        deps[b_].add(a_)
    known = set(plan.by_id)
    if known:
        for tid in mentioned:
            if tid not in known:
                raise PlanError(f"unknown task id {tid!r} in taskgraph (no such task in plan)")
    order = [t.id for t in plan.tasks] + [t for t in mentioned if t not in known]
    graph: dict[str, list[str]] = {}
    for tid in order:
        graph[tid] = sorted(deps.get(tid, set()), key=nkey)
    cycle = find_cycle(graph)
    if cycle:
        raise PlanError("cycle in taskgraph: " + " → ".join(cycle))
    return graph


def find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(n: str):
        state[n] = 1
        stack.append(n)
        for d in graph.get(n, []):
            if state.get(d, 0) == 1:
                return stack[stack.index(d):] + [d]
            if state.get(d, 0) == 0:
                r = visit(d)
                if r:
                    return r
        stack.pop()
        state[n] = 2
        return None

    for n in graph:
        if state.get(n, 0) == 0:
            r = visit(n)
            if r:
                return list(reversed(r))
    return None


def ancestors(graph: dict[str, list[str]]) -> dict[str, set[str]]:
    memo: dict[str, set[str]] = {}

    def anc(n: str) -> set[str]:
        if n in memo:
            return memo[n]
        memo[n] = set()
        s: set[str] = set()
        for d in graph.get(n, []):
            s.add(d)
            s |= anc(d)
        memo[n] = s
        return s

    for n in graph:
        anc(n)
    return memo


def seams_of(graph: dict[str, list[str]]) -> list[str]:
    out = []
    for t in graph:
        for d in graph[t]:
            out.append(f"{d}↔{t}")
    return out


# --------------------------------------------------------------------------
# Predictor glue and scheduling
# --------------------------------------------------------------------------

def _predict():
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    import predict  # noqa: WPS433 (lazy: predict imports this module)
    return predict


def effective_times(plan: Plan, graph: dict[str, list[str]], args) -> tuple[dict[str, float], dict[str, str]]:
    """Per-task minutes. Features present: the predictor's value wins. A stated `Est. time` is used only
    for a task with no features, or for every task with --stated."""
    predict = _predict()
    models = predict.load_models(getattr(args, "models", None))
    coef = predict.load_coef(getattr(args, "coef", None))
    force_stated = bool(getattr(args, "stated", False))
    times: dict[str, float] = {}
    source: dict[str, str] = {}
    for tid in graph:
        task = plan.by_id.get(tid) or Task(id=tid, synthetic=True)
        stated = task.stated_time if (force_stated or not task.has_features) else None
        if stated is not None:
            times[tid], source[tid] = float(stated), "stated"
        else:
            p = predict.predict_task(task, models, coef)
            times[tid], source[tid] = p["est_time_min"], p["source"]
    return times, source


def simulate(times: dict[str, float], graph: dict[str, list[str]], cap: int) -> dict:
    order = {t: i for i, t in enumerate(sorted(graph, key=nkey))}
    done: dict[str, float] = {}
    start: dict[str, float] = {}
    lane: dict[str, int] = {}
    running: list[tuple[float, int, str, int]] = []
    free = list(range(1, max(1, cap) + 1))
    remaining = set(graph)
    now = 0.0
    while remaining or running:
        ready = [t for t in remaining if all(d in done for d in graph[t])]
        ready.sort(key=lambda t: (-times[t], order[t]))
        while ready and free:
            t = ready.pop(0)
            ln = min(free)
            free.remove(ln)
            start[t], lane[t] = now, ln
            running.append((now + times[t], order[t], t, ln))
            remaining.discard(t)
        if not running:
            break
        running.sort()
        now = running[0][0]
        while running and running[0][0] <= now + 1e-12:
            end, _, t, ln = running.pop(0)
            done[t] = end
            free.append(ln)
    events = []
    for t in start:
        if times[t] > 0:
            events.append((start[t], 1))
            events.append((done[t], -1))
    events.sort(key=lambda e: (e[0], e[1]))
    width = peak = 0
    for _, d in events:
        width += d
        peak = max(peak, width)
    # critical path on the dependency graph (unlimited lanes)
    ef: dict[str, float] = {}
    pred: dict[str, str | None] = {}
    anc_all = ancestors(graph)
    for t in sorted(graph, key=lambda x: (len(anc_all[x]), nkey(x))):
        best, bp = 0.0, None
        for d in sorted(graph[t], key=nkey):
            if ef[d] > best + 1e-12:
                best, bp = ef[d], d
        ef[t] = best + times[t]
        pred[t] = bp
    if ef:
        endt = max(sorted(ef, key=nkey), key=lambda x: ef[x])
        path = [endt]
        while pred[path[-1]]:
            path.append(pred[path[-1]])
        path.reverse()
        cp_len = ef[endt]
    else:
        path, cp_len = [], 0.0
    return {
        "start": start, "end": done, "lane": lane,
        "build_min": max(done.values()) if done else 0.0,
        "peak_width": peak,
        "critical_path": path,
        "critical_path_min": cp_len,
    }


def schedule_report(plan: Plan, args) -> dict:
    graph = parse_taskgraph(plan)
    times, source = effective_times(plan, graph, args)
    cap = args.cap
    sim = simulate(times, graph, cap)
    predict = _predict()
    coef = predict.load_coef(getattr(args, "coef", None))
    tail = args.tail_min if getattr(args, "tail_min", None) is not None else float(coef.get("schedule", {}).get("tail_min", 3.5))
    target = args.target_min if getattr(args, "target_min", None) is not None else plan.header_target()
    total = sim["build_min"] + tail
    sim.update({
        "graph": graph, "times": times, "source": source, "tail_min": tail,
        "total_min": total, "target_min": target,
        "target_met": None if target is None else total <= target + 1e-9,
        "cap": cap,
    })
    return sim


def summary_line(rep: dict) -> str:
    path = " → ".join(rep["critical_path"]) or "-"
    line = (f"critical path: {path} ({rep['critical_path_min']:.1f} min) · peak width {rep['peak_width']} · "
            f"predicted build {rep['build_min']:.1f} min · predicted total ≈ {rep['total_min']:.1f} min")
    if rep["target_min"] is not None:
        line += " (target ✓)" if rep["target_met"] else f" (target ✗ {rep['target_min']:.1f})"
    return line


def gantt_block(plan: Plan, rep: dict) -> list[str]:
    lines = ["```mermaid", "%% schedule", "gantt", "  title Predicted schedule (mm:ss)",
             "  dateFormat X", "  axisFormat %M:%S"]
    by_lane: dict[int, list[str]] = {}
    for t in sorted(rep["start"], key=lambda x: (rep["lane"][x], rep["start"][x], nkey(x))):
        by_lane.setdefault(rep["lane"][t], []).append(t)
    for ln in sorted(by_lane):
        lines.append(f"  section lane {ln}")
        for t in by_lane[ln]:
            task = plan.by_id.get(t)
            title = re.sub(r"[:;#,]", " ", task.title if task else "").strip()
            label = f"{t} {title}".strip()[:40]
            s = int(round(rep["start"][t] * 60))
            d = max(1, int(round(rep["times"][t] * 60)))
            lines.append(f"  {label} :{t.lower()}, {s}, {d}s")
    lines.append("```")
    return lines


def insert_schedule(plan: Plan, rep: dict) -> None:
    new = gantt_block(plan, rep) + ["", summary_line(rep)]
    old = None
    for b in plan.mermaid_blocks():
        if any(re.match(r"^\s*%%\s*schedule\b", ln) for ln in b.content):
            old = b
            break
    if old is not None:
        s, e = old.start, old.end + 1
        k = e
        while k < len(plan.lines) and not plan.lines[k].strip():
            k += 1
        if k < len(plan.lines) and plan.lines[k].startswith("critical path:"):
            e = k + 1
        plan.lines[s:e] = new
    else:
        blocks = find_taskgraph_blocks(plan)
        if not blocks:
            raise PlanError("no '%% taskgraph' block found in plan")
        at = blocks[-1][0].end + 1
        plan.lines[at:at] = [""] + new
    if plan.path is None:
        return
    plan.path.write_bytes(plan.to_text().encode("utf-8"))


# --------------------------------------------------------------------------
# Signatures and stubs
# --------------------------------------------------------------------------

def parse_signature(item: str) -> dict | None:
    s = strip_ticks(item)
    s = re.sub(r"\s+\((T\d+[a-z]*(?:\s*[,/]\s*T\d+[a-z]*)*)\)\s*$", "", s)
    m = re.match(r"^([A-Za-z_][\w.]*)\s*\(", s)
    if not m:
        return None
    depth, close = 0, None
    for i in range(m.end() - 1, len(s)):
        if s[i] in "([{":
            depth += 1
        elif s[i] in ")]}":
            depth -= 1
            if depth == 0:
                close = i
                break
    if close is None:
        return None
    args = s[m.end():close].strip()
    rest = s[close + 1:].strip()
    ret = None
    if rest.startswith("->"):
        ret = strip_ticks(rest[2:]).rstrip(".;,").strip() or None
    segs = m.group(1).split(".")
    member = segs[-1]
    cls, mod = None, segs[:-1]
    if len(segs) >= 2 and segs[-2][:1].isupper():
        cls, mod = segs[-2], segs[:-2]
    elif member[:1].isupper():
        cls, member, mod = member, "__init__", segs[:-1]
    return {"name": m.group(1), "args": args, "ret": ret, "module": mod, "cls": cls, "member": member, "item": s}


def param_names(args: str) -> list[str]:
    names = []
    for p in split_top_level(args):
        p = p.strip()
        if p in ("/", "*"):
            continue
        p = p.lstrip("*")
        names.append(re.split(r"[:=\s]", p, 1)[0])
    return names


def resolve_module(prefix: list[str], owned: list[str]) -> tuple[str | None, str | None]:
    """Return (relative path, warning)."""
    if not prefix:
        if len(owned) == 1:
            return owned[0], None
        non_init = [o for o in owned if not o.endswith("__init__.py")]
        if len(non_init) == 1:
            return non_init[0], None
        return None, "cannot tell which owned file holds it (name a module in the Produces line)"
    p = "/".join(prefix)
    cands = [o for o in owned if o[:-3] == p or o[:-3].endswith("/" + p)]
    if len(cands) == 1:
        return cands[0], None
    stem = prefix[-1]
    cands = [o for o in owned if o.rsplit("/", 1)[-1][:-3] == stem]
    if len(cands) == 1:
        return cands[0], None
    return p + ".py", f"module {'.'.join(prefix)!r} is not in the task's Owns; using {p}.py"


def _doc(text: str, indent: str) -> str:
    text = text.replace("\\", "\\\\").replace('"""', "'''")
    return f'{indent}"""{text}"""'


def _def_source(sig: dict, indent: str, tid: str, contract: str, is_method: bool) -> str:
    args = sig["args"]
    if is_method:
        first = param_names(args)[:1]
        if not first or first[0] not in ("self", "cls"):
            args = "self" + (", " + args if args else "")
    ret = f" -> {sig['ret']}" if sig["ret"] else ""
    doc = f"Contract: {contract}" if contract else f"Contract: see plan task {tid}."
    body = f'{indent}def {sig["member"]}({args}){ret}:\n{_doc(doc, indent + "    ")}\n{indent}    raise NotImplementedError("{tid}")\n'
    return body


def build_stub_defs(task: Task, warnings: list[str]):
    """Yield (relative path, sig, source-for-def, contract) for each Produces signature."""
    out = []
    for item in task.produces:
        sig = parse_signature(item)
        if sig is None:
            continue
        path, warn = resolve_module(sig["module"], task.owned_sources)
        if warn:
            warnings.append(f"{task.id}: {sig['name']}: {warn}")
        if path is None:
            continue
        for attempt in (sig, dict(sig, ret=None)):
            try:
                compile("from __future__ import annotations\n" + _def_source(attempt, "", task.id, "", False), "<stub>", "exec")
                sig = attempt
                break
            except SyntaxError:
                sig = None
        if sig is None:
            warnings.append(f"{task.id}: cannot parse signature {item!r}; skipped")
            continue
        out.append((path, sig))
    return out


def render_module(path: str, entries: list[tuple[Task, dict]], warnings: list[str]) -> str:
    funcs: list[tuple[Task, dict]] = []
    classes: dict[str, list[tuple[Task, dict]]] = {}
    seen = set()
    for task, sig in entries:
        key = (sig["cls"], sig["member"])
        if key in seen:
            warnings.append(f"{path}: duplicate Produces for {sig['name']} ({task.id}); kept the first")
            continue
        seen.add(key)
        if sig["cls"]:
            classes.setdefault(sig["cls"], []).append((task, sig))
        else:
            funcs.append((task, sig))
    names = [s["member"] for _, s in funcs] + list(classes)
    out = ['"""Generated interface stubs (plan_tools.py stubs). The stub is the contract:',
           'do not change a signature without a coordinator ruling."""',
           "from __future__ import annotations", "",
           "__all__ = [" + ", ".join(json.dumps(n) for n in names) + "]", ""]
    for task, sig in funcs:
        out.append("")
        out.append(_def_source(sig, "", task.id, task.contract_text, False).rstrip("\n"))
        out.append("")
    for cname, items in classes.items():
        first = items[0][0]
        doc = f"Contract: {first.contract_text}" if first.contract_text else f"Contract: see plan task {first.id}."
        out.append("")
        out.append(f"class {cname}:")
        out.append(_doc(doc, "    "))
        for task, sig in items:
            out.append("")
            out.append(_def_source(sig, "    ", task.id, task.contract_text, True).rstrip("\n"))
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def import_check(path: Path) -> str | None:
    name = f"_stubcheck_{abs(hash(str(path)))}"
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    finally:
        sys.modules.pop(name, None)
    return None


def cmd_stubs(args) -> int:
    plan = Plan.load(args.plan)
    root = Path(args.root)
    warnings: list[str] = []
    per_file: dict[str, list[tuple[Task, dict]]] = {}
    for task in plan.tasks:
        for path, sig in build_stub_defs(task, warnings):
            per_file.setdefault(path, []).append((task, sig))
    rc = 0
    for rel in sorted(per_file):
        target = root / rel
        if target.exists():
            print(f"skipped {rel} (exists)")
            continue
        src = render_module(rel, per_file[rel], warnings)
        if args.dry_run:
            print(f"would write {rel}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(src, encoding="utf-8", newline="\n")
        print(f"wrote {rel}")
        err = import_check(target)
        if err:
            print(f"import check failed for {rel}: {err}", file=sys.stderr)
            rc = 1
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if not per_file:
        print("no stubbable Produces lines found")
    return rc


# --------------------------------------------------------------------------
# taskgraph
# --------------------------------------------------------------------------

def mergeable_tasks(plan: Plan, graph, times, args) -> list[dict]:
    predict = _predict()
    models = predict.load_models(getattr(args, "models", None))
    coef = predict.load_coef(getattr(args, "coef", None))
    ctx: dict[str, int | None] = {}
    known_time: dict[str, float | None] = {}
    for tid in graph:
        task = plan.by_id.get(tid)
        if task is None:
            ctx[tid], known_time[tid] = None, None
            continue
        pred = predict.predict_task(task, models, coef) if task.features else None
        ctx[tid] = task.stated_context if task.stated_context is not None else (pred["est_context"] if pred else None)
        known_time[tid] = times.get(tid)
    anc = ancestors(graph)
    cp = set(simulate(times, graph, 1000)["critical_path"])
    res = []
    for tid in graph:
        reasons = []
        c, tm = ctx[tid], known_time[tid]
        if c is not None and c - IMPLEMENTER_PREFIX < MERGE_MIN_VARIABLE:
            reasons.append(f"variable context {(c - IMPLEMENTER_PREFIX) / 1000:.0f}k < {MERGE_MIN_VARIABLE // 1000}k")
        if tm is not None and tm < MERGE_MIN_MINUTES:
            reasons.append(f"predicted {tm:.1f} min < {MERGE_MIN_MINUTES:.0f} min")
        if not reasons:
            continue
        task = plan.by_id[tid]
        my_dirs = {o.rsplit("/", 1)[0] for o in task.owns if "/" in o}
        cands = []
        for other in graph:
            if other == tid:
                continue
            adjacent = other in graph[tid] or tid in graph[other]
            ot = plan.by_id.get(other)
            same_pkg = bool(ot and my_dirs & {o.rsplit("/", 1)[0] for o in ot.owns if "/" in o})
            if not (adjacent or same_pkg):
                continue
            independent = other not in anc[tid] and tid not in anc[other]
            if independent and tid in cp and other in cp:
                continue
            merged = (c or IMPLEMENTER_PREFIX) + max(0, (ctx[other] or IMPLEMENTER_PREFIX) - IMPLEMENTER_PREFIX)
            if merged > CTX_CEILING:
                continue
            cands.append((0 if adjacent else 1, merged, nkey(other), other))
        cands.sort()
        res.append({"task": tid, "reasons": reasons, "merge_with": cands[0][3] if cands else None})
    return res


def cmd_taskgraph(args) -> int:
    plan = Plan.load(args.plan)
    graph = parse_taskgraph(plan)
    seams = seams_of(graph)
    times, _ = effective_times(plan, graph, args)
    merges = mergeable_tasks(plan, graph, times, args)
    if args.format == "full":
        print(json.dumps({"graph": graph, "seams": seams, "mergeable": merges}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(graph, ensure_ascii=False, indent=2))
        for s in seams:
            print(f"seam {s}", file=sys.stderr)
        for m in merges:
            to = f"merge with {m['merge_with']}" if m["merge_with"] else "no safe merge partner"
            print(f"warning: mergeable {m['task']} ({'; '.join(m['reasons'])}); {to}", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------
# schedule
# --------------------------------------------------------------------------

def cmd_schedule(args) -> int:
    plan = Plan.load(args.plan)
    rep = schedule_report(plan, args)
    if args.insert:
        insert_schedule(plan, rep)
    if args.json:
        out = {k: rep[k] for k in ("critical_path", "critical_path_min", "peak_width", "build_min", "tail_min",
                                   "total_min", "target_min", "target_met", "cap")}
        out["tasks"] = {t: {"min": round(rep["times"][t], 3), "start": round(rep["start"][t], 3),
                            "end": round(rep["end"][t], 3), "lane": rep["lane"][t], "source": rep["source"][t]}
                        for t in rep["times"]}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(summary_line(rep))
        for t in sorted(rep["start"], key=lambda x: (rep["start"][x], nkey(x))):
            print(f"  {t}: lane {rep['lane'][t]}, {rep['start'][t]:.1f} to {rep['end'][t]:.1f} min ({rep['source'][t]})")
        if args.insert:
            print(f"inserted schedule into {args.plan}")
    return 0


# --------------------------------------------------------------------------
# lint
# --------------------------------------------------------------------------

PLACEHOLDERS = [
    (r"\bTBD\b", "TBD"),
    (r"\bTODO\b", "TODO"),
    (r"handle edge cases", "'handle edge cases'"),
    (r"add (?:appropriate )?error handling", "'add error handling'"),
    (r"similar to task\s+\w+", "'similar to Task N'"),
    (r"tests? for the above", "'tests for the above'"),
    (r"\bfill in later\b|\bto be decided\b", "deferred detail"),
]
DIAGRAM_TYPES = ("flowchart", "graph", "sequencediagram", "statediagram", "statediagram-v2", "gantt", "classdiagram",
                 "erdiagram", "journey", "pie", "mindmap", "timeline", "gitgraph", "quadrantchart", "requirementdiagram")
SPEC_SKIP = {"overview", "introduction", "background", "goals", "non-goals", "glossary", "contents",
             "table of contents", "references", "open questions", "appendix", "summary", "status"}


def check_diagram(block: FenceBlock) -> str | None:
    lines = [ln for ln in block.content if ln.strip() and not ln.strip().startswith("%%")]
    if not lines:
        return "empty mermaid block"
    first = lines[0].strip().split()[0].lower()
    if first not in DIAGRAM_TYPES:
        return f"unknown diagram type {lines[0].strip().split()[0]!r}"
    if first in ("flowchart", "graph"):
        subs = sum(1 for ln in lines if ln.strip().lower().startswith("subgraph"))
        ends = sum(1 for ln in lines if ln.strip().lower() == "end")
        if subs != ends:
            return "unbalanced subgraph/end"
    body = "\n".join(lines)
    body = re.sub(r'"[^"\n]*"', "", body)
    body = re.sub(r"<[^>\n]*>", "", body)
    for o, c in (("[", "]"), ("{", "}")):
        if body.count(o) != body.count(c):
            return f"unbalanced {o}{c}"
    if first in ("flowchart", "graph") and body.count("(") != body.count(")"):
        return "unbalanced ()"
    return None


def sig_key(sig: dict) -> str:
    return f"{sig['cls']}.{sig['member']}" if sig["cls"] else sig["member"]


def lint_plan(plan: Plan, args) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    ids = [t.id for t in plan.tasks]
    for tid in sorted({i for i in ids if ids.count(i) > 1}, key=nkey):
        issues.append(f"duplicate task heading {tid}")
    if not plan.tasks:
        issues.append("no task headings (### Tn ...) found")

    # placeholders (outside code fences)
    for i, ln in enumerate(plan.lines):
        if plan.fenced[i]:
            continue
        for pat, label in PLACEHOLDERS:
            if re.search(pat, ln, re.I):
                issues.append(f"placeholder {label} at line {i + 1}")

    for t in plan.tasks:
        if not t.has_features and t.stated_time is None:
            warnings.append(f"WARNING: {t.id} has no features (Components, LOC owned, Tests) and no Est. time; "
                            "the predictor will use defaults")

    # Owns present, parallel tasks do not share files
    graph = None
    try:
        graph = parse_taskgraph(plan)
    except PlanError as exc:
        issues.append(f"taskgraph: {exc}")
    for t in plan.tasks:
        if not t.owns:
            issues.append(f"{t.id}: no **Owns:** line")
    if graph:
        anc = ancestors(graph)
        for a_i, a in enumerate(plan.tasks):
            for b in plan.tasks[a_i + 1:]:
                if a.id in graph and b.id in graph and a.id not in anc[b.id] and b.id not in anc[a.id]:
                    shared = sorted(set(a.owns) & set(b.owns))
                    if shared:
                        issues.append(f"{a.id} and {b.id} can run in parallel but both own {', '.join(shared)}")

    # Consumes / Produces consistency
    produced: dict[str, list[tuple[str, dict]]] = {}
    for t in plan.tasks:
        for item in t.produces:
            sig = parse_signature(item)
            if sig:
                produced.setdefault(sig_key(sig), []).append((t.id, sig))
    for t in plan.tasks:
        for item in t.consumes:
            sig = parse_signature(item)
            if not sig:
                continue
            ref = re.search(r"\s+\((T\d+[a-z]*(?:\s*[,/]\s*T\d+[a-z]*)*)\)\s*$", strip_ticks(item))
            refs = re.findall(TASK_ID, ref.group(1)) if ref else []
            cands = produced.get(sig_key(sig), [])
            if refs:
                cands = [c for c in cands if c[0] in refs]
            if not cands:
                where = f" from {'/'.join(refs)}" if refs else ""
                issues.append(f"{t.id} consumes {sig['name']}{where}, but no Produces line defines it")
                continue
            ok = False
            for pid, psig in cands:
                same_params = param_names(psig["args"]) == param_names(sig["args"])
                same_ret = not (psig["ret"] and sig["ret"]) or re.sub(r"\s+", "", psig["ret"]) == re.sub(r"\s+", "", sig["ret"])
                if same_params and same_ret:
                    ok = True
                    break
            if not ok:
                pid, psig = cands[0]
                issues.append(f"{t.id} consumes {sig['name']}({sig['args']}) but {pid} produces "
                              f"{psig['name']}({psig['args']})" + (f" -> {psig['ret']}" if psig["ret"] else ""))

    # diagrams
    for b in plan.mermaid_blocks():
        err = check_diagram(b)
        if err:
            issues.append(f"mermaid block at line {b.start + 1}: {err}")

    # size caps
    max_chars = getattr(args, "max_chars", DEFAULT_MAX_CHARS)
    if len(plan.text) > max_chars:
        issues.append(f"plan is {len(plan.text)} chars, over the {max_chars} cap")
    for t in plan.tasks:
        if t.stated_context is not None and t.stated_context > CTX_CEILING:
            issues.append(f"{t.id}: Est. context {t.stated_context // 1000}k is over the {CTX_CEILING // 1000}k ceiling; split it")

    # mergeable / over cap, and the time-target warning
    miss: str | None = None
    if graph is not None and not find_cycle(graph):
        try:
            times, _ = effective_times(plan, graph, args)
        except PlanError as exc:
            issues.append(str(exc))
            times = None
        if times is not None:
            for t in sorted(times, key=nkey):
                if times[t] > args.max_task_min + 1e-9:
                    issues.append(f"{t}: predicted {times[t]:.1f} min is over the {args.max_task_min:.0f}-min cap; split it along its components")
            for m in mergeable_tasks(plan, graph, times, args):
                to = f"merge with {m['merge_with']}" if m["merge_with"] else "no safe merge partner"
                issues.append(f"{m['task']} is mergeable ({'; '.join(m['reasons'])}); {to}")
            rep = schedule_report(plan, args)
            if rep["target_min"] is not None and not rep["target_met"]:
                miss = (f"MISSED TARGET: predicted {rep['total_min']:.1f} min vs target {rep['target_min']:.1f} min "
                        f"— critical path {' → '.join(rep['critical_path'])}")
    if miss:
        warnings.append(miss)

    # SPEC coverage
    if getattr(args, "spec", None):
        sp = Path(args.spec)
        if not sp.is_file():
            issues.append(f"spec not found: {args.spec}")
        else:
            stext = sp.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
            sflags, _ = scan_fences(stext.split("\n"))
            plan_l = plan.text.lower()
            for ln, fenced in zip(stext.split("\n"), sflags):
                m = None if fenced else re.match(r"^#{2,3}\s+(.*?)\s*#*$", ln)
                if not m:
                    continue
                raw = m.group(1)
                nm = re.match(r"^(?:§\s*)?(\d+(?:\.\d+)*)\.?\s+(.*)$", raw)
                num, title = (nm.group(1), nm.group(2)) if nm else (None, raw)
                title = title.strip().strip("`")
                if title.lower() in SPEC_SKIP:
                    continue
                covered = title.lower() in plan_l
                if not covered and num:
                    covered = bool(re.search(rf"(?:§|section\s+|sec\.\s*)\s*{re.escape(num)}\b", plan_l))
                if not covered:
                    issues.append(f"SPEC section {raw!r} has no task")
    return issues, warnings


def cmd_lint(args) -> int:
    plan = Plan.load(args.plan)
    issues, warnings = lint_plan(plan, args)
    for w in warnings:
        print(w)
    for i in issues:
        print(f"ISSUE: {i}")
    if issues:
        print(f"lint: {len(issues)} issue(s)")
        return 1
    print("lint: ok")
    return 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def add_predictor_args(p):
    p.add_argument("--models", help="models.json (default: config/models.json)")
    p.add_argument("--coef", help="predictor.json (default: config/predictor.json)")
    p.add_argument("--stated", action="store_true",
                   help="use stated Est. time lines even where features exist (default: features win)")


def build_parser():
    ap = argparse.ArgumentParser(prog="plan_tools.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("taskgraph", help="print task -> dependencies JSON; seams and mergeable warnings on stderr")
    p.add_argument("--plan", required=True)
    p.add_argument("--format", choices=("graph", "full"), default="graph",
                   help="full: {graph, seams, mergeable} on stdout")
    add_predictor_args(p)
    p.set_defaults(func=cmd_taskgraph)

    p = sub.add_parser("stubs", help="write interface stubs from Produces lines")
    p.add_argument("--plan", required=True)
    p.add_argument("--root", default=".")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_stubs)

    p = sub.add_parser("schedule", help="simulate the ready queue; optionally insert a Gantt into the plan")
    p.add_argument("--plan", required=True)
    p.add_argument("--cap", type=int, default=DEFAULT_CAP)
    p.add_argument("--target-min", type=float, default=None)
    p.add_argument("--tail-min", type=float, default=None, help="minutes after the build (default from predictor.json)")
    p.add_argument("--insert", action="store_true")
    p.add_argument("--json", action="store_true")
    add_predictor_args(p)
    p.set_defaults(func=cmd_schedule)

    p = sub.add_parser("lint", help="check the plan; MISSED TARGET is a warning (exit 0)")
    p.add_argument("--plan", required=True)
    p.add_argument("--spec")
    p.add_argument("--cap", type=int, default=DEFAULT_CAP)
    p.add_argument("--target-min", type=float, default=None)
    p.add_argument("--tail-min", type=float, default=None)
    p.add_argument("--max-task-min", type=float, default=DEFAULT_MAX_TASK_MIN)
    p.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    add_predictor_args(p)
    p.set_defaults(func=cmd_lint)

    for name in REVIEW_COMMANDS:
        sub.add_parser(name, help="implemented in pt_review.py")
    return ap


def _utf8_streams():
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            try:
                s.reconfigure(encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass


def main(argv=None):
    """Dispatch. adapter/packet/contract go to pt_review.main(argv) with the subcommand name kept in argv."""
    argv = list(sys.argv[1:] if argv is None else argv)
    _utf8_streams()
    if argv and argv[0] in REVIEW_COMMANDS:
        # pt_review.main receives the FULL argv, including the subcommand name as argv[0].
        if str(SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPT_DIR))
        import pt_review
        return pt_review.main(argv)
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PlanError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
