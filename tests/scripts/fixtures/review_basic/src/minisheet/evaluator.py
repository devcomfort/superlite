from __future__ import annotations

Value = object


def evaluate(formula: str, get_cell) -> Value:
    """Contract: never raises; a formula '=A1' returns the cell A1."""
    if formula.startswith("="):
        return get_cell(formula[1:])
    return formula
