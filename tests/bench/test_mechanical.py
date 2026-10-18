"""Mechanical-task metrics (bench/mechanical.py, report_mechanical.py) from synthetic streams and plans:
no network, no agents."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
import harness  # noqa: E402
import mechanical  # noqa: E402
import report_mechanical  # noqa: E402

PLAN = """# Plan

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
**Components:** 1
**LOC owned:** 80
**Tests:** fast
**Model:** haiku
**Kind:** mechanical

### T2 beta
**Owns:** src/b.py
**Components:** 1
**LOC owned:** 200
**Tests:** fast
**Model:** sonnet

### T3 gamma
**Owns:** src/c.py
**Components:** 2
**LOC owned:** 300
**Tests:** fast
**Model:** sonnet
"""

T0 = 1_000_000.0


def stamp(sec):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(T0 + sec, timezone.utc).isoformat().replace("+00:00", "Z")


class Stream:
    def __init__(self):
        self.ev, self.n = [], 0

    def agent(self, aid, desc, sub, prompt, start, end, model, status="DONE", tools=2, out=100, note=True, text=None):
        tuid = f"toolu_{aid}"
        self.ev.append({"type": "assistant", "timestamp": stamp(start), "message": {"id": f"c{aid}", "content": [
            {"type": "tool_use", "id": tuid, "name": "Agent", "input": {"description": desc, "subagent_type": sub}}]}})
        self.ev.append({"type": "system", "subtype": "task_started", "task_id": aid, "tool_use_id": tuid,
                        "description": desc, "subagent_type": sub, "prompt": prompt, "task_type": "local_agent"})
        for i in range(tools):
            self.n += 1
            self.ev.append({"type": "assistant", "parent_tool_use_id": tuid,
                            "timestamp": stamp(start + (end - start) * (i + 1) / (tools + 1)),
                            "message": {"id": f"m{self.n}", "model": f"claude-{model}-5-5",
                                        "content": [{"type": "tool_use", "id": f"u{self.n}", "name": "Bash", "input": {"command": "x"}}],
                                        "usage": {"input_tokens": 10, "output_tokens": out, "cache_read_input_tokens": 1000,
                                                  "cache_creation_input_tokens": 500,
                                                  "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 500}}}})
        self.ev.append({"type": "assistant", "parent_tool_use_id": tuid, "timestamp": stamp(end),
                        "message": {"id": f"f{aid}", "model": f"claude-{model}-5-5", "content": [{"type": "text", "text": f"Status: {status}"}],
                                    "usage": {"input_tokens": 1, "output_tokens": 5}}})
        if note:
            self.ev.append({"type": "system", "subtype": "task_notification", "task_id": aid, "tool_use_id": tuid, "status": "completed",
                            "handback_report": {"text": text or f"Status: {status}"}})


def run(tmp_path, t1_end=60.0, t2_end=100.0, t1_status="DONE", fix=False, kind_miss=False, text=None):
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "p.md").write_text(PLAN, encoding="utf-8")
    s = Stream()
    s.agent("a1", "Implementer A (T1)", "superlite:implementer-haiku", "Task T1 alpha", 10, t1_end, "haiku", t1_status, tools=4, text=text)
    s.agent("a2", "Implementer B (T2)", "superlite:implementer", "Task T2 beta", 10, t2_end, "sonnet", tools=6)
    end1 = t1_end
    if fix:
        s.agent("f1", "Fix T1 alpha", "superlite:fixer-sonnet", "Fix finding F-T1-1 in src/a.py", t1_end + 1, t1_end + 21, "sonnet")
        end1 = t1_end + 21
    if kind_miss:
        sl = tmp_path / ".superlite"
        sl.mkdir()
        (sl / "incidents.jsonl").write_text(json.dumps({"kind": "assumption", "context": "kind-miss T1 red tests"}) + "\n")
    s.agent("a3", "Implementer C (T3)", "superlite:implementer", "Task T3 gamma", max(end1, t2_end) + 2, max(end1, t2_end) + 42, "sonnet")
    d = harness.dispatch_stats(s.ev, tmp_path)["dispatches"]
    tasks, block = harness.mechanical_score(tmp_path, s.ev, d)
    return {t["task"]: t for t in tasks}, block


def test_haiku_first_time_pass_tokens_cost_and_tools(tmp_path):
    t, block = run(tmp_path)
    h = t["T1"]
    assert h["model"] == "haiku" and h["kind"] == "mechanical" and h["dispatches"] == 1
    assert (h["start_s"], h["end_s"], h["duration_s"]) == (0.0, 50.0, 50.0)  # times are relative to the first event
    assert h["tool_calls"] == 4 and h["status"] == "DONE" and h["first_time_pass"] is True
    assert h["tokens"]["in"] == 4 * 10 + 1 and h["tokens"]["cache_read"] == 4000 and h["tokens"]["cache_write_1h"] == 2000
    haiku = harness.PRICES["haiku"]
    assert abs(h["cost_usd"] - (41 * haiku[0] + h["tokens"]["out"] * haiku[1] + 4000 * haiku[4] + 2000 * haiku[3])) < 1e-6
    assert h["rework_s"] == 0 and h["rework_cost"] == 0
    assert block["haiku"]["first_time_pass_rate"] == 1.0
    assert block["by_kind"]["mechanical"] == {"tasks": 1, "loc": 80, "task_share": 0.333, "loc_share": 0.138}
    assert block["plan_tasks"] == 3 and block["plan_mechanical"] == 1


def test_rework_by_fixer_and_kind_miss_incident(tmp_path):
    t, block = run(tmp_path, t1_status="NEEDS_CONTEXT", fix=True, kind_miss=True,
                   text="Status: NEEDS_CONTEXT\nThe spec for a() is ambiguous.")
    h = t["T1"]
    assert h["first_time_pass"] is False and h["rework_dispatches"] == 1 and h["kind_miss_incidents"] == 1
    assert h["rework_s"] == 20.0 and h["rework_cost"] > 0
    assert h["status"] == "NEEDS_CONTEXT" and "ambiguous" in h["status_reason"]
    assert block["haiku"]["needs_context_or_blocked"] == 1 and "T1" in block["haiku"]["stuck_reasons"]
    assert block["haiku"]["rework_cost_usd"] == round(h["rework_cost"], 4)


def test_kind_miss_alone_defeats_first_time_pass(tmp_path):
    t, _ = run(tmp_path, kind_miss=True)
    assert t["T1"]["first_time_pass"] is False and t["T1"]["rework_dispatches"] == 0


def test_critical_path_slack_lag_and_counterfactual(tmp_path):
    # T1 (Haiku) ends at 60, T2 at 100: T1 is off the critical path with 42 s slack
    t, block = run(tmp_path)
    assert t["T1"]["on_critical_path"] is False and t["T2"]["on_critical_path"] is True
    assert t["T1"]["slack_s"] == 40.0 and t["T2"]["slack_s"] == 0.0
    assert t["T3"]["start_lag_s"] == 2.0 and t["T3"]["on_critical_path"] is True
    cf = block["counterfactual_sonnet"]
    assert cf["LABEL"].startswith("COUNTERFACTUAL ESTIMATE") and cf["off_critical_path_tasks"] == ["T1"]
    assert cf["haiku_saves_cost_usd"] > 0 and cf["sum_task_time_saved_s"] > 0
    assert cf["critical_path_saved_s"] == 0.0  # slack absorbs the slower Sonnet run
    # T1 now finishes last: the same saving moves the run end
    t2, block2 = run(tmp_path / "b", t1_end=100.0, t2_end=60.0)
    assert t2["T1"]["on_critical_path"] is True and t2["T2"]["on_critical_path"] is False
    assert block2["counterfactual_sonnet"]["critical_path_saved_s"] > 0


def test_run_without_haiku_says_so(tmp_path):
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    (tmp_path / "docs" / "plans" / "p.md").write_text(PLAN.replace("**Model:** haiku", "**Model:** sonnet"), encoding="utf-8")
    s = Stream()
    s.agent("a2", "Implementer B (T2)", "superlite:implementer", "Task T2 beta", 10, 50, "sonnet")
    tasks, block = harness.mechanical_score(tmp_path, s.ev, harness.dispatch_stats(s.ev, tmp_path)["dispatches"])
    assert block["haiku"] is None and block["note"] == "no Haiku tasks in this run"
    assert block["by_model"]["sonnet"]["tasks"] == 1 and block["tasks_built"] == 1


def test_report_rows_and_summary(tmp_path):
    t, block = run(tmp_path)
    p = tmp_path / "score.json"
    p.write_text(json.dumps({"run": "r1", "tasks": list(t.values()), "mechanical": block}), encoding="utf-8")
    q = tmp_path / "none.json"
    q.write_text(json.dumps({"run": "r2", "tasks": [], "mechanical": {"tasks_built": 0, "haiku": None, "note": "no Haiku tasks in this run"}}))
    runs = report_mechanical.load([str(p), str(q)])
    text = report_mechanical.render(runs)
    assert "r1" in text and "no Haiku tasks in this run" in text and "COUNTERFACTUAL ESTIMATE" in text
    s = report_mechanical.summary(runs)
    assert s["runs"] == 2 and s["runs_with_haiku"] == 1 and s["first_time_pass_rate"] == 1.0
