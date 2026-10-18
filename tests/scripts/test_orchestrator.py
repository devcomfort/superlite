"""Who orchestrates: the human/AI gate on lint --stable, dispatch, wave0 and build_prime; finish line; bench prompts."""
from __future__ import annotations

import json
from pathlib import Path

from test_plan_tools import SCRIPTS, run
from test_routing import mech_plan

ORCH = SCRIPTS / "orchestrator.py"
REPO = SCRIPTS.parents[2]
LINE = "Orchestrator: AI, do not ask me to choose or to approve."
BLOCK = "BLOCKED: human orchestrator selected, show the plan, ask for approval, then run sl orchestrator approve"


def orch(tmp_path, *args):
    return run(ORCH, *args, "--plan", tmp_path / "plan.md", cwd=tmp_path)


def gated(tmp_path, p):
    """The four gated tools, each as (name, process)."""
    sl = tmp_path / ".superlite"
    return {
        "lint --stable": run(SCRIPTS / "plan_tools.py", "lint", "--stable", "--plan", p, cwd=tmp_path),
        "dispatch": run(SCRIPTS / "dispatch.py", "--plan", p, "--pool", sl / "pool.json", "--ledger", sl / "progress.md", cwd=tmp_path),
        "wave0": run(SCRIPTS / "wave0.py", "--plan", p, cwd=tmp_path),
        "build_prime": run(SCRIPTS / "build_prime.py", "--plan", p, "--out", sl / "prime.md", cwd=tmp_path),
    }


def test_each_gated_tool_is_blocked_in_human_mode_and_runs_after_approve(tmp_path):
    p = mech_plan(tmp_path, 2)
    assert "human" in orch(tmp_path, "set", "human").out
    for name, cp in gated(tmp_path, p).items():
        assert cp.returncode == 4, (name, cp.both)
        assert BLOCK in cp.err and len(cp.err.strip().splitlines()) == 1, name
    assert not (tmp_path / ".superlite" / "stable.json").exists() and not (tmp_path / ".superlite" / "briefs").exists()
    ap = orch(tmp_path, "approve", "--by", "carol")
    assert ap.returncode == 0 and "human, approved" in ap.out and "carol" in ap.out
    for name, cp in gated(tmp_path, p).items():
        assert cp.returncode in (0, 1) and BLOCK not in cp.both, (name, cp.both)  # lint may exit 1 for FIX tasks, never 4
    assert (tmp_path / ".superlite" / "stable.json").exists()


def test_schedule_prune_and_plain_lint_stay_allowed_in_human_mode(tmp_path):
    p = mech_plan(tmp_path, 2)
    orch(tmp_path, "set", "human")
    for args in (("schedule", "--plan", p, "--insert"), ("prune", "--plan", p), ("lint", "--plan", p)):
        cp = run(SCRIPTS / "plan_tools.py", *args, cwd=tmp_path)
        assert BLOCK not in cp.both and cp.returncode != 4, (args, cp.both)
    assert "%% schedule" in p.read_text(encoding="utf-8")


def test_ai_mode_and_no_file_are_ungated(tmp_path):
    p = mech_plan(tmp_path, 2)
    for name, cp in gated(tmp_path, p).items():  # no orchestrator.json
        assert BLOCK not in cp.both, (name, cp.both)
    orch(tmp_path, "set", "ai")
    st = json.loads((tmp_path / ".superlite" / "orchestrator.json").read_text(encoding="utf-8"))
    assert st["mode"] == "ai" and st["approved"] is True and st["by"] == "user" and st["time"]
    for name, cp in gated(tmp_path, p).items():
        assert BLOCK not in cp.both, (name, cp.both)


def test_approve_needs_human_mode(tmp_path):
    cp = orch(tmp_path, "approve")
    assert cp.returncode == 2 and "human mode only" in cp.err
    orch(tmp_path, "set", "ai")
    assert orch(tmp_path, "approve").returncode == 2


def test_status_lines(tmp_path):
    assert "not set (ungated)" in orch(tmp_path, "status").out
    orch(tmp_path, "set", "human")
    assert "human, awaiting approval" in orch(tmp_path, "status").out
    orch(tmp_path, "approve")
    assert "human, approved" in orch(tmp_path, "status").out
    orch(tmp_path, "set", "ai")
    assert orch(tmp_path, "status").out.startswith("orchestrator: AI")


def test_set_ai_can_record_the_headless_default_as_a_ruling(tmp_path):
    orch(tmp_path, "set", "ai", "--by", "coordinator", "--ruling", "orchestrator defaulted to AI - headless run, no human can answer - cost if wrong: none")
    text = (tmp_path / ".superlite" / "progress.md").read_text(encoding="utf-8")
    assert text.strip() == "Ruling: orchestrator defaulted to AI - headless run, no human can answer - cost if wrong: none"


def finish(tmp_path):
    sl = tmp_path / ".superlite"
    sl.mkdir(exist_ok=True)
    (sl / "progress.md").write_text("# Progress ledger\n", encoding="utf-8")
    return run(SCRIPTS / "finish.py", "--ledger", sl / "progress.md", "--log", sl / "i.jsonl", cwd=tmp_path).out


def test_finish_reports_the_mode_and_the_approval_time(tmp_path):
    assert "orchestrator: not set (ungated)" in finish(tmp_path)
    orch(tmp_path, "set", "human")
    assert "orchestrator: human, awaiting approval" in finish(tmp_path)
    orch(tmp_path, "approve", "--by", "dana")
    out = finish(tmp_path)
    st = json.loads((tmp_path / ".superlite" / "orchestrator.json").read_text(encoding="utf-8"))
    assert f"orchestrator: human, approved {st['approved_time']} by dana" in out
    orch(tmp_path, "set", "ai")
    assert "orchestrator: AI" in finish(tmp_path)


def bench_prompts():
    b = REPO / "bench"
    return sorted([*b.glob("prompt*.md"), *b.glob("tasks/*/prompt*.md")])


def test_every_bench_prompt_says_the_orchestrator_is_ai():
    files = bench_prompts()
    assert len(files) >= 10
    missing = [str(f.relative_to(REPO)) for f in files if LINE not in f.read_text(encoding="utf-8")]
    assert not missing, missing


def test_skill_size_caps_and_the_new_names():
    skills = REPO / "skills"
    assert len((skills / "using-superlite" / "SKILL.md").read_text(encoding="utf-8")) <= 2000
    assert len((skills / "subagent-driven-development" / "SKILL.md").read_text(encoding="utf-8")) <= 11600
    brain = (skills / "brainstorming" / "SKILL.md").read_text(encoding="utf-8")
    assert "Human orchestrator: I approve the plan before it runs" in brain and "AI orchestrator: hands off, it does everything" in brain
    assert brain.count("AskUserQuestion") >= 1 and "ONE `AskUserQuestion` call" in brain
    plans = (skills / "writing-plans" / "SKILL.md").read_text(encoding="utf-8")
    assert "**Human orchestrator**" in plans and "**AI orchestrator**" in plans and "A human approves" not in plans


# ---------------------------------------------------------------- review plan (human orchestrator, phase 1)

import hashlib  # noqa: E402

REVIEW = REPO / "skills" / "writing-plans" / "review-plan.md"


def review_file(tmp_path, name="plan.review.md"):
    f = tmp_path / "docs" / "plans" / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("# Review plan\n\n## Summary\nA word counter.\n", encoding="utf-8")
    return f


def test_approve_review_records_path_and_sha256(tmp_path):
    orch(tmp_path, "set", "human")
    f = review_file(tmp_path)
    cp = orch(tmp_path, "approve", "--by", "erin", "--review", f)
    assert cp.returncode == 0, cp.both
    st = json.loads((tmp_path / ".superlite" / "orchestrator.json").read_text(encoding="utf-8"))
    assert st["review_path"] == str(f).replace("\\", "/") and st["review_sha256"] == hashlib.sha256(f.read_bytes()).hexdigest()
    assert st["approved"] is True and st["approved_by"] == "erin"
    assert f"review plan {st['review_path']}" in cp.out


def test_approve_review_with_a_missing_file_fails_and_does_not_approve(tmp_path):
    orch(tmp_path, "set", "human")
    cp = orch(tmp_path, "approve", "--review", tmp_path / "nope.review.md")
    assert cp.returncode == 2 and "review plan not found" in cp.err
    st = json.loads((tmp_path / ".superlite" / "orchestrator.json").read_text(encoding="utf-8"))
    assert st["approved"] is False and "review_path" not in st
    assert "awaiting approval" in orch(tmp_path, "status").out


def test_approve_without_review_is_unchanged(tmp_path):
    orch(tmp_path, "set", "human")
    cp = orch(tmp_path, "approve", "--by", "frank")
    st = json.loads((tmp_path / ".superlite" / "orchestrator.json").read_text(encoding="utf-8"))
    assert cp.returncode == 0 and st["approved"] is True and "review_path" not in st and "review plan" not in cp.out


def test_status_and_finish_show_the_review_plan_path(tmp_path):
    orch(tmp_path, "set", "human")
    f = review_file(tmp_path)
    orch(tmp_path, "approve", "--review", f)
    path = str(f).replace("\\", "/")
    assert f"review plan {path}" in orch(tmp_path, "status").out
    assert f"review plan {path}" in finish(tmp_path)
    p = mech_plan(tmp_path, 2)
    assert BLOCK not in run(SCRIPTS / "plan_tools.py", "lint", "--stable", "--plan", p, cwd=tmp_path).both  # the gate opened


REQUIRED_SECTIONS = ["## Summary", "## What you will get", "## What will be built", "## How it fits together", "## How it gets built",
                     "## Decisions you can change", "## Risks", "## Out of scope", "## How we will know it works", "## Rough time and cost"]


def test_review_plan_template_names_every_required_section_and_has_two_diagrams():
    text = REVIEW.read_text(encoding="utf-8")
    for h in REQUIRED_SECTIONS:
        assert h in text, h
    assert text.count("```mermaid") >= 2  # the example carries both diagrams
    for word in ("Size (S/M/L)", "at most 12 nodes", "rough until", "Do not", "Do\n", "five-line summary", "sha256", "**Review plan:**"):
        assert word in text, word


def test_skills_mention_both_phases_and_keep_their_caps():
    skills = REPO / "skills"
    plans = (skills / "writing-plans" / "SKILL.md").read_text(encoding="utf-8")
    brain = (skills / "brainstorming" / "SKILL.md").read_text(encoding="utf-8")
    sdd = (skills / "subagent-driven-development" / "SKILL.md").read_text(encoding="utf-8")
    for text in (plans, brain):
        assert ".review.md" in text and "review-plan.md" in text and "approve --review" in text
    assert "**Review plan:**" in plans and "machine plan" in plans and "machine plan" in brain
    assert "approve --review PATH" in sdd and "review plan" in sdd
    assert len((skills / "using-superlite" / "SKILL.md").read_text(encoding="utf-8")) <= 2000 and len(sdd) <= 11600
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "review plan" in readme.lower() and "You approve first" in readme
