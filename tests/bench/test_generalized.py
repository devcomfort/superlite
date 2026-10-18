"""Measurement tools between any models and agents: arms, baselines, selectors, group reports, history bridge."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
import history_import  # noqa: E402
import mechanical  # noqa: E402  (old name, aliased to taskmetrics)
import mechanical_ab as ab  # noqa: E402
import report_mechanical  # noqa: E402
import taskmetrics  # noqa: E402
from test_mechanical import run as fixture_run  # noqa: E402
from test_mechanical_ab import make_repo  # noqa: E402


def test_old_module_name_is_an_alias():
    assert mechanical is taskmetrics and mechanical.cost_of is taskmetrics.cost_of and mechanical._ts is taskmetrics._ts


def test_three_arm_dry_run(tmp_path, capsys):
    repo, _ = make_repo(tmp_path)
    ab.main([str(repo), "--dry-run", "--arms", "implementer-haiku:haiku:mini,implementer:sonnet,fixer-sonnet:opus", "--cost-cap", "1", "--n", "2"])
    cfg = json.loads(capsys.readouterr().out)
    assert cfg["arms"] == ["implementer-haiku:haiku:mini", "implementer:sonnet:full", "fixer-sonnet:opus:full"] and cfg["n"] == 2
    caps = cfg["per_run_cap_usd"]
    assert caps["fixer-sonnet:opus:full"] > caps["implementer:sonnet:full"] > caps["implementer-haiku:haiku:mini"]
    # 2 runs of each arm share the $1 cap by weight
    assert abs(sum(caps.values()) * 2 - 1.0) < 0.01
    # default grid is unchanged
    ab.main([str(repo), "--dry-run"])
    assert json.loads(capsys.readouterr().out)["arms"] == ["implementer-haiku:haiku:full", "implementer:sonnet:full"]


def test_arms_are_validated():
    with pytest.raises(ValueError, match="models.json"):
        ab.parse_arms("implementer:gpt-9", [], [])
    with pytest.raises(ValueError, match="agents/"):
        ab.parse_arms("nosuchagent:haiku", [], [])
    with pytest.raises(ValueError, match="agent:model"):
        ab.parse_arms("implementer", [], [])
    assert ab.agent_def("opus", "fixer-sonnet")["model"] == "opus"
    cmd = ab.claude_cmd("opus", "p", 0.5, "fixer-sonnet")
    assert cmd[cmd.index("--agent") + 1] == "fixer-sonnet" and json.loads(cmd[cmd.index("--agents") + 1])["fixer-sonnet"]["model"] == "opus"


def test_selector_and_task_selection(tmp_path):
    repo, _ = make_repo(tmp_path)
    plan = harness._run_plan(repo)
    assert [t.id for t in ab.pick_tasks(plan, None, "all")[0]] == ["T1", "T2"]
    assert [t.id for t in ab.pick_tasks(plan, None, "ids=T2")[0]] == ["T2"]
    assert [t.id for t in ab.pick_tasks(plan, None, "kind=design")[0]] == ["T2"]
    assert [t.id for t in ab.pick_tasks(plan, None, "tier=haiku")[0]] == ["T1"]
    with pytest.raises(ValueError):
        taskmetrics.parse_select("colour=red")


def _tasks_with_opus(tmp_path):
    t, _ = fixture_run(tmp_path)
    tasks = list(t.values())
    for x in tasks:
        x["agent_type"] = {"haiku": "implementer-haiku"}.get(x["model"], "implementer")
        x["group"] = taskmetrics.group_of(x)
    tasks[-1]["model"] = "opus"          # T3 now ran on an opus agent
    tasks[-1]["group"] = taskmetrics.group_of(tasks[-1])
    tasks[-1]["first_time_pass"] = False
    tasks[-1]["rework_cost"], tasks[-1]["rework_s"] = 0.05, 12.0
    return tasks


def test_report_groups_include_a_non_haiku_group(tmp_path):
    tasks = _tasks_with_opus(tmp_path)
    block = taskmetrics.mechanical_block(tasks, {}, harness.PRICES, harness.load_speeds(), None)
    assert set(block["groups"]) == {"implementer-haiku:haiku", "implementer:sonnet", "implementer:opus"}
    assert block["groups"]["implementer:opus"]["first_time_pass"] == 0 and block["groups"]["implementer:opus"]["rework_cost_usd"] == 0.05
    runs = [{"run": "r", "tasks": tasks, "mechanical": block}]
    text = report_mechanical.render(runs, focus={"opus"})
    assert "implementer:opus" in text and "implementer-haiku:haiku" in text and "0 of 1 focus tasks" not in text
    assert "1 of 1 focus tasks failed first time" in text
    assert "haiku_s" not in text and "haiku$" not in text   # columns are named after the group, not the model
    assert "COUNTERFACTUAL ESTIMATE" in text and "re-prices tokens only" in text


def test_baseline_other_than_sonnet(tmp_path):
    tasks = _tasks_with_opus(tmp_path)
    sonnet = [t for t in tasks if t["model"] == "sonnet"]
    for t in sonnet:
        t["kind"] = "mechanical"
    block = taskmetrics.mechanical_block(tasks, {}, harness.PRICES, harness.load_speeds(), None, None, baseline="opus", select="model=sonnet")
    cf = block["counterfactual"]
    assert block["baseline"] == "opus" and cf["baseline"] == "opus" and cf["subject_models"] == ["sonnet"]
    assert "re-prices tokens only" in cf["LABEL"] and "as if run on opus" in cf["LABEL"]
    row = cf["tasks"][0]
    t = next(x for x in sonnet if x["task"] == row["task"])
    tk = {"input": t["tokens"]["in"], "output": t["tokens"]["out"], "cache_read": t["tokens"]["cache_read"],
          "cache_write_5m": t["tokens"]["cache_write_5m"], "cache_write_1h": t["tokens"]["cache_write_1h"]}
    assert abs(row["baseline_cost_usd"] - taskmetrics.cost_of(tk, harness.PRICES["opus"])) < 1e-4
    assert cf["saves_cost_usd"] > 0 and "counterfactual_opus" in block   # Sonnet tasks cost less than they would on the Opus baseline


def test_pool_check_is_any_agent_outside_its_planned_tier(tmp_path):
    tasks = _tasks_with_opus(tmp_path)
    block = taskmetrics.mechanical_block(tasks, {}, harness.PRICES, harness.load_speeds(), None)
    assert block["pool"]["pool_violations"] == sum(1 for t in tasks if t["pool_violation"])
    assert all({"task", "planned", "ran_on", "agent_type"} <= set(v) for v in block["pool"]["violations"])


def test_history_bridge_roundtrip(tmp_path):
    tasks = _tasks_with_opus(tmp_path / "w")
    score = tmp_path / "combo-x.json"
    score.write_text(json.dumps({"tasks": tasks, "mechanical": {}}), encoding="utf-8")
    hist = tmp_path / "history.jsonl"
    assert history_import.import_scores([score], hist) == len(tasks)
    assert history_import.import_scores([score], hist) == 0          # no duplicates
    rows = [json.loads(ln) for ln in hist.read_text().splitlines()]
    assert {r["agent_type"] for r in rows} == {"implementer-haiku", "implementer"} and all(r["v"] == 1 for r in rows)
    runs = history_import.runs_from_history(hist)
    assert [r["run"] for r in runs] == ["combo-x"] and "implementer:opus" in runs[0]["mechanical"]["groups"]
    assert "implementer:opus" in report_mechanical.render(runs)
    assert report_mechanical.main(["--history", str(hist), "--focus", "opus"]) == 0
