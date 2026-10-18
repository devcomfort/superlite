from __future__ import annotations

from minisheet.evaluator import evaluate


def render(text: str):
    return evaluate(text, lambda ref: ref)
