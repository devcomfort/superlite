from __future__ import annotations


class Workbook:
    def __init__(self) -> None:
        self.cells: dict[str, str] = {}

    def set(self, ref: str, raw: str) -> list[str]:
        self.cells[ref] = raw
        return [ref]

    def get(self, ref: str):
        return self.cells.get(ref)
