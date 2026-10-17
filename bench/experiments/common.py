"""Shared helpers for superlite micro-experiments.

Run scripts with: uv run --no-project python bench/experiments/<script>.py
Every call runs `claude -p` with a clean environment (host-session CLAUDE*/ANTHROPIC* vars stripped,
so hooks and plugins behave like a fresh terminal) and stream-json output, then parses usage.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLAUDE = shutil.which("claude") or "claude"
SUPERPOWERS_OFF = {"superpowers@claude-plugins-official": False}


def clean_env(fork: bool = False, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not (k.startswith("CLAUDE") or k.startswith("ANTHROPIC"))}
    if fork:
        env["CLAUDE_CODE_FORK_SUBAGENT"] = "1"
    env.update(extra or {})
    return env


@dataclass
class Run:
    events: list[dict]
    seconds: float
    result: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.result.get("result") or ""

    @property
    def cost(self) -> float:
        return self.result.get("total_cost_usd") or 0.0

    def dispatches(self) -> dict[str, dict]:
        """Coordinator Agent tool_use id -> {type, model, prompt_len}."""
        out = {}
        for e in self.events:
            if e.get("type") == "assistant" and e.get("parent_tool_use_id") is None:
                for b in (e.get("message") or {}).get("content") or []:
                    if b.get("type") == "tool_use" and b.get("name") in ("Agent", "Task"):
                        i = b.get("input") or {}
                        out[b["id"]] = {"type": i.get("subagent_type"), "model": i.get("model"),
                                        "prompt_len": len(i.get("prompt") or "")}
        return out

    def calls_by_agent(self) -> dict[str, list[dict]]:
        """parent_tool_use_id -> list of unique API calls (deduped by message id), in order,
        each {model, read, write, input, ts}."""
        seen, out = set(), {}
        for e in self.events:
            p = e.get("parent_tool_use_id")
            if e.get("type") != "assistant" or not p:
                continue
            m = e.get("message") or {}
            mid = m.get("id")
            if (p, mid) in seen:
                continue
            seen.add((p, mid))
            u = m.get("usage") or {}
            out.setdefault(p, []).append({"model": m.get("model"), "read": u.get("cache_read_input_tokens") or 0,
                                          "write": u.get("cache_creation_input_tokens") or 0,
                                          "input": u.get("input_tokens") or 0, "ts": e.get("timestamp")})
        return out

    def tool_names(self) -> list[str]:
        for e in self.events:
            if e.get("type") == "system" and e.get("subtype") == "init":
                return list(e.get("tools") or [])
        return []


def run_claude(prompt: str, *, model: str = "opus", cwd: Path, budget: float = 2.0, plugin_superlite: bool = False,
               fork: bool = False, effort: str | None = None, extra_args: list[str] | None = None,
               env_extra: dict[str, str] | None = None, log: Path | None = None, timeout: int = 1800) -> Run:
    cwd.mkdir(parents=True, exist_ok=True)
    args = [CLAUDE, "-p", "--model", model, "--permission-mode", "auto", "--permission-prompts", "none",
            "--output-format", "stream-json", "--verbose", "--max-budget-usd", str(budget),
            "--settings", json.dumps({"enabledPlugins": SUPERPOWERS_OFF, "skillOverrides": {"orchestrator": "off"}})]
    if plugin_superlite:
        args += ["--plugin-dir", str(REPO)]
    if effort:
        args += ["--effort", effort]
    args += extra_args or []
    t0 = time.time()
    proc = subprocess.run(args, cwd=cwd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                          env=clean_env(fork, env_extra), timeout=timeout)
    secs = time.time() - t0
    events = []
    for line in proc.stdout.splitlines():
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if log:
        log.write_text(proc.stdout, encoding="utf-8")
    results = [e for e in events if e.get("type") == "result"]
    return Run(events, secs, results[-1] if results else {})


def pytest_counts(cwd: Path, target: str = "", pythonpath: Path | None = None) -> tuple[int, int]:
    """Run pytest in cwd and return (passed, total) from a junit file."""
    import xml.etree.ElementTree as ET
    junit = cwd / ".junit.xml"
    env = dict(os.environ)
    if pythonpath:
        env["PYTHONPATH"] = str(pythonpath)
    subprocess.run(["uv", "run", "--no-project", "--with", "pytest", "python", "-m", "pytest", "-q",
                    "-p", "no:cacheprovider", f"--junitxml={junit}", *([target] if target else [])],
                   cwd=cwd, env=env, capture_output=True, timeout=600)
    if not junit.exists():
        return 0, 0
    total = failed = 0
    for case in ET.parse(junit).getroot().iter("testcase"):
        total += 1
        if any(c.tag in ("failure", "error", "skipped") for c in case):
            failed += 1
    return total - failed, total
