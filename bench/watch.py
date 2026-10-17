"""Live, readable view of a benchmark arm's stream-json log.

Usage: uv run --no-project python bench/watch.py <log.jsonl>   (Ctrl-C to stop)
Prints the coordinator's text, every tool call (subagent dispatches marked >>), subagent results,
and cost lines, following the file as it grows.
"""
import json
import sys
import time
from datetime import datetime


def short(s, n=160):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def show(e):
    t = e.get("type")
    sub = e.get("parent_tool_use_id") is not None
    pad = "    │ " if sub else ""
    if t == "system" and e.get("subtype") == "init":
        return f"=== session start · model {e.get('model')} · plugins {[p.get('name') for p in e.get('plugins', [])]}"
    if t == "assistant":
        out = []
        for b in (e.get("message") or {}).get("content") or []:
            if b.get("type") == "text" and b.get("text", "").strip():
                out.append(f"{pad}💬 {short(b['text'], 220)}")
            elif b.get("type") == "tool_use":
                inp = b.get("input") or {}
                if b.get("name") in ("Agent", "Task"):
                    out.append(f"{pad}>> DISPATCH {inp.get('subagent_type', 'general-purpose')}"
                               f" [{inp.get('model', 'default')}/{inp.get('effort', '-')}] {short(inp.get('description', ''), 80)}")
                elif b.get("name") == "Skill":
                    out.append(f"{pad}★ SKILL {inp.get('skill')}")
                elif b.get("name") == "Bash":
                    out.append(f"{pad}$ {short(inp.get('command', ''), 140)}")
                elif b.get("name") in ("Write", "Edit"):
                    out.append(f"{pad}✎ {b['name']} {inp.get('file_path', '')}")
                elif b.get("name") == "SendMessage":
                    out.append(f"{pad}✉ SendMessage → {inp.get('to')}: {short(inp.get('message', ''), 90)}")
                else:
                    out.append(f"{pad}· {b['name']} {short(json.dumps(inp), 100)}")
        return "\n".join(out) or None
    if t == "result":
        return (f"=== turn ended ({e.get('subtype')}) · session cost so far ${e.get('total_cost_usd', 0):.2f}"
                f" · {short(e.get('result', ''), 160)}")
    return None


def main(path):
    import os
    while not os.path.exists(path):  # the arm may not have started yet
        time.sleep(5)
    with open(path, encoding="utf-8", errors="replace") as f:
        while True:
            line = f.readline()
            if not line:
                time.sleep(1)
                continue
            try:
                text = show(json.loads(line))
            except ValueError:
                continue
            if text:
                print(f"{datetime.now():%H:%M:%S} {text}", flush=True)


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except KeyboardInterrupt:
        pass
