"""A task's optional start/ directory seeds the run dir (bench/harness.py seed_run_dir)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))
import harness  # noqa: E402


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def test_start_dir_is_copied_and_committed_and_absent_start_is_unchanged(tmp_path, monkeypatch):
    spec = tmp_path / "SPEC.md"
    spec.write_text("the spec", encoding="utf-8")
    start = tmp_path / "start"
    (start / "src" / "pkg").mkdir(parents=True)
    (start / "src" / "pkg" / "mod.py").write_text("X = 1\n", encoding="utf-8")
    (start / ".superlite").mkdir()
    (start / ".superlite" / "incidents.jsonl").write_text("{}\n", encoding="utf-8")
    (start / "src" / "pkg" / "__pycache__").mkdir()
    (start / "src" / "pkg" / "__pycache__" / "mod.pyc").write_bytes(b"junk")
    (start / "SPEC.md").write_text("stale spec inside start", encoding="utf-8")
    monkeypatch.setattr(harness, "TASK_SPEC", spec)

    # With a start/ dir: its tree plus SPEC.md (the task's SPEC wins), all committed, no pyc.
    monkeypatch.setattr(harness, "TASK_START", start)
    with_start = tmp_path / "run1"
    with_start.mkdir()
    harness.seed_run_dir(with_start)
    tracked = set(_git(with_start, "ls-files").split())
    assert tracked == {"SPEC.md", "src/pkg/mod.py", ".superlite/incidents.jsonl"}
    assert (with_start / "SPEC.md").read_text(encoding="utf-8") == "the spec"
    assert _git(with_start, "status", "--porcelain").strip() == ""
    assert len(_git(with_start, "log", "--oneline").splitlines()) == 1

    # Without one (missing dir, or None as for the default task): only SPEC.md, as before.
    for missing in (tmp_path / "nope", None):
        monkeypatch.setattr(harness, "TASK_START", missing)
        bare = tmp_path / f"bare{missing is None}"
        bare.mkdir()
        harness.seed_run_dir(bare)
        assert _git(bare, "ls-files").split() == ["SPEC.md"]
