"""mechanical_ab.py without live agents: task selection, brief, copy + scoring on a tiny repo, aggregation."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
import harness  # noqa: E402
import mechanical_ab as ab  # noqa: E402

PLAN = """# Plan

## Task graph

```mermaid
flowchart LR
  T1[add] --> T2[mul]
  %% taskgraph
  T1 --> T2
```

### T1 add
**Owns:** src/m/add.py, tests/test_add.py
**Components:** 1
**LOC owned:** 5
**Tests:** fast
**Model:** haiku
**Kind:** mechanical

### T2 mul
**Owns:** src/m/mul.py, tests/test_mul.py
**Components:** 1
**LOC owned:** 5
**Tests:** fast
"""


def git(cwd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True)


def make_repo(tmp):
    repo = tmp / "run"
    (repo / "docs" / "plans").mkdir(parents=True)
    (repo / "src" / "m").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "docs" / "plans" / "p.md").write_text(PLAN, encoding="utf-8")
    (repo / "src" / "m" / "add.py").write_text("def add(a, b):\n    raise NotImplementedError('T1')\n")
    (repo / "tests" / "test_add.py").write_text("")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "Wave 0: skeleton")
    hidden = tmp / "hidden"
    hidden.mkdir()
    (hidden / "test_add.py").write_text("from m.add import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    return repo, hidden


def test_selection_brief_and_commit(tmp_path):
    repo, _ = make_repo(tmp_path)
    plan = harness._run_plan(repo)
    tasks, why = ab.pick_tasks(plan, None)
    assert [t.id for t in tasks] == ["T1"] and "Kind: mechanical" in why
    assert [t.id for t in ab.pick_tasks(plan, ["T2"])[0]] == ["T2"]
    assert ab.owned_tests(tasks[0]) == ["tests/test_add.py"]
    assert "Owns: src/m/add.py, tests/test_add.py" in ab.brief_for(tasks[0], repo) and "do not reply READY" in ab.brief_for(tasks[0], repo)
    assert len(ab.stub_commit(repo, None)) == 40


def test_copy_and_scoring_stub_fails_then_solution_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "PYTEST", [sys.executable, "-m", "pytest"])
    repo, hidden = make_repo(tmp_path)
    task = harness._run_plan(repo).by_id["T1"]
    verify = f'"{sys.executable}" -m pytest {{tests}} -q -p no:cacheprovider'
    dest = tmp_path / "copy"
    ab.prepare(repo, ab.stub_commit(repo, None), dest, "")
    red = ab.score(dest, task, verify, hidden)
    assert red["hidden_total"] == 1 and red["hidden_passed"] == 0 and red["hidden_failed"]
    (dest / "src" / "m" / "add.py").write_text("def add(a, b):\n    return a + b\n")
    (dest / "tests" / "test_add.py").write_text("import sys\nsys.path.insert(0, 'src')\nfrom m.add import add\n\ndef test_a():\n    assert add(2, 2) == 4\n")
    ok = ab.score(dest, task, verify, hidden)
    assert ok["own_ok"] and ok["hidden_passed"] == ok["hidden_total"] == 1 and ok["out_of_scope"] == []
    (dest / "src" / "m" / "other.py").write_text("x = 1\n")
    assert ab.score(dest, task, verify, hidden)["out_of_scope"] == ["src/m/other.py"]
    assert not (dest / "hidden_tests").exists()


def test_fail_reason_and_aggregate():
    base = {"task": "T1", "rep": 1, "model": "haiku", "own_ok": True, "tokens": {"in": 1, "out": 10, "cache_read": 5, "cache_write": 0}}
    runs = [dict(base, passed=True, fail_reason=None, duration_s=10.0, cost_usd=0.01, tool_calls=4),
            dict(base, rep=2, passed=False, timed_out=True, duration_s=300.0, cost_usd=0.05, tool_calls=30,
                 fail_reason=ab.fail_reason({"timed_out": True})),
            dict(base, model="sonnet", passed=True, fail_reason=None, duration_s=40.0, cost_usd=0.2, tool_calls=6)]
    rows = ab.aggregate(runs)
    h = next(r for r in rows if r["model"] == "haiku")
    assert h["passed"] == 1 and h["runs"] == 2 and h["median_s"] == 155.0 and h["failures"] == ["#2: timeout"]
    assert ab.fail_reason({"status": "NEEDS_CONTEXT", "reply": "unclear"}).startswith("NEEDS_CONTEXT")
    assert ab.fail_reason({"own_ok": False, "own_tail": "1 failed"}) == "own tests red: 1 failed"
    assert "T1" in ab.render(rows, 0.26, 2.0) and "Total spend $0.26" in ab.render(rows, 0.26, 2.0)
