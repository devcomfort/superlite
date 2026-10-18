"""Fixture parser: nested parentheses around integers, joined with + and -."""
GUARD = True      # test knob: False removes the depth guard (RecursionError on deep input)
LIMIT = None      # test knob: an int makes depths >= LIMIT raise _Boom (an unexpected error)


class _Boom(Exception):
    pass


def _value(s, i, depth):
    if LIMIT is not None and depth >= LIMIT:
        raise _Boom("too deep")
    if GUARD and depth > 50:
        raise ValueError("nesting too deep")
    if i < len(s) and s[i] == "(":
        v, i = _sum(s, i + 1, depth + 1)
        if i >= len(s) or s[i] != ")":
            raise ValueError("expected )")
        return v, i + 1
    j = i
    while j < len(s) and s[j].isascii() and s[j].isdigit():
        j += 1
    if j == i:
        raise ValueError("expected a number")
    return int(s[i:j]), j


def _sum(s, i, depth):
    v, i = _value(s, i, depth)
    while i < len(s) and s[i] in "+-":
        op = s[i]
        w, i = _value(s, i + 1, depth)
        v = v + w if op == "+" else v - w
    return v, i


def parse(text):
    if len(text) > 100000:
        raise ValueError("input too long")
    v, i = _sum(text.strip(), 0, 0)
    if i != len(text.strip()):
        raise ValueError("trailing input")
    return v
