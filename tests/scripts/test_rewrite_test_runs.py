import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "rewrite-test-runs"
_GIT_BASH = r"C:\Program Files\Git\bin\bash.exe"
BASH = _GIT_BASH if os.name == "nt" and os.path.exists(_GIT_BASH) else shutil.which("bash")
SL = (ROOT / "skills" / "subagent-driven-development" / "scripts" / "sl").as_posix()
NOTE = "raw test run rewritten to a background sl run_tests --full"


@pytest.fixture
def proj(tmp_path):
    (tmp_path / ".superlite").mkdir()
    (tmp_path / ".superlite" / "pool.json").write_text("{}")
    return tmp_path


def run(proj, command=None, raw=None, **extra):
    if raw is None:
        raw = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, **extra})
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj)}
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    return subprocess.run([BASH, str(HOOK)], input=raw, capture_output=True, text=True, env=env)


def rewritten(r):
    assert r.returncode == 0 and r.stderr == ""
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "allow"
    assert out["updatedInput"]["run_in_background"] is True
    assert out["updatedInput"]["description"] == "sl run_tests --full (rewritten from a raw test run)"
    assert out["additionalContext"].startswith(NOTE)
    assert "`sl run_tests --wait` only at the final gate" in out["additionalContext"]
    return out["updatedInput"]["command"]


SLCMD = f'bash "{SL}" run_tests --full'


@pytest.mark.parametrize("cmd", [
    "pytest", "pytest -x tests/test_a.py", "python -m pytest -q", "python3 -m pytest", "py -3 -m pytest",
    "uv run pytest", "uv run python -m pytest tests", "poetry run pytest", "python -m unittest",
    "npm test", "npm run test", "npm run test -- --watch=false", "pnpm test", "yarn test",
    "npx vitest run", "npx jest", "npx --no-install jest", "vitest", "go test ./...", "cargo test",
    "dotnet test", "CI=1 pytest", "  pytest",
])
def test_rewrites_raw_runners(proj, cmd):
    assert rewritten(run(proj, cmd)).strip() == SLCMD


def test_chained_commands_keep_other_work(proj):
    assert rewritten(run(proj, "cd app && pytest -x")) == f"cd app && {SLCMD} "
    assert rewritten(run(proj, "npm run build && npm test")) == f"npm run build && {SLCMD} "
    assert rewritten(run(proj, "cd x; go test ./...; echo done")).endswith("; echo done")
    assert rewritten(run(proj, "pytest 2>&1 | tail -5")).endswith("| tail -5")
    assert rewritten(run(proj, "make build\npytest")).startswith("make build\n")


def test_subagent_untouched(proj):
    r = run(proj, "pytest", agent_id="a1", agent_type="implementer")
    assert r.returncode == 0 and r.stdout == ""


def test_sl_run_tests_untouched(proj):
    for cmd in ('bash "$SL" run_tests --wait', 'bash "$SL" run_tests --fast', f'bash "{SL}" run_tests --full',
                "cd x && sl run_tests --wait && pytest"):
        r = run(proj, cmd)
        assert r.returncode == 0 and r.stdout == "", cmd


def test_no_marker_untouched(tmp_path):
    r = run(tmp_path, "pytest")
    assert r.returncode == 0 and r.stdout == ""
    assert not (tmp_path / ".superlite").exists()


@pytest.mark.parametrize("cmd", [
    "ls", "git status", "git commit -m 'run pytest'", "echo pytest", "grep -rn pytest .", "cat tests/test_a.py",
    "pip install pytest", "npm install", "npm run build", "go build ./...", "cargo build", "python app.py",
    'echo "a; pytest b"', "python - <<'EOF'\nimport pytest\nEOF", "pytestfoo", "cat npm-test.txt",
])
def test_non_test_commands_untouched(proj, cmd):
    r = run(proj, cmd)
    assert r.returncode == 0 and r.stdout == "", cmd


def test_other_tools_untouched(proj):
    raw = json.dumps({"tool_name": "PowerShell", "tool_input": {"command": "pytest"}})
    assert run(proj, raw=raw).stdout == ""


def test_malformed_input_fails_open(proj):
    for raw in ("", "not json", "[]", "{", json.dumps({"tool_name": "Bash"}),
                json.dumps({"tool_name": "Bash", "tool_input": {"command": 5}})):
        r = run(proj, raw=raw)
        assert r.returncode == 0 and r.stdout == "" and r.stderr == "", raw


def test_logs_rewrites(proj):
    run(proj, "pytest -x")
    line = (proj / ".superlite" / "incidents.jsonl").read_text().splitlines()[0]
    rec = json.loads(line)
    assert rec["kind"] == "rule-rewrite" and rec["agent"] == "coordinator" and rec["command"] == "pytest -x"


def test_plugin_root_env_used(proj):
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_ROOT": "C:\\plug in"}
    raw = json.dumps({"tool_name": "Bash", "tool_input": {"command": "pytest"}})
    r = subprocess.run([BASH, str(HOOK)], input=raw, capture_output=True, text=True, env=env)
    assert 'bash "C:/plug in/skills/subagent-driven-development/scripts/sl" run_tests --full' in rewritten(r)


def test_hooks_json_registers_hook():
    data = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    cmds = [(e["matcher"], e["hooks"][0]["command"]) for e in data["hooks"]["PreToolUse"]]
    assert ("Bash", 'bash "${CLAUDE_PLUGIN_ROOT}/hooks/rewrite-test-runs"') in cmds


def test_lf_endings():
    assert b"\r" not in HOOK.read_bytes()


def test_fast(proj):
    def best(argv, raw=""):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj)}
        times = []
        for _ in range(3):
            t = time.perf_counter()
            subprocess.run(argv, input=raw, capture_output=True, text=True, env=env)
            times.append(time.perf_counter() - t)
        return min(times)

    base = best([BASH, "-c", "exit 0"])
    for cmd in ("git status && ls", "cd app && pytest"):
        raw = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
        t = best([BASH, str(HOOK)], raw)
        assert t < max(0.6, base + 0.35), (cmd, t, base)
