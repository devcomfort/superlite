# Mini spreadsheet engine: a 10-step task

Build `solution.py` (Python ≥ 3.12, stdlib only) with a class `Sheet`. Work through the steps **in order**. Each step builds on the earlier ones, and later steps must not break earlier behavior. After each step, write tests for it and run the suite: `uv run --no-project --with pytest python -m pytest -q`.

Cells are named by one column letter `A`–`Z` and a row number `1`–`999`, e.g. `B12`. Cell names in the API are always uppercase.

## Step 1: storage
- `set(cell, raw: str)` stores raw input.
  - `""` clears the cell.
  - Raw matching `-?\d+` is an int.
  - Raw matching `-?\d+\.\d+` is a float.
  - A raw starting with `=` is a formula.
  - Anything else is text.
- `get(cell)` returns the cell's value: int, float or str for text, an error string (see step 3), or `None` for an empty cell.
- `raw(cell)` returns the stored raw string (`""` when empty).

## Step 2: formulas
- After `=` comes an expression: int/float literals, cell references, `+ - * /`, unary `-`, and parentheses. Usual precedence applies, with left associativity. Whitespace is allowed anywhere between tokens.
- An empty referenced cell counts as `0`.
- `+`, `-` and `*` on two ints give an int; any float makes a float. `/` always gives a float.
- Example: A1=`2`, A2=`=A1*3+1` → `get("A2") == 7`.

## Step 3: error values
- Values may be the error strings `"#DIV/0!"`, `"#VALUE!"`, `"#REF!"` or `"#CYCLE!"`.
- Text used in arithmetic → `#VALUE!`. Division by zero → `#DIV/0!`.
- If any operand of an operation is an error, the result is that error. When both operands are errors, the **left** one wins.
- A formula referencing a cell whose value is an error gets that error.
- A formula that doesn't parse evaluates to `#VALUE!`. Its raw is still stored.

## Step 4: recalculation
- `get` always reflects the current contents of every cell. Changing a cell changes every cell that depends on it, directly or transitively.

## Step 5: functions
- `SUM`, `MIN`, `MAX`, `AVG`, `COUNT` (uppercase), e.g. `=SUM(A1:B3, C1*2, 5)`.
- Arguments are ranges (`A1:B3`: a rectangle, corners in any order) or expressions.
- Within ranges, empty cells and text cells are **skipped**. An error in any argument, or in any cell of a range, makes the function return that error, with the first argument and the first cell in row-major order winning.
- `COUNT` counts numeric values.
- `SUM` of nothing = 0. `MIN` and `MAX` of nothing = 0. `AVG` of nothing = `#DIV/0!`.
- `AVG` is always a float. `SUM`, `MIN` and `MAX` keep int when every value is int.
- Functions nest and can appear inside expressions: `=1+MAX(A1:A3)*2`.

## Step 6: cycles
- A cell that is part of a reference cycle (including a self-reference, or a range containing itself) has the value `#CYCLE!`.
- A cell that depends on a cycle cell, without being part of the cycle, also gets `#CYCLE!` (it propagates like any other error).
- Breaking the cycle (by changing any cell in it) restores normal values everywhere.

## Step 7: absolute references and copy
- References may carry `$`: `$A$1`, `A$1`, `$A1`. They evaluate exactly like `A1`.
- `copy(src, dst)` copies `src`'s raw to `dst`. In a formula, each **relative** part shifts by the offset (Δcolumn, Δrow) from `src` to `dst`, and `$`-marked parts stay fixed.
- A shifted reference that falls outside `A`–`Z` or below row 1 becomes the text `#REF!` in the formula and evaluates to `#REF!`. A range with either corner out of bounds becomes `#REF!` as a whole.
- References are rewritten in place. Every other character of the formula (spacing, function names, numbers) is preserved exactly.
- Example: A1=`1`, B1=`=A1+$A$1`; `copy("B1", "C2")` → `raw("C2") == "=B2+$A$1"`.

## Step 8: insert rows
- `insert_rows(at, n)`: every cell in row ≥ `at` moves down by `n` (contents move with their cells).
- **Every** reference anywhere in the sheet, absolute or relative, that points to a row ≥ `at` is incremented by `n`.
- A range whose rows span across `at` (top < at ≤ bottom) grows: its bottom moves, its top doesn't.
- Values recompute.
- Example: A1=`1`, A2=`2`, A3=`=SUM(A1:A2)`; `insert_rows(2, 1)` → `raw("A4") == "=SUM(A1:A3)"`, `get("A4") == 3`.

## Step 9: delete rows
- `delete_rows(at, n)` removes rows `at … at+n−1`. Rows below move up by `n`.
- References to a deleted cell become `#REF!` in the formula text.
- References to rows below the deleted block shift up by `n`.
- A range that loses only some of its rows shrinks to cover the remaining rows, shifted. A range whose rows are all deleted becomes `#REF!`.
- Values recompute.
- Example: A1..A5 = `1`..`5`, B1=`=SUM(A1:A5)`; `delete_rows(2, 2)` → `raw("B1") == "=SUM(A1:A3)"`, `get("B1") == 1+4+5`.

## Step 10: undo and redo
- Each `set`, `copy`, `insert_rows` and `delete_rows` is one undoable action.
- `undo()` restores the exact state before the most recent action, all raws and therefore all values, and returns True. With nothing to undo it returns False.
- `redo()` re-applies the most recently undone action and returns True. With nothing to redo it returns False.
- Any new action clears the redo history.
