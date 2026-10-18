import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "session-start"
_GIT_BASH = r"C:\Program Files\Git\bin\bash.exe"
BASH = _GIT_BASH if os.name == "nt" and os.path.exists(_GIT_BASH) else shutil.which("bash")


def test_session_start_emits_skill_text_verbatim():
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=str(ROOT))
    r = subprocess.run([BASH, str(HOOK)], input="", capture_output=True, text=True,
                       encoding="utf-8", env=env)
    assert r.returncode == 0
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    skill = (ROOT / "skills" / "using-superlite" / "SKILL.md").read_text(encoding="utf-8")
    assert skill.replace("\r", "").rstrip("\n") in ctx   # newlines, quotes, backslashes survive
    assert "\r" not in ctx
