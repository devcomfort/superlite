# minisheet SPEC

Mini spreadsheet engine (CLI, HTTP API, web UI). Binding; where silent, untested.

## 0. Setup and layout
- Python >= 3.12, stdlib only at runtime, uv project, `src/minisheet/`. Run: `uv run python -m minisheet`, `uv run pytest`. `pyproject.toml`: project `minisheet`, a build backend, dev deps `pytest` `playwright`, `pythonpath=["src"]`.
- Modules (public names exactly as listed; extra helpers allowed): `refs lexer parser values evaluator functions workbook csvio cli __main__ server` and `static/index.html`. `minisheet/__init__.py` exports `Workbook`.
- Value = `float | str | bool | Empty | ErrorValue`; numbers are ALWAYS `float`, never `int`.

## 1. refs
- `Ref(col, row, abs_col=False, abs_row=False)`: frozen dataclass, 0-based (`A1` = `Ref(0,0)`). Columns A..ZZ (0..701), rows 1..9999.
- `parse_ref(s)`: `s` must fully match `\$?[A-Za-z]{1,2}\$?[1-9][0-9]{0,3}`, else `ValueError` (`A0`, `A01`, `AAA1`, `A10000`).
- `parse_range(s) -> (Ref, Ref)`: `ref:ref`, normalized to (top-left, bottom-right); each axis's `$` flag follows the corner supplying that axis's min/max (tie: first corner). `A1:A1` valid; bare `A1` -> `ValueError`.
- `to_a1(ref)`: uppercase, `$` before col/row if flagged; out of range -> `ValueError`.

| Call | Result |
|---|---|
| `parse_ref("B12")` | `Ref(1,11,False,False)` |
| `parse_ref("$zz$9999")` | `Ref(701,9998,True,True)` |
| `parse_range("$C3:A$1")` | `(Ref(0,0,False,True), Ref(2,2,True,False))` |
| `to_a1(Ref(26,0,True,False))` | `"$AA1"` |
| `parse_ref("A0")`, `parse_ref("AAA1")` | `ValueError` |

## 2. lexer
`tokenize(text) -> list[Token]`; `text` is the formula body WITHOUT the leading `=`. `Token(kind, text, pos)` dataclass, `pos` = 0-based index in `text`. No EOF token; spaces/tabs skipped.

| kind | rule | `Token.text` |
|---|---|---|
| `NUM` | `\d+(\.\d*)?\|\.\d+` then optional `[eE][+-]?\d+` | source |
| `STR` | `"..."`, `""` = one `"` | decoded |
| `REF` | `\$?[A-Za-z]+\$?[0-9]+`, not followed by `[A-Za-z0-9_]` nor directly by `(` | uppercased |
| `RANGE` | REF-shaped, `:` (no spaces), REF-shaped | uppercased |
| `NAME` | `[A-Za-z_][A-Za-z0-9_]*` (incl. REF-shaped followed by `(`, and `A1E3`) | uppercased |
| `OP` | longest of `<> <= >= + - * / ^ & = < > %` | operator |
| `LPAREN RPAREN COMMA` | `( ) ,` | char |

REF-shaped need not be in bounds (`AAA1` is a REF token). `FormulaSyntaxError(msg, pos)` (a `ValueError`), `.pos`: unterminated string -> its opening `"`; any other illegal char (`!`, `@`, `'`, lone `$`/`:`) -> that char.

| `tokenize(...)` | Result |
|---|---|
| `"A1+2"` | REF `A1`@0, OP `+`@2, NUM `2`@3 |
| `'"a""b"&sum(1)'` | STR `a"b`@0, OP `&`@6, NAME `SUM`@7, LPAREN@10, NUM@11, RPAREN@12 |
| `"$A$1:b2 <> 1e3"` | RANGE `$A$1:B2`@0, OP `<>`@8, NUM `1e3`@11 |
| `'"abc'` / `"1 + #"` | error pos 0 / pos 4 |

## 3. parser
`parse(text) -> Node` (same `text` convention; raises `FormulaSyntaxError`). Frozen dataclasses on base `Node`:

| Class | Fields |
|---|---|
| `Num` | `value: float` |
| `Str` | `value: str` |
| `Bool` | `value: bool` (bare `TRUE`/`FALSE`, any case, not before `(`) |
| `CellRef` | `ref: Ref` (flags kept) |
| `RangeRef` | `start: Ref`, `end: Ref` (normalized like `parse_range`) |
| `BadRef` | `text: str` (uppercased REF/RANGE token rejected by `parse_ref`/`parse_range`) |
| `Name` | `name: str` (other bare NAME, uppercased) |
| `UnaryOp` | `op: str` (`"-"`/`"+"`), `operand` |
| `Percent` | `operand` |
| `BinOp` | `op: str` (`+ - * / ^ & = <> < <= > >=`), `left`, `right` |
| `Call` | `name: str` (uppercased), `args: tuple[Node, ...]` |

Precedence, tightest first, binary ops LEFT-associative: `:` (in RANGE) > prefix `-` `+` > postfix `%` > `^` > `* /` > `+ -` > `&` > comparisons. So `-2^2` = `(-2)^2` = 4 and `2^3^2` = `(2^3)^2` = 64. Grammar: `power := percent ('^' percent)*`, `percent := unary '%'*`, `unary := ('-'|'+') unary | primary`; so `2^-1` parses. Call = `NAME` `(` args `)` (spaces between tokens fine); `F()` valid; an empty arg (`F(1,)`) is an error. Error pos = pos of the offending token, or `len(text)` at premature end.

| `parse(...)` | Result |
|---|---|
| `"1+2*3"` | `BinOp("+",Num(1.0),BinOp("*",Num(2.0),Num(3.0)))` |
| `"2^3^2"` | `BinOp("^",BinOp("^",Num(2.0),Num(3.0)),Num(2.0))` |
| `"-2^2"` | `BinOp("^",UnaryOp("-",Num(2.0)),Num(2.0))` |
| `"50%+1"` | `BinOp("+",Percent(Num(50.0)),Num(1.0))` |
| `"sum(a1:b2,3)"` | `Call("SUM",(RangeRef(Ref(0,0),Ref(1,1)),Num(3.0)))` |
| `"AAA1+foo+true"` | `BinOp("+",BinOp("+",BadRef("AAA1"),Name("FOO")),Bool(True))` |
| `"($A$1)"`, `"F()"` | `CellRef(Ref(0,0,True,True))`, `Call("F",())` (no paren node) |
| `"1+"`, `"(1"`, `"1 2"`, `"1+*2"` | error pos 2 (all four) |
| `"SUM(1,)"`, `""` | error pos 6, pos 0 |

## 4. values
- `Empty`: singleton, falsy. `ErrorValue(code)`: frozen dataclass, eq by code, `str()` = code.
- Constants: `DIV0`=`#DIV/0!`, `VALUE`=`#VALUE!`, `REF`=`#REF!`, `NAME`=`#NAME?`, `CIRC`=`#CIRC!`.
- Helpers (an `ErrorValue` arg is returned unchanged; failure -> `VALUE`):
  - `to_number(v)`: float; bool -> 1/0; Empty -> 0; str -> strip, `""` -> 0, else fully match `[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?` and be finite.
  - `to_bool(v)`: bool; float -> `!=0`; Empty -> False; str -> `TRUE`/`FALSE` (stripped, any case).
  - `to_text(v)`: str; bool -> `TRUE`/`FALSE`; Empty -> `""`; float -> `format_number`.
  - `format_number(x)`: `format(x,".15g")`, `"-0"` -> `"0"`.

| Call | Result |
|---|---|
| `to_number("  3.5 ")`, `("")`, `("abc")` | `3.5`, `0.0`, `VALUE` |
| `format_number` of `3.0`, `2.5`, `0.1+0.2` | `"3"`, `"2.5"`, `"0.3"` |
| `format_number` of `1/3`, `1e20`, `-0.0` | `"0.333333333333333"`, `"1e+20"`, `"0"` |

## 5. evaluator
`evaluate(node, get_cell) -> Value`; `get_cell(ref: Ref) -> Value` gives one cell's value (`Empty` if blank).
- Top-level `Empty` -> `0.0`; top-level range -> `VALUE`. Inside expressions `Empty` stays.
- `CellRef` -> `get_cell`; `BadRef` -> `REF`; `Name` -> `NAME`. A `RangeRef` is legal only as a direct function argument, where it is a `list` of values in row-major order; anywhere else -> `VALUE`.
- Unary `-`: `to_number` then negate; `+`: `to_number`; `Percent`: `to_number(x)/100`. Operand error wins, then coercion.
- Binary ops evaluate both operands (no short-circuit), then: (1) left error -> it; (2) right error -> it; (3) coerce left (`to_number`; `to_text` for `&`), failure -> `VALUE`; (4) right likewise; (5) compute.
- `/` by 0 (incl. 0/0) -> `DIV0`. `^`: `0^negative` -> `DIV0`; negative base with non-integer exponent, or overflow/inf/nan from any arithmetic -> `VALUE`; `0^0` = 1. `&` = `to_text(l)+to_text(r)`.
- Comparisons give bool. Empty first becomes the other side's zero (0.0 / `""` / False; Empty vs Empty equal). Same types compare naturally (strings via `.lower()`, `FALSE<TRUE`); different types order `number < text < bool`, no coercion.
- `Call`: unknown name -> `NAME` (args not evaluated). Normal function: all args evaluated left to right, then `fn(*args)`; no pre-check of errors/arity. Lazy function: see 6.

| Formula | Value |
|---|---|
| `-2^2`, `2^3^2`, `2^-1`, `50%`, `200%*3` | `4.0`, `64.0`, `0.5`, `0.5`, `6.0` |
| `1/0`, `0/0`, `0^-1`, `(-8)^0.5` | `DIV0`, `DIV0`, `DIV0`, `VALUE` |
| `1&2`, `"a"&1.5&TRUE` | `"12"`, `"a1.5TRUE"` |
| `"3"+1`, `""+1`, `"x"+1`, `TRUE+1` | `4.0`, `1.0`, `VALUE`, `2.0` |
| `1<"a"`, `"a"<TRUE`, `"A"="a"`, `2="2"`, `TRUE<5` | `True`, `True`, `True`, `False`, `False` |
| blank A1: `A1+1`, `A1&"x"`, `A1=0`, `A1=""`, `A1` | `1.0`, `"x"`, `True`, `True`, `0.0` |
| `(1/0)+NOPE()`, `NOPE()+(1/0)`, `"a"+(1/0)` | `DIV0`, `NAME`, `DIV0` |
| `FOO`, `NOPE(1/0)`, `AAA1`, `A0`, `A1:A2+1` | `NAME`, `NAME`, `REF`, `REF`, `VALUE` |

## 6. functions
`FUNCTIONS: dict` (uppercase keys). `@register(name, *, lazy=False)` stores the function under `name.upper()`, returns it. `functions.LAZY` = set of lazy names. Normal function: `fn(*args)`, each arg a scalar Value or a `list` (range). It validates its own arity (`VALUE` if wrong) and never raises. Lazy function (built-in: only `IF`): each arg is a zero-argument callable returning that argument's evaluated Value/list; call only what is needed.

Order: arity, then the FIRST error among args (left to right; row-major inside a range) is returned, then coercion. Only `SUM AVERAGE MIN MAX COUNT AND OR CONCAT` accept ranges; any other function given a list -> `VALUE`.

| Fn | Arity | Rule |
|---|---|---|
| `SUM` | >=1 | sum of collected numbers, left-to-right `+` from `0.0`; none -> `0.0` |
| `AVERAGE` | >=1 | sum/count; count 0 -> `DIV0` |
| `MIN` `MAX` | >=1 | none -> `0.0` |
| `COUNT` | >=1 | count of collected numbers (float) |
| `ROUND(x,n)` | 2 | `to_number` both; `n` truncated toward 0; round `Decimal(repr(x))` at `n` digits half AWAY from zero (`ROUND_HALF_UP`), to float; `-0.0` -> `0.0` |
| `ABS(x)` | 1 | `abs(to_number(x))` |
| `IF(c,a[,b])` | 2-3 | lazy; `c` error -> it; `to_bool(c)`; evaluate only the chosen branch; list result/cond -> `VALUE`; missing `b` and false -> `False` |
| `AND` `OR` | >=1 | collected bools: all/any; none collected -> `VALUE`; no short-circuit |
| `NOT(x)` | 1 | `not to_bool(x)` |
| `CONCAT` | >=1 | join `to_text` of scalars and of every range element (error element -> that error) |
| `LEN(s)` | 1 | `float(len(to_text(s)))` |
| `UPPER` `LOWER` | 1 | `.upper()`/`.lower()` of `to_text` |
| `LEFT(s[,n])` `RIGHT` | 1-2 | `n` default 1, `to_number` truncated toward 0; `n<0` -> `VALUE`; `n>=len` -> all; `n=0` -> `""` |

Collection, `SUM AVERAGE MIN MAX COUNT`: in a range only floats count (text, bool, Empty skipped). Scalars: float counts; bool counts as 1/0; Empty skipped; `""` skipped; other str counts if `to_number` succeeds, else `VALUE` (`COUNT`: skipped). So `SUM(A1)` with text in A1 is `VALUE`. `AND OR`: range: bool as is, float `!=0`, text/Empty skipped; scalar: `to_bool`, Empty skipped.

| Formula | Value |
|---|---|
| `SUM(1,2,3)`, `SUM()`, `SUM("2",TRUE)`, `SUM("x")` | `6.0`, `VALUE`, `3.0`, `VALUE` |
| `SUM(A1:A3)`, A1=1 A2="x" A3 blank / A2=`#DIV/0!` | `1.0` / `DIV0` |
| all-blank `AVERAGE(A1:A3)`, `MAX(A1:A3)` | `DIV0`, `0.0` |
| `AVERAGE(1,2)`, `MIN(3,-1,2)`, `COUNT(A1:A4)` over 1,"x",TRUE,blank | `1.5`, `-1.0`, `1.0` |
| `ROUND(2.5,0)`, `(-2.5,0)`, `(2.675,2)`, `(1234,-2)` | `3.0`, `-3.0`, `2.68`, `1200.0` |
| `ROUND(1)`, `ABS(-3)`, `ABS("-2")` | `VALUE`, `3.0`, `2.0` |
| `IF(1,"y","n")`, `IF(0,"y")`, `IF(TRUE,1,1/0)`, `IF("x",1,2)`, `IF(1/0,1,2)` | `"y"`, `False`, `1.0`, `VALUE`, `DIV0` |
| `AND(TRUE,1)`, `OR(0,FALSE)`, `AND(A1:A2)` (blank), `NOT("true")` | `True`, `False`, `VALUE`, `False` |
| `CONCAT("a",1,A1:A2)` (A1 blank, A2="z"), `LEN(12.50)`, `UPPER("aB")`, `LOWER(TRUE)` | `"a1z"`, `4.0`, `"AB"`, `"true"` |
| `LEFT("hello",2)`, `LEFT("hello")`, `RIGHT("hello",9)`, `RIGHT("hello",0)`, `LEFT("a",-1)` | `"he"`, `"h"`, `"hello"`, `""`, `VALUE` |

## 7. workbook
`Workbook()`. `ref_str` goes through `parse_ref` (any case, `$` ignored); a bad one raises `ValueError`, no change made.
- `set(ref_str, raw, *, literal=False)`. Classification in order: (1) `""` clears the cell; (2) first char `=` -> formula, body `raw[1:]`; (3) stripped raw matches the `to_number` grammar (finite) -> float; (4) stripped raw upper-cased is `TRUE`/`FALSE` -> bool; (5) else the string, unchanged. `literal=True` skips 2-4 (used by CSV).
- `get(ref_str) -> Value` (`Empty` if blank); `raw(ref_str) -> str` exactly as given (`""` if blank); `cells() -> list[str]`: canonical addresses (uppercase, no `$`) of non-empty cells, sorted by row then column.
- `recalc_count`: cumulative number of formula-cell evaluations. `last_changed -> list[str]`: the cells recomputed by the latest `set` (the cell first, then dependents, topological order; `[]` initially).
- A formula that does not parse keeps its raw, is `VALUE`, has no dependencies, and still counts as one evaluation per recompute.

**Dependencies** are static: every `CellRef` and every cell of every `RangeRef` anywhere in the AST (even an untaken `IF` branch or the args of an unknown function); `BadRef` adds none. A range depends on every cell in its rectangle, including cells blank now and set later.

**Recalc.** `set` computes D = the cell plus all transitive dependents, then evaluates each formula cell of D exactly once in topological order (+1 `recalc_count` each). A constant or cleared cell adds 0. No early cut-off; an identical raw still recalculates. `last_changed` = D.

**Cycles.** A cell is circular if on a cycle (self-reference and a range containing itself count) or transitively depending on a cycle cell. A circular cell is `CIRC` whatever its formula and is not evaluated (adds 0). Changing a cycle member so the cycle breaks recomputes all former members and dependents, which recover correct values.

Example 1 (fresh `wb`; Count = `recalc_count` after the call):

| Call | Count | Values afterwards |
|---|---|---|
| `set("A1","1")` | 0 | A1=1.0 |
| `set("B1","=A1+1")` | 1 | B1=2.0 |
| `set("C1","=B1*2")` | 2 | C1=4.0 |
| `set("A1","5")` | 4 | B1=6.0, C1=12.0 |
| `set("C1","=A1")` | 5 | C1=5.0 (B1 untouched) |
| `set("D1","=SUM(A1:A3)")` | 6 | D1=5.0 |
| `set("A3","9")` | 7 | D1=14.0 (A3 was blank) |
| `set("E1","=B1+C1")` | 8 | E1=11.0 |
| `set("A1","1")` | 12 | B1,C1,D1,E1 once each; E1=3.0 |
| `set("A1","")` | 16 | B1=1.0, C1=0.0, D1=9.0, E1=1.0 |
| `set("F1","=1+")` | 17 | F1=`VALUE`, raw `"=1+"` |

Example 2 (fresh `wb`): `set("A1","=B1")` -> count 1, A1=0.0. `set("B1","=A1")` -> A1,B1 `CIRC`, count 1. `set("C1","=A1+1")`, `set("D1","=C1")` -> `CIRC`, count 1. `set("B1","5")` -> count 4: A1=5.0, C1=6.0, D1=6.0. A self-reference (`A1` = `=A1+1`) is `CIRC`, count +0.
Example 3: raw `"007"` -> `get` 7.0, `raw` `"007"`; `" true "` -> `True`; `" =1"`, `"1,5"` -> strings; `"="` -> `VALUE`.

## 8. csvio
UTF-8, delimiter `,`, quote `"` (doubled inside), records end `\n` on write; read accepts `\n`, `\r\n`, `\r`, and quoted fields may contain them.
- `load_csv(path, formulas=True) -> Workbook`: record i, field j -> cell (col j, row i), first field = `A1`. Each non-empty field is `wb.set(ref, field)` (raw rules apply); empty fields skipped; a blank record still occupies a row. `formulas=False`: `=`-fields use `literal=True` (value and raw = the text). Out of A1..ZZ9999 -> `ValueError`; missing file -> `FileNotFoundError`. `recalc_count` after load: unspecified.
- `save_csv(wb, path, values=True)`: records for rows 1..last non-empty row; each lists columns A..last non-empty column of THAT row; a row without cells is the line `\n`. A field is quoted iff it contains `,` `"` `\n` or `\r`. Empty workbook -> empty file. Field text: `values=True`: `to_text` of the value, error -> its code; `values=False`: `wb.raw(ref)`.

| Case | Output / result |
|---|---|
| A1=`1`, B1=`=A1/4`, A2=text `say "hi", ok`, C2=`x` | `1,0.25\n"say ""hi"", ok",,x\n` |
| load `a,"b\nc"\n,=A1&"!"\n` | A1=`a`, B1=`"b\nc"`, B2=`"a!"`; with `formulas=False` B2=`=A1&"!"` text |

## 9. cli
`main(argv=None, stdin=None, stdout=None) -> int` (defaults from `sys`). Output: `\n`-terminated lines to `stdout`, flushed.
- `argv==[]`: REPL over `stdin` lines (stripped; blank ignored; no prompt). `argv[0]=="serve"`: section 10. Other argv: print `ERR usage: python -m minisheet [serve --port N [--load FILE]]`, return 2.
- Commands (name case-insensitive; args split on whitespace; REF = `parse_ref`; RANGE = `parse_range` or one cell):

| Command | Effect / output |
|---|---|
| `set REF [RAW]` | RAW = rest of line after REF, leading space stripped (may contain spaces; absent = `""`). Prints `OK` |
| `get REF` | float via `format_number`, bool `TRUE`/`FALSE`, str as is, error code; blank cell -> empty line |
| `show RANGE` | the grid below |
| `load PATH` | `load_csv(PATH)` replaces the workbook (PATH = rest of line). `OK` |
| `save [--raw] PATH` | `save_csv(wb,PATH,values=not raw)`. `OK` |
| `quit` | stop, no output (args ignored) |

- Errors print one line, processing continues: `ERR unknown command: <word as typed>`; wrong argument count: `ERR usage: <u>`, `<u>` = the command's synopsis in the table; `ERR bad reference: <token as typed>`; `OSError`/`ValueError` in load/save: `ERR cannot load: <PATH>` / `ERR cannot save: <PATH>`.
- Exit code at `quit`/end of input: `0` if no `ERR` line was printed, else `2`.

**show grid.** L = width of the largest row number. W_c = max(len(column letters), longest cell text in column c). Cell text: float `f"{x:.2f}"`; bool `TRUE`/`FALSE`; str with each `\n`,`\r` -> one space; error code; blank `""`. Floats right-aligned, everything else left-aligned. Header line = `" "*L` + per column `" "` + letters right-aligned to W_c. Row line = row number right-aligned to L + per column `" "` + text aligned to W_c. Nothing stripped.

A1=`1.5`, B1=`hi`, C1=`=A1*2`, A2=`=1/0`, B2=`TRUE`, C2=`=A1*100`; `show A1:C2` prints exactly (L=1, W=7,4,6):
```
        A    B      C
1    1.50 hi     3.00
2 #DIV/0! TRUE 150.00
```
Also: `set A1 3` -> `OK`, `get A1` -> `3`; `get AAA1` -> `ERR bad reference: AAA1` (exit 2).

## 10. server (P5)
`python -m minisheet serve --port N [--load FILE]` (any option order; `--port` required, 0 = free port): `load_csv(FILE)` if given (failure: `ERR cannot load: FILE`, return 2); bind `127.0.0.1`; print exactly one line `Serving on http://127.0.0.1:<actual port>` (flushed); serve until killed (`KeyboardInterrupt` -> 0). Bad/missing `--port`: `ERR usage: serve --port N [--load FILE]`, return 2. `server.create_server(wb, port=0)` returns the `HTTPServer`. Stdlib `http.server`, requests serialized by a lock, nothing else on stdout, query strings ignored. Any other method/path -> 404 `{"error":"not found"}`. JSON is UTF-8; success is 200.

**Cell** = `{"raw": str, "value": V, "display": str}`. V: float -> JSON number; str; bool -> `true`/`false`; `Empty` -> `null`; error -> `{"error":"#DIV/0!"}`. `display` = the show-grid cell text (section 9). `cells`/`changed` keys are canonical addresses.

| Request | Response |
|---|---|
| `GET /` | `text/html; charset=utf-8`, bytes of `static/index.html` |
| `GET /api/cells` | `{"cells":{ref:Cell,...}}`, non-empty cells only |
| `POST /api/cells` `{"ref","raw"}` | `{"changed":{ref:Cell}}` = exactly `last_changed`; a cleared cell is `{"raw":"","value":null,"display":""}` |
| `GET /api/csv` | `text/csv; charset=utf-8`, `save_csv(values=True)` content |
| `POST /api/csv` (UTF-8 CSV body) | replaces the workbook as `load_csv(formulas=True)`; responds like `GET /api/cells` |

400 `{"error":msg}` (state unchanged): body not a JSON object -> `invalid JSON`; `ref`/`raw` missing or not str -> `ref and raw must be strings`; bad ref -> `bad reference: <ref as sent>`; bad CSV (undecodable/out of bounds) -> `invalid CSV`.

Examples (fresh server):
1. `POST /api/cells {"ref":"A1","raw":"2"}` -> `{"changed":{"A1":{"raw":"2","value":2.0,"display":"2.00"}}}`.
2. `{"ref":"b1","raw":"=A1*2"}` -> `changed` = `{"B1":{"raw":"=A1*2","value":4.0,"display":"4.00"}}`; then `{"ref":"A1","raw":"5"}` -> `changed` has exactly `A1` (5.0) and `B1` (10.0, display `"10.00"`).
3. `{"ref":"C1","raw":"=1/0"}` -> C1 = `{"raw":"=1/0","value":{"error":"#DIV/0!"},"display":"#DIV/0!"}`; raw `TRUE` -> value `true`, display `"TRUE"`.
4. `{"ref":"AAA1","raw":"1"}` -> 400 `{"error":"bad reference: AAA1"}`; body `not json` -> 400 `{"error":"invalid JSON"}`.

## 11. web UI (P6): `static/index.html`
One file, inline vanilla JS + CSS, no CDN, no build; relative API URLs.

**DOM.** `<table id="grid" tabindex="0">`; header row of `<th>` A..Z (first empty); each body row: row-number `<th>` (1..50) then `<td data-ref="A1">`..`<td data-ref="Z50">` (1300 `td[data-ref]`, no other `data-ref`). `#cell-name` (text = selected ref), `#formula-bar` (`<input type="text">`, value = raw), `#status` (empty by default). `<body data-ready="true">` once the initial load rendered.

**Rendering.** td text = `display` (`""` if blank). Float value: class `num` and `text-align:right`; all else `text-align:left`. Error value: class `error`. One td has `selected`.

**Behaviour.**
- Load: fetch `/api/cells`, render, select A1, focus `#grid`.
- Select (click, arrow, commit move): set `selected`, `#cell-name`, bar := that cell's raw (`""` if blank; uncommitted text discarded); a click focuses `#grid`.
- Enter in bar: POST `{ref: selected, raw: bar}`. On 200: apply every `changed` entry to its td and the local raw store, `#status` := `""`, select the cell below (stay on row 50), focus `#grid`. Tab in bar: `preventDefault`, same commit, select the cell right (stay on Z). No page reload ever.
- Non-2xx or network failure: `#status` := response `error` (else `HTTP <code>`); selection and bar unchanged, bar keeps focus.
- Escape in bar: bar := selected raw, focus `#grid`. Double-click a td: select it, focus the bar.
- `keydown` with `key.length===1`, no ctrl/meta/alt, while `#grid` (not the bar) is focused: `preventDefault`, bar := that char, focus bar, caret at end.
- Arrow keys while the bar is not focused: `preventDefault`, move one cell, clamped to A1..Z50.

| Action | Resulting state |
|---|---|
| Page load, empty workbook | 1300 tds with empty text; A1 has `selected`; `#cell-name`=`A1`; bar value `""` |
| Bar `2`, Enter | A1 text `2.00`, class `num`, computed `text-align:right`; A2 `selected`; `#cell-name`=`A2` |
| A1: bar `=1/0`, Enter; later A1 := `7` | A1 `#DIV/0!` with class `error`, no `num`; then `7.00`, no `error` |
| Click B1 (`=A1*2`); ArrowUp; ArrowLeft x2 | `#cell-name`=`B1`, bar `=A1*2` (raw); then B1, A1, A1 selected |
| Grid focused, press `x` | bar value `x`, bar is the active element |
| POST fails 400 `{"error":"bad reference: X"}` | `#status`=`bad reference: X`; selection unchanged |
| A1 selected, type `5` in bar, Tab | A1 `5.00`; B1 `selected` |

## 12. Test harness
UI tests start `python -m minisheet serve --port <free port>` as a subprocess (waiting for the `Serving on` line) and drive it with Playwright (Python, headless Chromium).
