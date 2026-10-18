"""F7: per-task records (task_records) for `predict.py --refit`, from a fixture plan and dispatches."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
import harness  # noqa: E402

PLAN = """# Fixture Plan

## Task graph

```mermaid
flowchart LR
  T1[a] --> T3[c]
  T2[b] --> T3
  %% taskgraph
  T1 --> T3
  T2 --> T3
```

### T1 alpha
**Owns:** src/a.py
**Components:** 2
**LOC owned:** 300
**Tests:** fast
**Model:** sonnet

### T2 beta
**Owns:** src/b.py
**Components:** 1
**LOC owned:** 120
**Tests:** slow
**Model:** haiku

### T3 gamma
**Owns:** src/c.py
**Components:** 3
**LOC owned:** 400
**Tests:** fast
"""


def disp(desc, start, end, kind="superlite:implementer", model="sonnet-5-5"):
    return {"subagent_type": kind, "description": desc, "model": model, "start_s": start, "end_s": end}


def test_task_records_join_sum_and_skip(tmp_path):
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "p.md").write_text(PLAN, encoding="utf-8")
    dispatches = [
        disp("T1 alpha", 10.0, 70.0),
        disp("T1 alpha fix", 100.0, 130.0),            # re-dispatch: durations sum
        disp("T2 beta", 12.0, 52.0),
        disp("T9 ghost", 0.0, 5.0),                    # not in the plan: skipped
        disp("Review alpha", 80.0, 99.0, "superlite:reviewer"),  # not an implementer
        disp("T3 gamma", 80.0, 140.0),
    ]
    recs = {r["task"]: r for r in harness.task_records(tmp_path, dispatches)}
    assert set(recs) == {"T1", "T2", "T3"}
    assert recs["T1"] == {"task": "T1", "components": 2, "loc": 300, "tests": "fast",
                          "kind": "design", "model": "sonnet", "actual_s": 90.0}
    assert recs["T2"]["tests"] == "slow" and recs["T2"]["model"] == "haiku" and recs["T2"]["actual_s"] == 40.0
    assert recs["T3"]["model"] == "sonnet-5-5"  # no Model field: falls back to the dispatch's model


def test_task_records_without_plan(tmp_path):
    assert harness.task_records(tmp_path, [disp("T1 x", 0, 1)]) == []
