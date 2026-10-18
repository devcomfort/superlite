"""build_shape_audit on a fixture plan: edge classes, pruning, the what-if schedule, ruling counts."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
import build_shape_audit as bsa  # noqa: E402
import harness  # noqa: E402

PLAN = """# Plan

## Task graph

```mermaid
flowchart LR
  A[a] --> B[b]
  %% taskgraph
  T1 --> T2
  T1 --> T3
  T1 --> T4
  T5 --> T6
```

### T1 core
**Owns:** src/core/a.py, tests/core/test_a.py
**Components:** 1
**LOC owned:** 100
**Tests:** fast
**Produces:** core.a.load(path: str) -> str · core.a.dump(x: str) -> None

### T2 uses names that have Produces lines
**Owns:** src/util/b.py
**Components:** 1
**LOC owned:** 100
**Tests:** fast
**Consumes:** core.a.load(path: str) -> str (T1)

### T3 uses a name nobody produced
**Owns:** src/util/c.py
**Components:** 1
**LOC owned:** 100
**Tests:** fast
**Consumes:** core.a.parse(x: str) -> int (T1)

### T4 docs after code
**Owns:** docs/guide.md
**Components:** 1
**LOC owned:** 20
**Tests:** fast

### T5 engine
**Owns:** src/engine/e.py
**Components:** 3
**LOC owned:** 300
**Tests:** fast
**Produces:** engine.e.run(x: str) -> int

### T6 front end
**Owns:** src/engine/f.py
**Components:** 1
**LOC owned:** 100
**Tests:** fast
**Consumes:** engine.e.run(x: str) -> int (T5)

Ruling: sequential - engine front ends are tested through the real engine - longer critical path.
"""


def load(tmp_path):
    p = tmp_path / "plan.md"
    p.write_text(PLAN, encoding="utf-8")
    plan = bsa.pt.Plan(PLAN, p)
    return p, plan, bsa.pt.parse_taskgraph(plan)


def test_edge_classes(tmp_path):
    _, plan, graph = load(tmp_path)
    cls = {(e["producer"], e["consumer"]): e for e in bsa.classify_edges(plan, graph)}
    assert cls[("T1", "T2")]["class"] == "removable"
    assert cls[("T1", "T3")]["class"] == "missing_produces" and cls[("T1", "T3")]["missing"]
    assert cls[("T1", "T4")]["class"] == "ordering"
    # the ruling names the engine package both tasks own files in: held although the names have Produces lines
    assert cls[("T5", "T6")]["class"] == "real_ruling" and cls[("T5", "T6")]["class_without_ruling"] == "removable"


def test_longest_path_and_pruned_copy(tmp_path):
    p, plan, graph = load(tmp_path)
    assert bsa.longest_path(graph, {t: 1.0 for t in graph}) == (2.0, ["T1", "T2"]) or bsa.longest_path(graph, {t: 1.0 for t in graph})[0] == 2.0
    text = bsa.pruned_text(p, graph, {("T1", "T2")})
    g2 = bsa.pt.parse_taskgraph(bsa.pt.Plan(text))
    assert "T1" not in g2["T2"] and g2["T3"] == ["T1"] and set(g2) == set(graph)
    assert p.read_text(encoding="utf-8") == PLAN       # the original is never touched


def test_plan_report_whatif_schedule(tmp_path):
    p, _, _ = load(tmp_path)
    rep = bsa.plan_report(p)
    assert rep["edge_classes"] == {"removable": 1, "missing_produces": 1, "ordering": 1, "real_ruling": 1}
    assert rep["base"]["critical_path_min"] >= rep["pruned_removable_and_missing"]["critical_path_min"] > 0
    assert rep["pruned_removable"]["critical_path_min"] <= rep["base"]["critical_path_min"]
    assert rep["split_multi_component"]["tasks_split"] == ["T5"]
    assert rep["split_multi_component"]["critical_path_min_uncapped"] <= rep["split_multi_component"]["baseline_uncapped_min"]


def test_ruling_counts_from_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "RESULTS", tmp_path)
    plan_path = "C:/r/docs/plans/p.md"
    ev = lambda name, inp, i: {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"u{i}", "name": name, "input": inp}]}}  # noqa: E731
    events = [ev("Write", {"file_path": plan_path, "content": "x\nRuling: sequential - a\n"}, 1),
              ev("Edit", {"file_path": plan_path, "old_string": "x", "new_string": "x\n- Ruling: sequential - b"}, 2),
              ev("Write", {"file_path": plan_path, "content": "x\nRuling: sequential - a\n- Ruling: sequential - b\nRuling: sequential - c\n"}, 3),
              ev("Edit", {"file_path": "C:/r/src/x.py", "old_string": "", "new_string": "Ruling: sequential"}, 4)]
    (tmp_path / "run1.jsonl").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    assert bsa.rulings("run1") == {"first_draft": 1, "added_after": 2, "removed_after": 0, "final": 3}
    assert bsa.rulings("missing") is None
