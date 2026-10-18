#!/usr/bin/env python3
"""Review-side plan tools: adapter, packet, contract.

    pt_review.py adapter  --plan PLAN.md [--root .] [--out .superlite/probes/adapter.py]
    pt_review.py packet   --plan PLAN.md [--root .] [--log F] [--probes DIR] [--out F]
                          [--max-tokens 20000] [--tests F] [--base REF]
    pt_review.py contract --plan PLAN.md [--root .] [--seam Ta,Tb] [--log F]
                          [--timeout 300]

`packet` reads probe failures from `.superlite/probes/probe-results.json` and the test
summary from `.superlite/test-summary.json` (written by run_tests.py) by default. A
`contract --seam` run logs to `.superlite/incidents.jsonl` by default: each mismatch is an
`exception` incident, a pass is a `verified` entry.

`plan_tools.py` dispatches `adapter|packet|contract` to `main(argv)` here; the module
also runs standalone. Stdlib only. Incidents are read straight from the JSONL format
(plan section 6), never through incident.py.

Plan conventions read here (per task section `### Tn ...`):
  **Owns:** a.py, tests/test_a.py          **Consumes:** f(x) -> y (T1)
  **Produces:** pkg.mod.f(a: int, b=1) -> str  ·  Class.method(ref: str) -> list[str]
  **Probe entry:** call=pkg.mod.fn · run=python -m pkg · serve=pkg.server.create_server(Workbook())
  Data contract lines (any line, anchored at the start, bullets allowed):
      POST /api/cells {"ref":"A1"} -> 200 {cells: dict, note?: str}
  Review Focus section lines:  - <package>: deep, numeric, encoding, state
  Task graph: a `%% taskgraph` block of `Tn --> Tm` edges (Tn produces for Tm).
"""
from __future__ import annotations

import argparse
import ast
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _pyrun as pyrun  # noqa: E402

CATEGORIES = ("deep", "numeric", "encoding", "protocol", "file", "state")
CHARS_PER_TOKEN = 1.9  # 20k tokens ~ 38k chars (plan section 5)
RESOLVED = {"fixed", "resolved", "closed", "wontfix", "accepted"}
PASS_STATUSES = {"pass", "passed", "ok"}
SKIP_DIRS = {".git", ".superlite", ".venv", "venv", "node_modules", "__pycache__", "tests",
             "test", "build", "dist", ".pytest_cache"}
TASK_RE = re.compile(r"^#{2,4}\s+(T\d+[a-z]?)\b(.*)$")
LABEL_RE = re.compile(r"^\s*(?:[-*]\s+)?\*\*([A-Za-z][A-Za-z .]*?):?\*\*:?\s*(.*)$")
EDGE_RE = re.compile(r"\b(T\d+[a-z]?)(?:\[[^\]]*\])?\s*-->\s*(?:\|[^|]*\|\s*)?(T\d+[a-z]?)\b")
HTTP_LINE_RE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S*)\s*(.*)$")
TEST_PATH_RE = re.compile(r"(^|/)(tests?/|test_[^/]*$|[^/]*_test\.py$)")
CONSUMER_EXT = {".html", ".htm", ".js", ".mjs", ".ts", ".jsx", ".tsx", ".vue", ".py"}


class ToolError(Exception):
    """A usage or input error; main() prints it and returns 2."""


# --------------------------------------------------------------------------- plan parsing


@dataclass
class Task:
    id: str
    title: str
    start: int
    end: int
    fields: dict[str, list[str]] = field(default_factory=dict)  # label -> value lines

    def owns(self) -> list[str]:
        out: list[str] = []
        for line in self.fields.get("owns", []):
            for tok in split_top(line, ",·"):
                tok = re.sub(r"\s*\(.*\)\s*$", "", tok.strip().strip("`").strip())
                if tok and " " not in tok and ("." in tok or "/" in tok):
                    out.extend(expand_braces(tok))
        return out

    def produces(self) -> list[str]:
        items: list[str] = []
        for line in self.fields.get("produces", []):
            line = re.sub(r"^\s*[-*]\s+", "", line)
            items.extend(p.strip() for p in line.split("·") if p.strip())
        return items

    def consumes_ids(self) -> set[str]:
        return set(re.findall(r"\((T\d+[a-z]?)\)", " ".join(self.fields.get("consumes", []))))


@dataclass
class Plan:
    path: Path
    lines: list[str]
    tasks: dict[str, Task]
    edges: list[tuple[str, str]]
    headings: list[tuple[int, int, str, int]]  # (line idx, level, title, end idx)
    probe_entries: list[str]

    def section_text(self, start: int, end: int) -> str:
        return "\n".join(self.lines[start:end])

    def review_focus(self) -> str:
        for idx, _lvl, title, end in self.headings:
            if "review focus" in title.lower():
                return self.section_text(idx + 1, end).strip()
        return ""


def split_top(s: str, seps: str) -> list[str]:
    out, depth, cur = [], 0, []
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if ch in seps and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [p for p in out if p.strip()]


def expand_braces(s: str) -> list[str]:
    m = re.search(r"\{([^{}]*)\}", s)
    if not m:
        return [s]
    out: list[str] = []
    for alt in m.group(1).split(","):
        out.extend(expand_braces(s[: m.start()] + alt.strip() + s[m.end():]))
    return out


def parse_plan(path: str | Path) -> Plan:
    p = Path(path)
    if not p.is_file():
        raise ToolError(f"plan not found: {p}")
    lines = p.read_text(encoding="utf-8").splitlines()
    fence_marker = ""
    fence_id = [0] * len(lines)
    fid = 0
    heads: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines):
        m = re.match(r"^\s*(`{3,}|~{3,})", line)
        if m:
            if not fence_marker:
                fence_marker = m.group(1)
                fid += 1
                fence_id[i] = fid
                continue
            if line.strip().startswith(fence_marker[0] * len(fence_marker)) and set(line.strip()) <= {fence_marker[0]}:
                fence_id[i] = fid
                fence_marker = ""
                continue
        if fence_marker:
            fence_id[i] = fid
            continue
        hm = re.match(r"^(#{1,6})\s+(.*)$", line)
        if hm:
            heads.append((i, len(hm.group(1)), hm.group(2).strip()))
    headings = []
    for n, (i, lvl, title) in enumerate(heads):
        end = len(lines)
        for j, lvl2, _t in heads[n + 1:]:
            if lvl2 <= lvl:
                end = j
                break
        headings.append((i, lvl, title, end))

    tasks: dict[str, Task] = {}
    for i, lvl, title, end in headings:
        m = TASK_RE.match(lines[i])
        if m:
            tasks[m.group(1)] = Task(m.group(1), title, i, end)

    probe_entries: list[str] = []
    for tid, t in tasks.items():
        _collect_fields(lines, fence_id, t.start + 1, t.end, t.fields)
    plan_fields: dict[str, list[str]] = {}
    _collect_fields(lines, fence_id, 0, len(lines), plan_fields)
    probe_entries = [v.strip().strip("`").strip() for v in plan_fields.get("probe entry", []) if v.strip()]

    edges: list[tuple[str, str]] = []
    for i, line in enumerate(lines):
        if "%% taskgraph" in line:
            j = i + 1
            while j < len(lines) and fence_id[j] == fence_id[i]:
                m = EDGE_RE.search(lines[j])
                if m:
                    edges.append((m.group(1), m.group(2)))
                j += 1
    return Plan(p, lines, tasks, edges, headings, probe_entries)


def _collect_fields(lines: list[str], fence_id: list[int], start: int, end: int,
                    out: dict[str, list[str]]) -> None:
    i = start
    while i < end:
        if fence_id[i]:
            i += 1
            continue
        m = LABEL_RE.match(lines[i])
        if not m:
            i += 1
            continue
        label = m.group(1).strip().lower()
        vals = [m.group(2).strip()] if m.group(2).strip() else []
        j = i + 1
        while j < end and not fence_id[j] and lines[j].strip() and not LABEL_RE.match(lines[j]) \
                and not lines[j].startswith("#") and re.match(r"^(\s+|[-*]\s+)", lines[j]):
            vals.append(lines[j].strip())
            j += 1
        out.setdefault(label, []).extend(vals)
        i = j


# --------------------------------------------------------------------------- Produces signatures


@dataclass
class Planned:
    task: str
    raw: str
    qual: str
    args_src: str | None  # None => "(...)": params unchecked
    ret: str | None
    plan_line: int = 0

    @property
    def parts(self) -> list[str]:
        return self.qual.split(".")


def parse_sig(item: str) -> tuple[str, str | None, str | None] | None:
    item = item.strip().strip("`").strip()
    m = re.match(r"^([A-Za-z_][\w.]*)\s*\(", item)
    if not m:
        return None
    depth, end = 0, -1
    for j in range(m.end() - 1, len(item)):
        c = item[j]
        depth += (c in "([{") - (c in ")]}")
        if depth == 0:
            end = j
            break
    if end < 0:
        return None
    args = item[m.end():end].strip()
    rest = item[end + 1:].strip()
    ret = None
    if rest:
        if not rest.startswith("->"):
            return None
        ret = rest[2:].strip().strip("`").strip()
        try:
            ast.parse(ret, mode="eval")
        except SyntaxError:
            ret = None
    if args in ("...", "…"):
        return m.group(1), None, ret
    try:
        ast.parse(f"def _f({args}): pass")
    except SyntaxError:
        return None
    return m.group(1), args, ret


def planned_items(plan: Plan, task_ids: list[str] | None = None) -> list[Planned]:
    out: list[Planned] = []
    for tid, t in plan.tasks.items():
        if task_ids is not None and tid not in task_ids:
            continue
        for item in t.produces():
            parsed = parse_sig(item)
            if parsed:
                out.append(Planned(tid, item, parsed[0], parsed[1], parsed[2], t.start + 1))
    return out


def _params_from_src(args_src: str) -> list[dict]:
    fn = ast.parse(f"def _f({args_src}): pass").body[0]
    a = fn.args  # type: ignore[attr-defined]
    out: list[dict] = []

    def add(arg: ast.arg, kind: str, default: ast.expr | None) -> None:
        out.append({"name": arg.arg, "kind": kind,
                    "default": ast.unparse(default) if default is not None else None,
                    "ann": ast.unparse(arg.annotation) if arg.annotation else None})

    pos = list(a.posonlyargs) + list(a.args)
    defaults = [None] * (len(pos) - len(a.defaults)) + list(a.defaults)
    for n, (arg, d) in enumerate(zip(pos, defaults)):
        add(arg, "POSITIONAL_ONLY" if n < len(a.posonlyargs) else "POSITIONAL_OR_KEYWORD", d)
    if a.vararg:
        add(a.vararg, "VAR_POSITIONAL", None)
    for arg, d in zip(a.kwonlyargs, a.kw_defaults):
        add(arg, "KEYWORD_ONLY", d)
    if a.kwarg:
        add(a.kwarg, "VAR_KEYWORD", None)
    return out


class _Norm(ast.NodeTransformer):
    def visit_Attribute(self, node: ast.Attribute):  # typing.List -> List, http.server.X -> X
        return ast.Name(id=node.attr, ctx=ast.Load())

    def visit_Constant(self, node: ast.Constant):  # forward-ref strings
        if isinstance(node.value, str):
            try:
                return self.visit(ast.parse(node.value, mode="eval").body)
            except SyntaxError:
                return node
        return node


def norm_ann(s: str | None) -> str | None:
    if s is None:
        return None
    try:
        return ast.unparse(_Norm().visit(ast.parse(s, mode="eval")))
    except SyntaxError:
        return s.strip()


def compare_sig(p: Planned, real: dict) -> list[str]:
    """Differences between a planned signature and the real one (empty = match)."""
    if not real.get("ok"):
        return [f"{p.qual}: {real.get('error', 'cannot read the real signature')}"]
    msgs: list[str] = []
    if p.args_src is not None:
        want = _params_from_src(p.args_src)
        have = real["params"]
        wn, hn = [x["name"] for x in want], [x["name"] for x in have]
        for n in wn:
            if n not in hn:
                msgs.append(f"{p.qual}: missing parameter '{n}' (planned {p.raw})")
        for n in hn:
            if n not in wn:
                msgs.append(f"{p.qual}: extra parameter '{n}' not in the plan")
        if not msgs and wn != hn:
            msgs.append(f"{p.qual}: parameter order differs, planned ({', '.join(wn)}) real ({', '.join(hn)})")
        if not msgs:
            for w, h in zip(want, have):
                if w["kind"] != h["kind"]:
                    msgs.append(f"{p.qual}: parameter '{w['name']}' is {h['kind'].lower()}, planned {w['kind'].lower()}")
                if w["default"] is not None:
                    if not h["has_default"]:
                        msgs.append(f"{p.qual}: parameter '{w['name']}' lost its default {w['default']}")
                    elif not _same_default(w["default"], h["default"]):
                        msgs.append(f"{p.qual}: parameter '{w['name']}' default is {h['default']}, planned {w['default']}")
                wa, ha = norm_ann(w["ann"]), norm_ann(h["ann"])
                if wa and ha and wa != ha:
                    msgs.append(f"{p.qual}: parameter '{w['name']}' annotated {ha}, planned {wa}")
    wr, hr = norm_ann(p.ret), norm_ann(real.get("returns"))
    if wr and hr and wr != hr:
        msgs.append(f"{p.qual}: returns {hr}, planned {wr}")
    return msgs


def _same_default(planned: str, real_repr: str | None) -> bool:
    try:
        return repr(ast.literal_eval(planned)) == real_repr
    except (ValueError, SyntaxError):
        return planned.strip() == (real_repr or "").strip()


_INTROSPECT = r'''
import sys, json, importlib, inspect
def ann(a):
    if a is inspect.Parameter.empty:
        return None
    if isinstance(a, str):
        return a
    if isinstance(a, type):
        return a.__qualname__
    return str(a)
out = []
for mod_name, chain in json.loads(sys.argv[1]):
    r = {"ok": False}
    try:
        obj = importlib.import_module(mod_name)
        parent = None
        for i, name in enumerate(chain):
            parent = obj
            try:
                obj = getattr(obj, name)
            except AttributeError:
                raise AttributeError("%s not found in %s" % (".".join(chain[:i + 1]), mod_name))
        sig = inspect.signature(obj)
        params = list(sig.parameters.values())
        if inspect.isclass(parent) and params and params[0].name in ("self", "cls"):
            if not isinstance(inspect.getattr_static(parent, chain[-1]), staticmethod):
                params = params[1:]
        r = {"ok": True, "params": [
            {"name": p.name, "kind": p.kind.name, "has_default": p.default is not p.empty,
             "default": repr(p.default) if p.default is not p.empty else None, "ann": ann(p.annotation)}
            for p in params], "returns": ann(sig.return_annotation), "file": None, "line": 0}
        try:
            r["file"] = inspect.getsourcefile(obj)
            r["line"] = inspect.getsourcelines(obj)[1]
        except (TypeError, OSError):
            pass
    except BaseException as e:
        r = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
    out.append(r)
print("@@SIG@@" + json.dumps(out))
'''


def project_env(root: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(root / "src"), str(root)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def module_name(root: Path, file: Path) -> str:
    file = file.resolve()
    for base in (root / "src", root):
        try:
            rel = file.relative_to(base.resolve())
        except ValueError:
            continue
        parts = list(rel.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)
    return file.stem


def find_module_file(root: Path, dotted: str) -> Path | None:
    rel = dotted.replace(".", "/")
    for base in (root / "src", root):
        for cand in (base / f"{rel}.py", base / rel / "__init__.py"):
            if cand.is_file():
                return cand
    return None


def _top_level_names(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return set()
    names: set[str] = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            names.update(t.id for t in n.targets if isinstance(t, ast.Name))
    return names


def locate(root: Path, plan: Plan, p: Planned) -> tuple[str, list[str], Path | None]:
    """Return (module, attribute chain, defining file) for a planned item."""
    parts = p.parts
    for k in range(len(parts) - 1, 0, -1):
        f = find_module_file(root, ".".join(parts[:k]))
        if f:
            return module_name(root, f), parts[k:], f
    owned = [root / o for o in plan.tasks[p.task].owns()
             if o.endswith(".py") and not TEST_PATH_RE.search(o)]
    existing = [f for f in owned if f.is_file()]
    for f in existing:
        if parts[0] in _top_level_names(f):
            return module_name(root, f), parts, f
    if existing:
        return module_name(root, existing[0]), parts, existing[0]
    return "", parts, owned[0] if owned else None


def read_real(root: Path, located: list[tuple[str, list[str]]]) -> list[dict]:
    todo = [(m, c) for m, c in located if m]
    results: list[dict] = []
    if todo:
        try:
            proc = subprocess.run([sys.executable, "-c", _INTROSPECT, json.dumps(todo)], cwd=root,
                                  env=project_env(root), capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=60)
            line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("@@SIG@@")), None)
            results = json.loads(line[7:]) if line else \
                [{"ok": False, "error": f"introspection failed: {proc.stderr.strip()[-200:]}"}] * len(todo)
        except subprocess.TimeoutExpired:
            results = [{"ok": False, "error": "introspection timed out"}] * len(todo)
    it = iter(results)
    return [next(it) if m else {"ok": False, "error": "no module found (file missing)"}
            for m, _c in located]


@dataclass
class Mismatch:
    part: int
    file: str
    line: int
    msg: str
    task: str = ""

    def __str__(self) -> str:
        return f"MISMATCH part{self.part} {self.file}:{self.line} - {self.msg}"


def rel_to(root: Path, f: str | Path | None) -> str:
    if not f:
        return "?"
    try:
        return Path(f).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(f).replace("\\", "/")


def check_interfaces(plan: Plan, root: Path, task_ids: list[str] | None) -> tuple[list[Mismatch], int]:
    items = planned_items(plan, task_ids)
    locs = [locate(root, plan, p) for p in items]
    reals = read_real(root, [(m, c) for m, c, _f in locs])
    out: list[Mismatch] = []
    for p, (mod, chain, f), real in zip(items, locs, reals):
        msgs = compare_sig(p, real)
        if msgs:
            file = rel_to(root, real.get("file") or f) if (real.get("file") or f) else \
                rel_to(root, plan.path)
            line = int(real.get("line") or 1) if real.get("file") else (1 if f else p.plan_line)
            for m in msgs:
                out.append(Mismatch(1, file, line, f"{p.task} Produces: {m}", p.task))
    return out, len(items)


# --------------------------------------------------------------------------- data contract (part 2)


@dataclass
class ContractLine:
    method: str
    path: str
    body: object | None
    status: int | None
    shape: object | None  # parsed shape or None
    plan_line: int


@dataclass
class Call:
    file: str
    line: int
    method: str
    path: str
    prefix: bool


def parse_shape(text: str):
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        shape: dict[str, tuple[bool, object]] = {}
        for part in split_top(text[1:-1], ","):
            key, _, typ = part.partition(":")
            key = key.strip().strip("\"'")
            optional = key.endswith("?")
            shape[key.rstrip("?")] = (optional, parse_shape(typ) if typ.strip() else "any")
        return shape
    if "|" in text and not text.startswith(("{", "list[")):
        return ("union", [parse_shape(t) for t in text.split("|")])
    return text.strip("`\"'").lower()


_TYPE_CHECKS = {
    "str": lambda v: isinstance(v, str), "string": lambda v: isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "float": lambda v: isinstance(v, float) or (isinstance(v, int) and not isinstance(v, bool)),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool), "boolean": lambda v: isinstance(v, bool),
    "list": lambda v: isinstance(v, list), "array": lambda v: isinstance(v, list),
    "dict": lambda v: isinstance(v, dict), "object": lambda v: isinstance(v, dict),
    "null": lambda v: v is None, "none": lambda v: v is None, "any": lambda v: True,
}


def check_shape(value, shape, where: str = "$") -> list[str]:
    if isinstance(shape, dict):
        if not isinstance(value, dict):
            return [f"{where} is {type(value).__name__}, expected object"]
        probs: list[str] = []
        for key, (optional, sub) in shape.items():
            if key not in value:
                if not optional:
                    probs.append(f"{where} lacks required key '{key}'")
                continue
            probs.extend(check_shape(value[key], sub, f"{where}.{key}"))
        return probs
    if isinstance(shape, tuple) and shape and shape[0] == "union":
        alts = [check_shape(value, s, where) for s in shape[1]]
        return [] if any(not a for a in alts) else [f"{where} matches none of the allowed types"]
    if isinstance(shape, str):
        m = re.match(r"^(?:list|array)\[(.+)\]$", shape)
        if m:
            if not isinstance(value, list):
                return [f"{where} is {type(value).__name__}, expected list"]
            probs = []
            for n, item in enumerate(value[:20]):
                probs.extend(check_shape(item, parse_shape(m.group(1)), f"{where}[{n}]"))
            return probs
        check = _TYPE_CHECKS.get(shape)
        if check and not check(value):
            return [f"{where} is {type(value).__name__}, expected {shape}"]
    return []


def data_contract(plan: Plan, task_ids: list[str]) -> list[ContractLine]:
    ranges = [(plan.tasks[t].start, plan.tasks[t].end) for t in task_ids if t in plan.tasks]
    ranges += [(i, end) for i, _l, title, end in plan.headings
               if "contract" in title.lower() and not TASK_RE.match(plan.lines[i])]
    seen: set[int] = set()
    out: list[ContractLine] = []
    for s, e in ranges:
        for i in range(s, e):
            if i in seen:
                continue
            seen.add(i)
            raw = re.sub(r"^\s*[-*]\s+", "", plan.lines[i]).strip().strip("`").strip()
            m = HTTP_LINE_RE.match(raw)
            if not m:
                continue
            rest = m.group(3).strip().rstrip("`")
            left, arrow, right = re.split(r"(->|→)", rest, maxsplit=1) if re.search(r"->|→", rest) \
                else (rest, "", "")
            body = None
            if left.strip():
                try:
                    body = json.loads(left.strip())
                except ValueError:
                    body = None
            status, shape = None, None
            sm = re.match(r"^\s*(\d{3})\s*(.*)$", right)
            if sm:
                status = int(sm.group(1))
                if sm.group(2).strip():
                    shape = parse_shape(sm.group(2).strip())
            out.append(ContractLine(m.group(1), m.group(2), body, status, shape, i + 1))
    return out


def _path_clean(p: str) -> tuple[str, bool]:
    prefix = False
    cut = re.search(r"\$\{|\{\{|[?#]", p)
    if cut:
        prefix = cut.group(0) in ("${", "{{")
        p = p[: cut.start()]
    return p, prefix


def scan_calls(root: Path, files: list[str]) -> list[Call]:
    calls: list[Call] = []
    for rel in files:
        f = root / rel
        if f.suffix not in CONSUMER_EXT or TEST_PATH_RE.search(rel) or not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")

        def line_of(pos: int) -> int:
            return text.count("\n", 0, pos) + 1

        for m in re.finditer(r"\bfetch\(\s*([`'\"])(/[^`'\"]*)", text):
            nxt = text.find("fetch(", m.end())
            window = text[m.end(): nxt if nxt != -1 else m.end() + 300][:300]
            mm = re.search(r"method\s*:\s*[`'\"](\w+)", window)
            path, prefix = _path_clean(m.group(2))
            calls.append(Call(rel, line_of(m.start()), (mm.group(1) if mm else "GET").upper(), path, prefix))
        for m in re.finditer(r"\b(?:axios|requests|session|client|http)\.(get|post|put|patch|delete|head)\(\s*"
                             r"f?([`'\"])(?:https?://[^/`'\"]+)?(/[^`'\"]*)", text):
            path, prefix = _path_clean(m.group(3))
            if f.suffix == ".py" and "{" in m.group(3):
                path, prefix = m.group(3).split("{", 1)[0], True
            calls.append(Call(rel, line_of(m.start()), m.group(1).upper(), path, prefix))
        for m in re.finditer(r"\.request\(\s*(['\"])(\w+)\1\s*,\s*f?(['\"])(/[^'\"]*)", text):
            path, prefix = _path_clean(m.group(4))
            calls.append(Call(rel, line_of(m.start()), m.group(2).upper(), path, prefix))
    return calls


def _segments(path: str) -> list[str]:
    return [s for s in path.strip("/").split("/")]


def _is_param(seg: str) -> bool:
    return bool(re.fullmatch(r"\{[^}]*\}|:[\w]+|<[^>]*>", seg))


def call_in_contract(call: Call, contract: list[ContractLine]) -> bool:
    cs = _segments(call.path)
    for c in contract:
        if c.method != call.method:
            continue
        if call.prefix:  # the call path stops at a template literal, e.g. /api/cells/${ref}
            if c.path.startswith(call.path):
                return True
            continue
        ks = _segments(c.path)
        if len(ks) == len(cs) and all(_is_param(k) or k == s for k, s in zip(ks, cs)):
            return True
    return False


_SERVE_SNIPPET = r'''
def _make_server(target, args_src):
    import importlib, inspect
    mod_name, _, fn_name = target.rpartition(".")
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, fn_name)
    def _cap(*a, **k):
        return a, k
    pos, kw = eval("_cap(%s)" % args_src, dict(vars(mod), _cap=_cap)) if args_src is not None else ((), {})
    sig = inspect.signature(fn)
    if "port" in sig.parameters and "port" not in kw:
        kw["port"] = 0
    if args_src is None:
        need = [p.name for p in sig.parameters.values() if p.name != "port"
                and p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
        if need:
            raise RuntimeError("serve factory needs arguments %s; write serve=%s(...) in the Probe entry"
                               % (need, target))
    return fn(*pos, **kw), fn
'''

_SERVER_RUNNER = _SERVE_SNIPPET + r'''
import sys, json, inspect
spec = json.loads(sys.argv[1])
try:
    srv, fn = _make_server(spec["target"], spec["args"])
    host, port = srv.server_address[:2]
    try:
        f, line = inspect.getsourcefile(fn), inspect.getsourcelines(fn)[1]
    except (TypeError, OSError):
        f, line = None, 0
    print("@@READY@@" + json.dumps({"host": host, "port": port, "file": f, "line": line}), flush=True)
    srv.serve_forever()
except BaseException as e:
    print("@@ERR@@%s: %s" % (type(e).__name__, e), flush=True)
    sys.exit(3)
'''


def parse_serve(entry: str) -> tuple[str, str | None]:
    m = re.match(r"^\s*([\w.]+)\s*(?:\((.*)\))?\s*$", entry, re.S)
    if not m:
        raise ToolError(f"bad serve entry: {entry!r}")
    return m.group(1), m.group(2)


def parse_probe_entry(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in text.split("·"):
        key, eq, val = part.strip().partition("=")
        key = key.strip().lower()
        if eq and key in ("call", "run", "serve") and val.strip():
            out[key] = val.strip().strip("`").strip()
    return out


class ServerHandle:
    """A real server in its own process (own PID), port 0; killed by PID in close()."""

    def __init__(self, root: Path, target: str, args: str | None, timeout: float = 20.0):
        self.tmp = tempfile.mkdtemp(prefix="pt_review_")
        self.out_path = Path(self.tmp) / "out.txt"
        self.err_path = Path(self.tmp) / "err.txt"
        self._out = open(self.out_path, "wb")
        self._err = open(self.err_path, "wb")
        self.proc = subprocess.Popen(
            [sys.executable, "-c", _SERVER_RUNNER, json.dumps({"target": target, "args": args})],
            cwd=root, env=project_env(root), stdout=self._out, stderr=self._err, stdin=subprocess.DEVNULL)
        self.info: dict | None = None
        self.error: str | None = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            text = self.out_path.read_text(encoding="utf-8", errors="replace")
            for ln in text.splitlines():
                if ln.startswith("@@READY@@"):
                    self.info = json.loads(ln[9:])
                elif ln.startswith("@@ERR@@"):
                    self.error = ln[7:]
            if self.info or self.error or self.proc.poll() is not None:
                break
            time.sleep(0.05)
        if not self.info and not self.error:
            tail = self.err_path.read_text(encoding="utf-8", errors="replace").strip()[-200:]
            self.error = "server did not start" + (f": {tail}" if tail else "")

    def request(self, method: str, path: str, body) -> tuple[int, bytes]:
        host = self.info["host"] if self.info["host"] not in ("", "0.0.0.0") else "127.0.0.1"
        conn = http.client.HTTPConnection(host, self.info["port"], timeout=10)
        try:
            data = None if body is None else json.dumps(body).encode()
            conn.request(method, path, body=data,
                         headers={"Content-Type": "application/json"} if data is not None else {})
            r = conn.getresponse()
            return r.status, r.read()
        finally:
            conn.close()

    def close(self) -> None:
        try:
            self.proc.kill()
            self.proc.wait(timeout=10)
        except Exception:
            pass
        self._out.close()
        self._err.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


def find_serve(plan: Plan, root: Path, producer: Task) -> tuple[str, str | None] | None:
    owned_mods = {module_name(root, root / o) for o in producer.owns() if o.endswith(".py")}
    entries = []
    for e in plan.probe_entries:
        serve = parse_probe_entry(e).get("serve")
        if serve:
            entries.append(parse_serve(serve))
    for target, args in entries:
        if target.rpartition(".")[0] in owned_mods:
            return target, args
    if entries:
        return entries[0]
    for p in planned_items(plan, [producer.id]):
        if p.ret and "Server" in p.ret:
            mod, chain, _f = locate(root, plan, p)
            if mod and len(chain) == 1:
                return f"{mod}.{chain[0]}", None
    return None


def check_data_contract(plan: Plan, root: Path, producer: Task, consumer: Task
                        ) -> tuple[list[Mismatch], list[str]]:
    notes: list[str] = []
    mm: list[Mismatch] = []
    contract = data_contract(plan, [producer.id, consumer.id])
    if not contract:
        return mm, ["part2 skipped: no data contract lines (METHOD /path -> status {shape}) in the plan"]
    calls = scan_calls(root, consumer.owns())
    for c in calls:
        if not call_in_contract(c, contract):
            shown = c.path + ("..." if c.prefix else "")
            mm.append(Mismatch(2, c.file, c.line, f"consumer {consumer.id} calls {c.method} {shown}, "
                                                  f"which is not in the data contract", consumer.id))
    serve = find_serve(plan, root, producer)
    if not serve:
        notes.append("part2: server not started (no serve= in a Probe entry and no Produces returning a server)")
        return mm, notes
    handle = ServerHandle(root, *serve)
    try:
        if handle.error or not handle.info:
            err = handle.error or "unknown"
            if "needs arguments" in err:
                notes.append(f"part2: server not started: {err}")
            else:
                mm.append(Mismatch(2, rel_to(root, plan.path), producer.start + 1,
                                   f"producer {producer.id} server failed to start: {err}", producer.id))
            return mm, notes
        loc_file = rel_to(root, handle.info["file"]) if handle.info.get("file") else rel_to(root, plan.path)
        loc_line = handle.info.get("line") or 1
        for c in contract:
            path = re.sub(r"\{[^}]*\}|:\w+|<[^>]*>", "x", c.path)
            try:
                status, raw = handle.request(c.method, path, c.body)
            except Exception as e:  # noqa: BLE001
                mm.append(Mismatch(2, loc_file, loc_line, f"{c.method} {c.path} failed: {type(e).__name__}: {e}",
                                   producer.id))
                continue
            if c.status is not None and status != c.status:
                mm.append(Mismatch(2, loc_file, loc_line,
                                   f"{c.method} {c.path} returned status {status}, contract says {c.status}",
                                   producer.id))
                continue
            if c.shape is not None:
                try:
                    value = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    mm.append(Mismatch(2, loc_file, loc_line,
                                       f"{c.method} {c.path} body is not JSON, contract expects a shape",
                                       producer.id))
                    continue
                for prob in check_shape(value, c.shape):
                    mm.append(Mismatch(2, loc_file, loc_line, f"{c.method} {c.path}: {prob}", producer.id))
    finally:
        handle.close()
    return mm, notes


# --------------------------------------------------------------------------- consumer tests (part 3)


def rerun_consumer_tests(root: Path, consumer: Task, timeout: float) -> tuple[list[Mismatch], list[str]]:
    files = [o for o in consumer.owns() if o.endswith(".py") and TEST_PATH_RE.search(o) and (root / o).is_file()]
    if not files:
        return [], [f"part3 skipped: {consumer.id} owns no existing Python test files"]
    try:
        base = pyrun.pytest_cmd()
    except pyrun.PytestUnavailable as e:
        return [], [f"part3 skipped: {e}"]
    cmd = [*base, "-q", "-x", "--no-header", "-p", "no:cacheprovider", *files]
    try:
        proc = pyrun.run_tree(cmd, cwd=root, env=project_env(root, SUPERLITE_REAL="1"), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return [Mismatch(3, files[0], 1, f"{consumer.id} tests hung (> {timeout:.0f}s) with SUPERLITE_REAL=1",
                         consumer.id)], []
    if proc.returncode == 0:
        return [], []
    if proc.returncode == 5:
        return [], [f"part3 skipped: pytest collected no tests in {', '.join(files)}"]
    out = proc.stdout + proc.stderr
    loc = re.search(r"^([^\s:]+\.py):(\d+): ", out, re.M)
    last = next((ln for ln in reversed(out.splitlines()) if ln.strip()), "pytest failed")
    file, line = (loc.group(1).replace("\\", "/"), int(loc.group(2))) if loc else (files[0], 1)
    return [Mismatch(3, file, line, f"{consumer.id} tests fail with the real producer "
                                    f"(SUPERLITE_REAL=1): {last.strip()}", consumer.id)], []


# --------------------------------------------------------------------------- contract command


def resolve_seam(plan: Plan, seam: str) -> tuple[Task, Task]:
    parts = [s.strip() for s in seam.split(",")]
    if len(parts) != 2 or any(p not in plan.tasks for p in parts):
        raise ToolError(f"--seam needs two task ids that exist in the plan, got {seam!r}")
    a, b = parts
    ta, tb = plan.tasks[a], plan.tasks[b]
    if (a, b) in plan.edges or a in tb.consumes_ids():
        return ta, tb
    if (b, a) in plan.edges or b in ta.consumes_ids():
        return tb, ta
    raise ToolError(f"no seam between {a} and {b} (no edge in %% taskgraph, no Consumes tag)")


def append_log(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def cmd_contract(a: argparse.Namespace) -> int:
    plan = parse_plan(a.plan)
    root = Path(a.root).resolve()
    notes: list[str] = []
    mismatches: list[Mismatch]
    if a.seam:
        producer, consumer = resolve_seam(plan, a.seam)
        label = "seam " + "↔".join(s.strip() for s in a.seam.split(","))
        mismatches, n = check_interfaces(plan, root, [producer.id])
        if n == 0:
            notes.append(f"part1: {producer.id} has no parseable Produces signatures")
        m2, n2 = check_data_contract(plan, root, producer, consumer)
        mismatches += m2
        notes += n2
        m3, n3 = rerun_consumer_tests(root, consumer, a.timeout)
        mismatches += m3
        notes += n3
    else:
        label = "contract"
        mismatches, n = check_interfaces(plan, root, None)
        notes.append(f"part1: {n} Produces signature(s) checked")
    for n_ in notes:
        print(f"note: {n_}")
    for m in mismatches:
        print(m)
    # A seam run always logs: mismatches become incidents, a pass becomes `verified`.
    log = Path(a.log) if a.log else (root / ".superlite" / "incidents.jsonl" if a.seam else None)
    if mismatches:
        print(f"FAIL: {label}: {len(mismatches)} mismatch(es)")
        if log:
            for m in mismatches:
                append_log(log, {"file": m.file, "line": m.line, "context": f"{label}: {m.msg}"[:200],
                                 "agent": "pt_review", "kind": "exception", "confidence": "high",
                                 "resolution": "open", "time": time.strftime("%H:%M:%S")})
        return 1
    print(f"PASS: verified: {label}")
    if log and a.seam:
        append_log(log, {"file": "", "line": 0, "context": f"verified: {label}", "agent": "pt_review",
                         "kind": "verified", "time": time.strftime("%H:%M:%S")})
    return 0


# --------------------------------------------------------------------------- adapter command

_ADAPTER_HEAD = '''"""Probe adapter, generated by pt_review.py adapter from the plan's Probe entry lines.
Do not edit; regenerate. Entry kinds: call(text) -> value, run(args, stdin) -> (rc, out, err),
request(method, path, body) -> (status, json)."""
from __future__ import annotations

import importlib
import inspect
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = (Path(__file__).resolve().parent / __REL_ROOT__).resolve()
for _p in (ROOT / "src", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

ENTRIES = __ENTRIES__
KINDS = __KINDS__


def _entry(kind, package=None):
    for e in ENTRIES:
        if kind in e and (package is None or e["package"] == package):
            return e
    raise LookupError("no %s entry%s in the plan's Probe entry lines" % (kind, " for " + package if package else ""))
'''

_ADAPTER_CALL = '''

def _resolve(dotted):
    parts = dotted.split(".")
    for k in range(len(parts), 0, -1):
        prefix = ".".join(parts[:k])
        try:
            obj = importlib.import_module(prefix)
        except ModuleNotFoundError as exc:
            if exc.name and prefix.startswith(exc.name):
                continue
            raise
        parent = None
        for name in parts[k:]:
            parent, obj = obj, getattr(obj, name)
        return obj, parent
    raise ImportError(dotted)


def call(text, package=None):
    """Library entry: import the planned target and call it with `text`."""
    obj, parent = _resolve(_entry("call", package)["call"])
    if inspect.isclass(parent) and inspect.isfunction(obj) and not isinstance(
            inspect.getattr_static(parent, obj.__name__, None), (staticmethod, classmethod)):
        obj = getattr(parent(), obj.__name__)
    return obj(text)
'''

_ADAPTER_RUN = '''

def run(args=(), stdin="", package=None, timeout=10):
    """CLI entry: execute the planned command with extra args; returns (rc, stdout, stderr)."""
    cmd = shlex.split(_entry("run", package)["run"], posix=(os.name != "nt"))
    if cmd and cmd[0] in ("python", "python3", "py"):
        cmd[0] = sys.executable
    if isinstance(args, str):
        args = shlex.split(args, posix=(os.name != "nt"))
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=os.pathsep.join(
        [str(ROOT / "src"), str(ROOT)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else [])))
    p = subprocess.run(cmd + list(args), input=stdin, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=ROOT, env=env, timeout=timeout)
    return p.returncode, p.stdout, p.stderr
'''

_ADAPTER_SERVE = '''
import http.client
import threading

_SERVERS = {}
''' + _SERVE_SNIPPET + '''

def _server(package=None):
    e = _entry("serve", package)
    key = e["package"]
    if key not in _SERVERS:
        target, args = e["serve"]
        srv, _fn = _make_server(target, args)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        _SERVERS[key] = srv
    return _SERVERS[key]


def request(method, path, body=None, package=None, timeout=10):
    """Server entry: one shared server per process on port 0; returns (status, json-or-text)."""
    srv = _server(package)
    host, port = srv.server_address[:2]
    conn = http.client.HTTPConnection(host if host not in ("", "0.0.0.0") else "127.0.0.1", port, timeout=timeout)
    try:
        if body is None or isinstance(body, bytes):
            data = body
        elif isinstance(body, str):
            data = body.encode("utf-8", "surrogatepass")
        else:
            data = json.dumps(body).encode()
        conn.request(method, path, body=data, headers={"Content-Type": "application/json"} if data else {})
        r = conn.getresponse()
        raw = r.read().decode("utf-8", "replace")
    finally:
        conn.close()
    try:
        return r.status, json.loads(raw)
    except ValueError:
        return r.status, raw


def close():
    for srv in list(_SERVERS.values()):
        srv.shutdown()
        srv.server_close()
    _SERVERS.clear()
'''


def build_adapter(plan: Plan, out: Path, root: Path) -> str:
    entries: list[dict] = []
    for text in plan.probe_entries:
        parsed = parse_probe_entry(text)
        if not parsed:
            continue
        first = parsed.get("call") or parsed.get("serve") or parsed.get("run", "")
        first = re.sub(r"^(python3?|py)\s+-m\s+", "", first.split("(")[0].strip())
        entry: dict = {"package": first.split(".")[0].split()[0] if first else f"p{len(entries)}"}
        if "call" in parsed:
            entry["call"] = parsed["call"]
        if "run" in parsed:
            entry["run"] = parsed["run"]
        if "serve" in parsed:
            entry["serve"] = list(parse_serve(parsed["serve"]))
        entries.append(entry)
    if not entries:
        raise ToolError("no `Probe entry:` lines with call=/run=/serve= found in the plan")
    kinds = [k for k in ("call", "run", "serve") if any(k in e for e in entries)]
    rel_root = os.path.relpath(root, out.parent.resolve()).replace("\\", "/")
    src = _ADAPTER_HEAD.replace("__REL_ROOT__", repr(rel_root)).replace("__ENTRIES__", repr(entries)) \
        .replace("__KINDS__", repr(["request" if k == "serve" else k for k in kinds]))
    if "call" in kinds:
        src += _ADAPTER_CALL
    if "run" in kinds:
        src += _ADAPTER_RUN
    if "serve" in kinds:
        src += _ADAPTER_SERVE
    return src


def cmd_adapter(a: argparse.Namespace) -> int:
    plan = parse_plan(a.plan)
    root = Path(a.root).resolve()
    out = Path(a.out) if a.out else root / ".superlite" / "probes" / "adapter.py"
    out.parent.mkdir(parents=True, exist_ok=True)
    src = build_adapter(plan, out, root)
    compile(src, str(out), "exec")
    out.write_text(src, encoding="utf-8", newline="\n")
    print(f"wrote {out}")
    return 0


# --------------------------------------------------------------------------- packet command


def read_incidents(path: Path) -> list[dict]:
    out: list[dict] = []
    if path.is_file():
        for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            if isinstance(e, dict) and "file" in e:
                e["file"] = str(e.get("file", "")).replace("\\", "/")
                try:
                    e["line"] = int(e.get("line") or 0)
                except (TypeError, ValueError):
                    e["line"] = 0
                out.append(e)
    return out


def excerpt(root: Path, file: str, line: int, ctx: int = 12) -> str:
    f = root / file
    if not f.is_file():
        f = root / "src" / file
    if not f.is_file():
        return "(file not found)"
    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
    if line <= 0:
        lo, hi = 1, min(len(lines), 2 * ctx + 1)
    else:
        lo, hi = max(1, line - ctx), min(len(lines), line + ctx)
    rows = []
    for n in range(lo, hi + 1):
        mark = ">" if n == line else " "
        rows.append(f"{mark}{n:>4} | {lines[n - 1][:160]}")
    return "\n".join(rows) if rows else "(empty file)"


@dataclass
class Item:
    section: str  # incidents | probes | uncovered | contract
    rank: tuple
    title: str
    body: str
    file: str = ""
    line: int = 0


def incident_items(entries: list[dict]) -> list[Item]:
    groups: dict[tuple[str, int], list[dict]] = {}
    for e in entries:
        if e.get("kind") != "verified":
            groups.setdefault((e["file"], e["line"]), []).append(e)
    items: list[Item] = []
    for (file, line), es in groups.items():
        repeated = len(es) >= 2
        unresolved = any(str(e.get("resolution", "")).lower() not in RESOLVED for e in es)
        low = any(str(e.get("confidence", "")).lower() == "low" for e in es)
        if not (repeated or unresolved or low):
            continue
        why = [w for w, on in (("repeated", repeated), ("unresolved", unresolved), ("low confidence", low)) if on]
        tier = 0 if repeated else 1 if unresolved else 2
        lines = []
        for e in es[:3]:
            tags = "/".join(str(e[k]) for k in ("kind", "resolution", "confidence", "agent") if e.get(k))
            lines.append(f"- [{tags}] {str(e.get('context', ''))[:200]}")
        if len(es) > 3:
            lines.append(f"- (+{len(es) - 3} more entries at this location)")
        items.append(Item("incidents", (1, tier, -len(es), file, line),
                          f"{file}:{line}  ({', '.join(why)}; {len(es)} entr{'y' if len(es) == 1 else 'ies'})",
                          "\n".join(lines), file, line))
    return items


def read_probe_failures(probes: Path) -> list[Item]:
    f = probes if probes.is_file() else probes / "probe-results.json"
    if not f.is_file():
        return []
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except ValueError:
        return []
    results = data.get("results", []) if isinstance(data, dict) else data
    items: list[Item] = []
    for r in results if isinstance(results, list) else []:
        if not isinstance(r, dict) or str(r.get("status", "pass")).lower() in PASS_STATUSES:
            continue
        file = str(r.get("file", "")).replace("\\", "/")
        line = int(r.get("line") or 0)
        detail = str(r.get("detail") or r.get("message") or r.get("probe") or "")[:200]
        items.append(Item("probes", (3, str(r.get("category", "")), file, line),
                          f"probe {r.get('category', '?')} {r.get('status')}: {file}:{line}",
                          f"- {detail}" if detail else "", file, line))
    return items


def focus_packages(plan: Plan) -> list[tuple[str, list[str]]]:
    text = plan.review_focus()
    out: list[tuple[str, list[str]]] = []
    for ln in text.splitlines():
        m = re.match(r"^\s*(?:[-*]\s*)?\**`?([\w./-]+)`?\**\s*[:—-]\s*(.+)$", ln)
        if not m:
            continue
        cats = [c for c in re.split(r"[,·/;\s]+", m.group(2).lower().replace("**", "")) if c in CATEGORIES]
        if cats:
            out.append((Path(m.group(1)).name, list(dict.fromkeys(cats))))
    return out


def package_dir(root: Path, pkg: str) -> Path | None:
    for cand in (root / "src" / pkg, root / pkg):
        if cand.is_dir():
            return cand
    return None


def uncovered_items(plan: Plan, root: Path, entries: list[dict]) -> list[Item]:
    verified = [e for e in entries if e.get("kind") == "verified"]
    items: list[Item] = []
    for pkg, cats in focus_packages(plan):
        files = [e for e in verified if pkg in re.split(r"[/.]", e["file"].replace(".py", ""))
                 or e["file"].replace(".py", "") == pkg]
        for cat in cats:
            hit = any(str(e.get("category", "")).lower() == cat
                      or re.search(rf"\b{cat}\b", str(e.get("context", "")).lower()) for e in files)
            if hit:
                continue
            file, line = "", 0
            d = package_dir(root, pkg)
            if d:
                cands = sorted((p for p in d.rglob("*.py") if p.name != "__init__.py"
                                and not set(p.relative_to(d).parts) & SKIP_DIRS),
                               key=lambda p: -p.stat().st_size)
                if cands:
                    file = rel_to(root, cands[0])
                    try:
                        tree = ast.parse(cands[0].read_text(encoding="utf-8"))
                        line = next((n.lineno for n in tree.body
                                     if isinstance(n, (ast.FunctionDef, ast.ClassDef))), 1)
                    except (SyntaxError, OSError):
                        line = 1
            items.append(Item("uncovered", (4, pkg, cat),
                              f"package {pkg}: no `verified` entry for category `{cat}`",
                              "- Unverified: judge from the excerpt or list it as a finding.", file, line))
    return items


def package_of(root: Path, f: Path) -> str | None:
    try:
        rel = f.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    parts = list(rel.parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    elif parts and not (root / parts[0] / "__init__.py").is_file():
        return None
    return parts[0] if len(parts) > 1 else None


def source_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        out.extend(Path(dirpath) / f for f in filenames if f.endswith(".py"))
    return out


def cross_package_calls(root: Path) -> list[str]:
    files = source_files(root)
    pkgs = {p for p in (package_of(root, f) for f in files) if p}
    rows: set[tuple[str, int, str, str, str]] = set()
    for f in files:
        own = package_of(root, f)
        if not own:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        alias: dict[str, str] = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for al in n.names:
                    alias[(al.asname or al.name).split(".")[0]] = al.name if al.asname else al.name.split(".")[0]
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                for al in n.names:
                    alias[al.asname or al.name] = f"{n.module}.{al.name}"
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            chain, cur = [], n.func
            while isinstance(cur, ast.Attribute):
                chain.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name) and cur.id in alias:
                full = ".".join([alias[cur.id]] + chain[::-1])
                target = full.split(".")[0]
                if target in pkgs and target != own:
                    rows.add((rel_to(root, f), n.lineno, own, target, full))
    return [f"- {f}:{ln}  {a} -> {b}: {full}()" for f, ln, a, b, full in sorted(rows)]


def git_diff_stat(root: Path, base: str | None) -> str:
    def git(*args: str) -> subprocess.CompletedProcess | None:
        try:
            return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None

    if not (root / ".git").exists():
        return "(not a git repository)"
    if base is None:
        first = git("rev-list", "--max-parents=0", "HEAD")
        base = first.stdout.split()[0] if first and first.returncode == 0 and first.stdout.split() else "HEAD"
    r = git("diff", "--stat", base)
    if not r or r.returncode != 0:
        return "(diff stat unavailable)"
    return r.stdout.strip() or "(no changes)"


def read_test_summary(path: Path) -> tuple[str, int]:
    if not path.is_file():
        return "- no test summary recorded (`run_tests.py --full` runs alongside this review)", 0
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return "- test summary unreadable", 0
    failed = d.get("failures") or d.get("failed_tests") or []
    skipped = d.get("skipped_tests") or []
    nfail = int(d["failed"]) if isinstance(d.get("failed"), int) else len(failed)
    rows = [f"- passed {d.get('passed', '?')} · failed {nfail} · skipped {d.get('skipped', len(skipped))}"]
    rows += [f"- FAILING: {t}" for t in failed[:30]]
    rows += [f"- SKIPPED: {t}" for t in skipped[:30]]
    return "\n".join(rows), nfail


def render_item(root: Path, it: Item, shown: set[tuple[str, int]], idx: str) -> str:
    out = [f"### {idx} {it.title}"]
    if it.body:
        out.append(it.body)
    if it.file:
        key = (it.file, it.line)
        if key in shown:
            out.append("(excerpt shown with the item for the same location)")
        else:
            shown.add(key)
            out.append("```\n" + excerpt(root, it.file, it.line) + "\n```")
    return "\n".join(out) + "\n"


def cap_text(s: str, limit: int, note: str = "(truncated)") -> str:
    if len(s) <= limit:
        return s
    return s[: max(0, limit - len(note) - 1)].rstrip() + "\n" + note


def cmd_packet(a: argparse.Namespace) -> int:
    plan = parse_plan(a.plan)
    root = Path(a.root).resolve()
    sl = root / ".superlite"
    log = Path(a.log) if a.log else sl / "incidents.jsonl"
    probes = Path(a.probes) if a.probes else sl / "probes"
    out = Path(a.out) if a.out else sl / "review-packet.md"
    tests = Path(a.tests) if a.tests else sl / "test-summary.json"
    cap = int(a.max_tokens * CHARS_PER_TOKEN)

    entries = read_incidents(log)
    items = incident_items(entries) + read_probe_failures(probes) + uncovered_items(plan, root, entries)
    mismatches, n_checked = check_interfaces(plan, root, None)
    for m in mismatches:
        items.append(Item("contract", (2, m.file, m.line, m.msg), f"{m.file}:{m.line}  part1 {m.task}",
                          f"- {m.msg}", m.file, m.line))
    items.sort(key=lambda i: i.rank)
    counts = {s: sum(1 for i in items if i.section == s) for s in ("incidents", "probes", "uncovered", "contract")}
    tests_text, nfail = read_test_summary(tests)
    n_open = sum(counts.values()) + (1 if nfail else 0)
    fast = n_open == 0

    seams = cross_package_calls(root)
    seam_text = "\n".join(seams) if seams else "- none"
    seam_text = cap_text(seam_text, 5000, f"- (+ more calls omitted; {len(seams)} total)")
    focus = cap_text(plan.review_focus() or "(plan has no Review Focus section)", 3000)
    diff = cap_text(git_diff_stat(root, a.base), 2000)

    head = [
        f"# Review packet: {'FAST PATH' if fast else 'REVIEW REQUIRED'}",
        f"plan: {plan.path.name}",
        "Answer in one turn, no tools: a verdict, then findings as `file:line - problem - fix`. "
        "Anything marked unverified is judged from its excerpt or listed as a finding.",
        ("Nothing is open: no open incidents, probe failures, unverified categories, contract mismatches or "
         "failing tests. Reply with a short APPROVED (about 10 s)." if fast else
         f"Open items: {n_open} (incidents {counts['incidents']}, probe failures {counts['probes']}, "
         f"unverified categories {counts['uncovered']}, contract mismatches {counts['contract']}, "
         f"failing tests {nfail}). Excerpts are +-12 lines."),
        "",
    ]
    tail = ["## 4. Test summary", tests_text, "",
            "## 5. Cross-package seams (calls from one package into another)", seam_text, "",
            "## 6. Diff stat", "```\n" + diff + "\n```", "",
            "## 7. Review Focus", focus, ""]
    sec_titles = {
        "incidents": "## 1. Open incidents (repeated file:line first, then unresolved, then low confidence)",
        "probes": "## 2. Probe results: failures still open and unverified categories",
        "contract": f"## 3. Contract check: real signatures vs the plan's Produces ({n_checked} checked, "
                    f"{len(mismatches)} mismatch(es))",
    }
    fixed_len = len("\n".join(head + tail)) + 400 + sum(len(t) + 40 for t in sec_titles.values())
    budget = cap - fixed_len
    chosen: list[tuple[Item, str]] = []
    used, shown = 0, set()
    omitted = {s: 0 for s in counts}
    stopped = False
    for n, it in enumerate(items, 1):
        text = render_item(root, it, shown, f"[{n}]")
        if stopped or used + len(text) > budget:
            stopped = True
            omitted[it.section] += 1
            continue
        chosen.append((it, text))
        used += len(text)
    parts = list(head)
    for sec in ("incidents", "probes", "contract"):
        parts.append(sec_titles[sec])
        sec_items = [t for it, t in chosen if it.section == sec or (sec == "probes" and it.section == "uncovered")]
        parts.extend(sec_items or ["- none\n"])
        om = omitted[sec] + (omitted["uncovered"] if sec == "probes" else 0)
        if om:
            parts.append(f"- ({om} lower-ranked item(s) omitted to stay within the size cap)\n")
    parts.extend(tail)
    text = "\n".join(parts)
    if len(text) > cap:
        text = cap_text(text, cap, "(packet truncated at the size cap)")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {out} ({len(text)} chars, ~{int(len(text) / CHARS_PER_TOKEN)} tokens) - "
          f"{'FAST PATH' if fast else f'{n_open} open item(s)'}")
    return 0


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pt_review.py", description="Review-side plan tools.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("adapter", "packet", "contract"):
        sp = sub.add_parser(name)
        sp.add_argument("--plan", required=True)
        sp.add_argument("--root", default=".")
        if name == "adapter":
            sp.add_argument("--out")
        elif name == "packet":
            sp.add_argument("--log")
            sp.add_argument("--probes")
            sp.add_argument("--out")
            sp.add_argument("--max-tokens", type=int, default=20000)
            sp.add_argument("--tests", help="test summary JSON (default .superlite/test-summary.json)")
            sp.add_argument("--base", help="git ref for the diff stat (default: the root commit)")
        else:
            sp.add_argument("--seam", help="Ta,Tb: run parts 1-3 for that seam")
            sp.add_argument("--log", help="append a verified/incident entry to this JSONL log "
                                          "(--seam default: <root>/.superlite/incidents.jsonl)")
            sp.add_argument("--timeout", type=float, default=300.0, help="consumer test timeout, seconds")
    return ap


def main(argv: list[str]) -> int:
    try:
        a = build_parser().parse_args(argv)
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 2
    try:
        return {"adapter": cmd_adapter, "packet": cmd_packet, "contract": cmd_contract}[a.cmd](a)
    except ToolError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    sys.exit(main(sys.argv[1:]))
