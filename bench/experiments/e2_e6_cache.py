"""E2: prime-then-assign at full wave width (5 Sonnet implementers). E6: 1h TTL after a >5 min gap."""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import run_claude

shared = "SHARED WAVE PRIME. Plan for a tiny project: five independent echo tasks.\n" + "\n".join(
    f"Plan rule {i}: implement exactly what the task message says; report status, files and the command result in under 40 words; cite rule {i} if relevant."
    for i in range(1, 121)) + "\n\nThis message only primes you. Reply with exactly READY; your task follows in the next message."
prompt = f"""Infrastructure test. Follow these steps exactly; no extra work.
1. Dispatch ONE Agent: subagent_type "superlite:implementer", model "sonnet", effort "medium", prompt = the PRIME text below verbatim. Wait for READY.
2. In ONE message dispatch FOUR more Agents with identical settings and the identical PRIME prompt. Wait for all READY.
3. Also dispatch ONE Agent: subagent_type "superlite:test-runner", model "haiku", effort "low", prompt = the PRIME text verbatim. Wait for READY.
4. SendMessage each of the five implementers: "Task: run `echo t<N>` (N = 1..5 in dispatch order) and report." Wait for all five.
5. Run Bash `sleep 400` (timeout 450000 ms).
6. SendMessage implementer 1: "Task 2: run `echo late1` and report." and SendMessage the test-runner: "Run `echo late2` and report." Wait for both.
7. Reply with one line per step, then EXPERIMENT-DONE.
<PRIME>
{shared}
</PRIME>"""
out = Path(__file__).parent / "results"
out.mkdir(exist_ok=True)
r = run_claude(prompt, model="opus", cwd=Path(tempfile.mkdtemp()), budget=4, plugin_superlite=True,
               log=out / "e2_e6.jsonl", timeout=1500)
d = r.dispatches()
rows = []
for pid, calls in r.calls_by_agent().items():
    meta = d.get(pid, {})
    rows.append({"agent": pid[-6:], "type": meta.get("type"), "calls": [(c["read"], c["write"]) for c in calls],
                 "ts": [c["ts"] for c in calls]})
res = {"cost": r.cost, "seconds": round(r.seconds), "agents": rows, "tail": r.text[-300:]}
(out / "e2_e6.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
print(json.dumps(res, indent=1)[:4000])
