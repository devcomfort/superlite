"""Reference implementation of the ladder10 mini spreadsheet engine."""
from __future__ import annotations

import re

__all__ = ["Sheet"]


class _Err:
    __slots__ = ("code",)

    def __init__(self, code):
        self.code = code

    def __repr__(self):
        return self.code


DIV0 = _Err("#DIV/0!")
VALUE = _Err("#VALUE!")
REF = _Err("#REF!")
CYCLE = _Err("#CYCLE!")

_INT_RE = re.compile(r"-?[0-9]+")
_FLOAT_RE = re.compile(r"-?[0-9]+\.[0-9]+")
_NAME_RE = re.compile(r"([A-Z])([0-9]+)")
_REF_RE = re.compile(r"(\$?)([A-Z])(\$?)([0-9]+)")
_TOKEN_RE = re.compile(
    r"""
    (?P<ws>[ \t\r\n]+)
  | (?P<num>[0-9]+(?:\.[0-9]+)?)
  | (?P<ref>\$?[A-Z]\$?[0-9]+(?![A-Za-z0-9_]))
  | (?P<referr>\#REF!)
  | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>[-+*/(),:])
  | (?P<bad>.)
    """,
    re.X | re.S,
)
_FUNCS = ("SUM", "MIN", "MAX", "AVG", "COUNT")
_MAXCOL = 25
_MAXROW = 999


def _classify(raw):
    if _INT_RE.fullmatch(raw):
        return int(raw)
    if _FLOAT_RE.fullmatch(raw):
        return float(raw)
    return raw


def _tokenize(text, start=0):
    toks = []
    pos = start
    n = len(text)
    while pos < n:
        m = _TOKEN_RE.match(text, pos)
        toks.append((m.lastgroup, m.group(), m.start(), m.end()))
        pos = m.end()
    return toks


def _ref(text):
    """Parse ref text to (col_abs, col, row_abs, row); None when row < 1."""
    m = _REF_RE.fullmatch(text)
    row = int(m.group(4))
    if row < 1:
        return None
    return (bool(m.group(1)), ord(m.group(2)) - 65, bool(m.group(3)), row)


def _fmt(r):
    return ("$" if r[0] else "") + chr(65 + r[1]) + ("$" if r[2] else "") + str(r[3])


# ---------------------------------------------------------------- parsing

class _ParseError(Exception):
    pass


class _Parser:
    def __init__(self, text):
        self.toks = [t for t in _tokenize(text, 1) if t[0] != "ws"]
        self.i = 0

    def peek(self, k=0):
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else None

    def parse(self):
        node = self.expr()
        if self.peek() is not None:
            raise _ParseError
        return node

    def expr(self):
        node = self.term()
        while True:
            t = self.peek()
            if t and t[0] == "op" and t[1] in "+-":
                self.i += 1
                node = ("bin", t[1], node, self.term())
            else:
                return node

    def term(self):
        node = self.unary()
        while True:
            t = self.peek()
            if t and t[0] == "op" and t[1] in "*/":
                self.i += 1
                node = ("bin", t[1], node, self.unary())
            else:
                return node

    def unary(self):
        t = self.peek()
        if t and t[0] == "op" and t[1] == "-":
            self.i += 1
            return ("neg", self.unary())
        return self.primary()

    def refnode(self, tok):
        r = _ref(tok[1])
        if r is None:
            raise _ParseError
        return r[1], r[3]

    def primary(self):
        t = self.peek()
        if t is None:
            raise _ParseError
        kind, text = t[0], t[1]
        if kind == "num":
            self.i += 1
            return ("num", float(text) if "." in text else int(text))
        if kind == "ref":
            self.i += 1
            c, r = self.refnode(t)
            return ("ref", c, r)
        if kind == "referr":
            self.i += 1
            return ("err",)
        if kind == "word":
            nxt = self.peek(1)
            if text in _FUNCS and nxt and nxt[0] == "op" and nxt[1] == "(":
                self.i += 2
                return ("fn", text, self.args())
            raise _ParseError
        if kind == "op" and text == "(":
            self.i += 1
            node = self.expr()
            t2 = self.peek()
            if not (t2 and t2[0] == "op" and t2[1] == ")"):
                raise _ParseError
            self.i += 1
            return node
        raise _ParseError

    def args(self):
        args = []
        t = self.peek()
        if t and t[0] == "op" and t[1] == ")":
            self.i += 1
            return args
        while True:
            t = self.peek()
            n1 = self.peek(1)
            if t and t[0] == "ref" and n1 and n1[0] == "op" and n1[1] == ":":
                t2 = self.peek(2)
                if not (t2 and t2[0] == "ref"):
                    raise _ParseError
                c1, r1 = self.refnode(t)
                c2, r2 = self.refnode(t2)
                self.i += 3
                args.append(("range", c1, r1, c2, r2))
            else:
                args.append(self.expr())
            t = self.peek()
            if t and t[0] == "op" and t[1] == ",":
                self.i += 1
                continue
            if t and t[0] == "op" and t[1] == ")":
                self.i += 1
                return args
            raise _ParseError


def _parse(raw):
    try:
        return _Parser(raw).parse()
    except (_ParseError, RecursionError):
        return None


def _deps_walk(node, refs, ranges):
    t = node[0]
    if t == "ref":
        refs.append((node[1], node[2]))
    elif t == "range":
        ranges.append(node)
    elif t == "neg":
        _deps_walk(node[1], refs, ranges)
    elif t == "bin":
        _deps_walk(node[2], refs, ranges)
        _deps_walk(node[3], refs, ranges)
    elif t == "fn":
        for a in node[2]:
            _deps_walk(a, refs, ranges)


# ------------------------------------------------------------- evaluation

def _rect_values(node, vals):
    """Values of non-empty cells in a range node, in row-major order."""
    c1, r1, c2, r2 = node[1], node[2], node[3], node[4]
    clo, chi = min(c1, c2), max(c1, c2)
    rlo, rhi = min(r1, r2), max(r1, r2)
    area = (chi - clo + 1) * (rhi - rlo + 1)
    if area <= len(vals):
        for r in range(rlo, rhi + 1):
            for c in range(clo, chi + 1):
                v = vals.get((c, r))
                if v is not None:
                    yield v
    else:
        keys = [k for k in vals if clo <= k[0] <= chi and rlo <= k[1] <= rhi]
        keys.sort(key=lambda k: (k[1], k[0]))
        for k in keys:
            yield vals[k]


def _ev(node, vals):
    t = node[0]
    if t == "num":
        return node[1]
    if t == "ref":
        v = vals.get((node[1], node[2]))
        return 0 if v is None else v
    if t == "err":
        return REF
    if t == "neg":
        v = _ev(node[1], vals)
        if isinstance(v, _Err):
            return v
        if isinstance(v, str):
            return VALUE
        return -v
    if t == "bin":
        op = node[1]
        lv = _ev(node[2], vals)
        rv = _ev(node[3], vals)
        if isinstance(lv, _Err):
            return lv
        if isinstance(rv, _Err):
            return rv
        if isinstance(lv, str) or isinstance(rv, str):
            return VALUE
        if op == "+":
            return lv + rv
        if op == "-":
            return lv - rv
        if op == "*":
            return lv * rv
        if rv == 0:
            return DIV0
        return lv / rv
    if t == "fn":
        return _fn(node[1], node[2], vals)
    raise AssertionError(t)


def _fn(name, args, vals):
    nums = []
    for a in args:
        if a[0] == "range":
            for v in _rect_values(a, vals):
                if isinstance(v, _Err):
                    return v
                if isinstance(v, str):
                    continue
                nums.append(v)
        else:
            v = _ev(a, vals)
            if isinstance(v, _Err):
                return v
            if isinstance(v, str):
                return VALUE
            nums.append(v)
    if name == "COUNT":
        return len(nums)
    if name == "AVG":
        if not nums:
            return DIV0
        return sum(nums) / len(nums)
    if not nums:
        return 0
    if name == "SUM":
        res = sum(nums)
    elif name == "MIN":
        res = min(nums)
    else:
        res = max(nums)
    if any(isinstance(x, float) for x in nums):
        res = float(res)
    return res


# ------------------------------------------------------------- rewriting

def _rewrite(raw, ref_cb, range_cb):
    """Rewrite references of formula text `raw` in place.

    ref_cb(r) -> new r or None (#REF!); range_cb(r1, r2) -> (r1', r2') or None.
    """
    sig = [t for t in _tokenize(raw, 1) if t[0] != "ws"]
    out = []
    pos = 0
    i = 0
    while i < len(sig):
        kind, text, s, e = sig[i]
        if kind == "ref":
            r = _ref(text)
            if r is not None:
                r2 = None
                if (
                    i + 2 < len(sig)
                    and sig[i + 1][1] == ":"
                    and sig[i + 1][0] == "op"
                    and sig[i + 2][0] == "ref"
                ):
                    r2 = _ref(sig[i + 2][1])
                if r2 is not None:
                    res = range_cb(r, r2)
                    out.append(raw[pos:s])
                    if res is None:
                        out.append("#REF!")
                    else:
                        a = text if res[0] == r else _fmt(res[0])
                        b_text = sig[i + 2][1]
                        b = b_text if res[1] == r2 else _fmt(res[1])
                        out.append(a + raw[e:sig[i + 2][2]] + b)
                    pos = sig[i + 2][3]
                    i += 3
                    continue
                res = ref_cb(r)
                out.append(raw[pos:s])
                if res is None:
                    out.append("#REF!")
                else:
                    out.append(text if res == r else _fmt(res))
                pos = e
        i += 1
    out.append(raw[pos:])
    return "".join(out)


def _in_bounds(c, r):
    return 0 <= c <= _MAXCOL and 1 <= r <= _MAXROW


def _copy_formula(raw, dc, dr):
    def shift(r):
        c = r[1] if r[0] else r[1] + dc
        row = r[3] if r[2] else r[3] + dr
        if not _in_bounds(c, row):
            return None
        return (r[0], c, r[2], row)

    def rng(a, b):
        x, y = shift(a), shift(b)
        if x is None or y is None:
            return None
        return (x, y)

    return _rewrite(raw, shift, rng)


def _insert_formula(raw, at, n):
    def mv(r):
        return (r[0], r[1], r[2], r[3] + n) if r[3] >= at else r

    return _rewrite(raw, mv, lambda a, b: (mv(a), mv(b)))


def _delete_formula(raw, at, n):
    end = at + n - 1

    def one(r):
        row = r[3]
        if at <= row <= end:
            return None
        if row > end:
            return (r[0], r[1], r[2], row - n)
        return r

    def rng(a, b):
        if a[3] <= b[3]:
            top, bot, top_is_a = a[3], b[3], True
        else:
            top, bot, top_is_a = b[3], a[3], False
        if at <= top and bot <= end:
            return None
        if top < at:
            ntop = top
        elif top <= end:
            ntop = at
        else:
            ntop = top - n
        if bot < at:
            nbot = bot
        elif bot <= end:
            nbot = at - 1
        else:
            nbot = bot - n
        if top_is_a:
            na = (a[0], a[1], a[2], ntop)
            nb = (b[0], b[1], b[2], nbot)
        else:
            nb = (b[0], b[1], b[2], ntop)
            na = (a[0], a[1], a[2], nbot)
        return (na, nb)

    return _rewrite(raw, one, rng)


# ------------------------------------------------------------------ sheet

def _key(cell):
    m = _NAME_RE.fullmatch(cell) if isinstance(cell, str) else None
    if not m or int(m.group(2)) < 1:
        raise ValueError(f"invalid cell name: {cell!r}")
    return (ord(m.group(1)) - 65, int(m.group(2)))


class Sheet:
    def __init__(self):
        self._cells = {}  # (col, row) -> raw (non-empty)
        self._vals = None
        self._undo = []
        self._redo = []
        self._parse_cache = {}

    # -- internals
    def _record(self):
        self._undo.append(dict(self._cells))
        self._redo.clear()

    def _changed(self):
        self._vals = None

    def _ast(self, raw):
        try:
            return self._parse_cache[raw]
        except KeyError:
            a = self._parse_cache[raw] = _parse(raw)
            return a

    def _compute(self):
        vals = {}
        forms = {}
        for k, raw in self._cells.items():
            if raw.startswith("="):
                forms[k] = self._ast(raw)
            else:
                vals[k] = _classify(raw)
        deps = {}
        for k, ast in forms.items():
            d = []
            if ast is not None:
                refs, ranges = [], []
                _deps_walk(ast, refs, ranges)
                for rk in refs:
                    if rk in forms:
                        d.append(rk)
                for rg in ranges:
                    clo, chi = sorted((rg[1], rg[3]))
                    rlo, rhi = sorted((rg[2], rg[4]))
                    area = (chi - clo + 1) * (rhi - rlo + 1)
                    if area <= len(forms):
                        for r in range(rlo, rhi + 1):
                            for c in range(clo, chi + 1):
                                if (c, r) in forms:
                                    d.append((c, r))
                    else:
                        for fk in forms:
                            if clo <= fk[0] <= chi and rlo <= fk[1] <= rhi:
                                d.append(fk)
            deps[k] = d

        def process(comp):
            if len(comp) > 1 or comp[0] in deps[comp[0]]:
                for k in comp:
                    vals[k] = CYCLE
                return
            k = comp[0]
            ast = forms[k]
            if ast is None:
                vals[k] = VALUE
                return
            try:
                v = _ev(ast, vals)
            except RecursionError:
                v = VALUE
            if isinstance(v, str):
                v = VALUE
            vals[k] = v

        # iterative Tarjan SCC; components are emitted dependencies-first
        index, low, onstack, stack = {}, {}, set(), []
        counter = 0
        for root in forms:
            if root in index:
                continue
            index[root] = low[root] = counter
            counter += 1
            stack.append(root)
            onstack.add(root)
            work = [(root, iter(deps[root]))]
            while work:
                v, it = work[-1]
                advanced = False
                for w in it:
                    if w not in index:
                        index[w] = low[w] = counter
                        counter += 1
                        stack.append(w)
                        onstack.add(w)
                        work.append((w, iter(deps[w])))
                        advanced = True
                        break
                    elif w in onstack:
                        low[v] = min(low[v], index[w])
                if advanced:
                    continue
                work.pop()
                if work:
                    u = work[-1][0]
                    low[u] = min(low[u], low[v])
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        onstack.discard(w)
                        comp.append(w)
                        if w == v:
                            break
                    process(comp)
        self._vals = vals

    # -- public API
    def set(self, cell, raw):
        k = _key(cell)
        self._record()
        if raw == "":
            self._cells.pop(k, None)
        else:
            self._cells[k] = raw
        self._changed()

    def get(self, cell):
        k = _key(cell)
        if self._vals is None:
            self._compute()
        v = self._vals.get(k)
        if isinstance(v, _Err):
            return v.code
        return v

    def raw(self, cell):
        return self._cells.get(_key(cell), "")

    def copy(self, src, dst):
        sk, dk = _key(src), _key(dst)
        self._record()
        raw = self._cells.get(sk, "")
        if raw.startswith("="):
            raw = _copy_formula(raw, dk[0] - sk[0], dk[1] - sk[1])
        if raw == "":
            self._cells.pop(dk, None)
        else:
            self._cells[dk] = raw
        self._changed()

    def insert_rows(self, at, n):
        if at < 1 or n < 1:
            return
        self._record()
        new = {}
        for (c, r), raw in self._cells.items():
            if raw.startswith("="):
                raw = _insert_formula(raw, at, n)
            new[(c, r + n if r >= at else r)] = raw
        self._cells = new
        self._changed()

    def delete_rows(self, at, n):
        if at < 1 or n < 1:
            return
        self._record()
        end = at + n - 1
        new = {}
        for (c, r), raw in self._cells.items():
            if at <= r <= end:
                continue
            if raw.startswith("="):
                raw = _delete_formula(raw, at, n)
            new[(c, r - n if r > end else r)] = raw
        self._cells = new
        self._changed()

    def undo(self):
        if not self._undo:
            return False
        self._redo.append(dict(self._cells))
        self._cells = self._undo.pop()
        self._changed()
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append(dict(self._cells))
        self._cells = self._redo.pop()
        self._changed()
        return True
