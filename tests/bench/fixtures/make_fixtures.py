"""Trim the real benchmark logs in bench/results into small fixtures for test_metrics.py.

Run from the repo root:  uv run --no-project python tests/bench/fixtures/make_fixtures.py

The logs are 1-3 MB each. The metrics need only each event's type, timestamp, parent and message
id, usage, the tool_use blocks (names, ids, short inputs) and the agent start and end markers, so
the rest (thinking, tool output, progress ticks, long strings) is dropped or cut short. Every
fixture stays well under 200 KB.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parents[2] / "bench" / "results"
SOURCES = ["combo-superlite-e1", "combo-superpowers-e1", "combo-superpowers-e2", "combo-superlite-e3"]
LIMIT = 200_000
KEEP_SYSTEM = ("task_started", "task_notification")


def cut(s, n: int = 360):
    """Head + tail of a long string, so leading and trailing markers (READY, 'do after') survive."""
    if not isinstance(s, str) or len(s) <= n:
        return s
    return s[: n * 2 // 3] + " ... " + s[-(n // 3):]


def shrink_command(cmd: str) -> str:
    """Cut a command to its head, but keep a window around any kill-by-name call."""
    m = re.search(r"taskkill|pkill|killall|stop-process|kill\s+-9", cmd, re.I)
    if m and m.start() > 200:
        return cut(cmd, 200) + " ... " + cmd[max(0, m.start() - 60): m.end() + 120]
    return cut(cmd, 240)


def shrink_input(name: str, inp: dict, top: bool) -> dict:
    if name in ("Bash", "PowerShell"):
        return {"command": shrink_command(inp.get("command") or "")}
    if name in ("Agent", "Task"):
        return {k: cut(v, 160) if k == "prompt" else v for k, v in inp.items()
                if k in ("description", "subagent_type", "model", "effort", "name", "prompt")}
    if name == "SendMessage":
        return {"to": inp.get("to"), "summary": inp.get("summary"), "message": cut(str(inp.get("message")), 420)}
    if name == "Write":
        return {"file_path": inp.get("file_path"), "content": ""}
    return {}


def trim(e: dict, seen_mid: set, agent_ids: set) -> dict | None:
    ty, sub = e.get("type"), e.get("subtype")
    out = {k: e[k] for k in ("type", "subtype", "timestamp", "parent_tool_use_id") if k in e}
    if ty == "system":
        if sub not in KEEP_SYSTEM:
            return None
        if sub == "task_started" and e.get("task_type") == "local_agent":
            agent_ids.add(e.get("task_id"))
        if e.get("task_id") not in agent_ids:
            return None                 # background shell tasks are irrelevant to the metrics
        out.update({k: e[k] for k in ("task_id", "tool_use_id", "task_type", "description", "subagent_type", "status")
                    if k in e})
        if "prompt" in e:
            out["prompt"] = cut(e["prompt"], 140)
        if sub == "task_notification" and isinstance(e.get("handback_report"), dict):
            out["handback_report"] = {"text": cut(str(e["handback_report"].get("text")), 300)}
        return out
    if ty == "result":
        out["result"] = cut(str(e.get("result")), 120)
        return out
    if ty not in ("assistant", "user"):
        return None
    top = not e.get("parent_tool_use_id")
    if not top and ty == "user":
        return out                      # a subagent's tool output: only its timestamp matters
    msg = e.get("message") or {}
    blocks = []
    content = msg.get("content")
    if isinstance(content, list):
        for b in content:
            bt = b.get("type")
            if bt == "tool_use" and (top or b["name"] in ("Bash", "PowerShell")):
                blocks.append({"type": "tool_use", "id": b["id"], "name": b["name"],
                               "input": shrink_input(b["name"], b.get("input") or {}, top)})
            elif bt == "text" and ty == "assistant" and top:
                blocks.append({"type": "text", "text": cut(b.get("text") or "", 160)})
            elif bt == "tool_result" and top:
                blocks.append({"type": "tool_result", "tool_use_id": b.get("tool_use_id"), "content": ""})
    m = {"content": blocks}
    if ty == "assistant":
        m.update({k: msg[k] for k in ("id", "model", "usage") if k in msg})
        mid = msg.get("id")
        if mid in seen_mid:
            m.pop("usage", None)        # one usage record per message is enough
        seen_mid.add(mid)
        if isinstance(m.get("usage"), dict):
            m["usage"] = {k: v for k, v in m["usage"].items()
                          if k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                   "cache_creation_input_tokens", "cache_creation")}
    out["message"] = m
    return out


ID_KEYS = ("parent_tool_use_id", "tool_use_id", "task_id", "id", "to")


def alias_ids(x, table: dict):
    """Replace long opaque ids with short stable aliases (the same id always maps the same way)."""
    if isinstance(x, dict):
        return {k: (table.setdefault(v, f"i{len(table)}") if k in ID_KEYS and isinstance(v, str) and len(v) > 8
                    else alias_ids(v, table)) for k, v in x.items()}
    if isinstance(x, list):
        return [alias_ids(i, table) for i in x]
    return x


def main() -> None:
    for name in SOURCES:
        src = RESULTS / f"{name}.jsonl"
        dst = HERE / f"{name}.trim.jsonl"
        lines, seen_mid, agent_ids, table = [], set(), set(), {}
        for line in src.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith("{"):
                continue
            try:
                t = trim(json.loads(line), seen_mid, agent_ids)
            except json.JSONDecodeError:
                continue
            if t is not None:
                lines.append(json.dumps(alias_ids(t, table), ensure_ascii=False, separators=(",", ":")))
        dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
        size = dst.stat().st_size
        print(f"{dst.name}: {len(lines)} events, {size // 1024} KB")
        if size > LIMIT:
            sys.exit(f"{dst.name} is over {LIMIT} bytes")


if __name__ == "__main__":
    main()
