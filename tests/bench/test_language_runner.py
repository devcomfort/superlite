"""Language-neutral scoring hooks in bench/harness.py: task.yaml, run.sh/own_tests.sh with JUnit XML, Node on PATH."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
import harness  # noqa: E402

JUNIT = """<?xml version="1.0"?><testsuites><testsuite name="s">
<testcase classname="hidden_tests/a.test.ts" name="ok1"/>
<testcase classname="hidden_tests/a.test.ts" name="ok2"/>
<testcase classname="hidden_tests/a.test.ts" name="bad"><failure message="x"/></testcase>
<testcase classname="hidden_tests/a.test.ts" name="skip"><skipped/></testcase>
</testsuite></testsuites>"""

RUNNER = f"""#!/usr/bin/env bash
cat > "$JUNIT" <<'XML'
{JUNIT}
XML
echo "$HIDDEN_DIR" > hidden_tests/seen_dir.txt
exit 0
"""


def test_default_task_config_is_python(tmp_path):
    cfg = harness.load_task_cfg(None)
    assert cfg == {"language": "python", "extensions": [".py"], "src_dirs": ["src"], "needs_node": False}
    assert harness.load_task_cfg(tmp_path) == cfg  # no task.yaml


def test_task_yaml_overrides(tmp_path):
    (tmp_path / "task.yaml").write_text(
        "language: typescript  # note\nextensions: [.ts, .tsx]\nsrc_dirs: [src, lib]\nneeds_node: true\nbogus: 1\n",
        encoding="utf-8")
    cfg = harness.load_task_cfg(tmp_path)
    assert cfg == {"language": "typescript", "extensions": [".ts", ".tsx"], "src_dirs": ["src", "lib"],
                   "needs_node": True}


def test_src_loc_counts_by_extension_and_skips_node_modules(tmp_path):
    (tmp_path / "src" / "node_modules").mkdir(parents=True)
    (tmp_path / "src" / "a.ts").write_text("1\n2\n3\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("1\n", encoding="utf-8")
    (tmp_path / "src" / "node_modules" / "c.ts").write_text("1\n" * 50, encoding="utf-8")
    ts = {"extensions": [".ts"], "src_dirs": ["src"]}
    assert harness.count_src_loc(tmp_path, ts) == 3
    assert harness.count_src_loc(tmp_path, harness.load_task_cfg(None)) == 1  # default: .py under src/
    assert harness.count_src_loc(tmp_path / "missing") == 0


def test_with_node_prepends_only_when_needed(tmp_path, monkeypatch):
    monkeypatch.setenv("BENCH_NODE_DIR", str(tmp_path))
    env = {"Path": "/usr/bin"}
    assert harness.with_node(env, {"needs_node": False}) is env
    out = harness.with_node(env, {"needs_node": True})
    assert out["Path"].startswith(str(tmp_path) + ";" if sys.platform == "win32" else str(tmp_path) + ":")
    assert env["Path"] == "/usr/bin"  # input untouched
    monkeypatch.setenv("BENCH_NODE_DIR", str(tmp_path / "absent"))
    assert harness.with_node(env, {"needs_node": True}) is env


def test_junit_counts_marks_failures_and_skips():
    p = Path(__import__("tempfile").mkdtemp()) / "j.xml"
    p.write_text(JUNIT, encoding="utf-8")
    total, failed, by_file = harness.junit_counts(p)
    assert total == 4 and len(failed) == 2
    assert list(by_file.values()) == [[2, 4]]


def test_hidden_score_uses_task_runner(tmp_path, monkeypatch):
    suite = tmp_path / "hidden"
    suite.mkdir()
    (suite / "run.sh").write_text(RUNNER, encoding="utf-8", newline="\n")
    run_dir = tmp_path / "run"
    (run_dir / "node_modules").mkdir(parents=True)
    (run_dir / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(harness, "TASK_HIDDEN", suite)
    r = harness.hidden_score(run_dir)
    assert (r["hidden_passed"], r["hidden_total"]) == (2, 4)
    assert len(r["hidden_failed_ids"]) == 2
    assert not (run_dir / "hidden_tests").exists()  # ran in a temp copy


def test_hidden_score_runner_without_junit(tmp_path, monkeypatch):
    suite = tmp_path / "hidden"
    suite.mkdir()
    (suite / "run.sh").write_text("exit 0\n", encoding="utf-8", newline="\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setattr(harness, "TASK_HIDDEN", suite)
    r = harness.hidden_score(run_dir)
    assert r["hidden_passed"] == 0 and r["hidden_total"] is None and r["hidden_failed_ids"] == ["(no junit)"]


def test_own_tests_uses_task_script(tmp_path, monkeypatch):
    suite = tmp_path / "hidden"
    suite.mkdir()
    (suite / "own_tests.sh").write_text(RUNNER.replace("hidden_tests/seen_dir.txt", "seen.txt"),
                                        encoding="utf-8", newline="\n")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setattr(harness, "TASK_HIDDEN", suite)
    assert harness.own_tests(run_dir) == {"own_tests_summary": "2 passed, 2 failed"}
