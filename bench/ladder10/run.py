"""Run the 10-step spreadsheet task on several model tiers in parallel and score per step.
Usage: uv run --no-project python bench/ladder10/run.py [model:effort ...]"""
import json, re, shutil, subprocess, sys, tempfile, time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "experiments"))
from common import run_claude

ARMS = [a.split(":") for a in (sys.argv[1:] or ["haiku:low", "sonnet:medium", "opus:medium", "fable:medium"])]
OUT = HERE / "results"; OUT.mkdir(exist_ok=True)
PROMPT = ("Implement the task in SPEC.md in this directory (work only here). Follow its steps in order: for each step, "
          "implement it, add tests for it under tests/, and run the whole suite before moving on. Don't skip steps. "
          "When all 10 steps are done and every test passes, reply with a one-line summary per step and the line TASK-DONE.")


def score(impl: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        hd = Path(tmp) / "hidden"; shutil.copytree(HERE / "hidden", hd)
        junit = Path(tmp) / "j.xml"
        subprocess.run(["uv", "run", "--no-project", "--with", "pytest", "python", "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        f"--junitxml={junit}"], cwd=hd, env={**__import__("os").environ, "PYTHONPATH": str(impl)}, capture_output=True, timeout=600)
        steps = {f"{i:02d}": [0, 0] for i in range(1, 11)}
        if junit.exists():
            for c in ET.parse(junit).getroot().iter("testcase"):
                m = re.match(r"test_s(\d\d)_", c.get("name", ""))
                if not m or m.group(1) not in steps:
                    continue
                steps[m.group(1)][1] += 1
                if not any(x.tag in ("failure", "error", "skipped") for x in c):
                    steps[m.group(1)][0] += 1
    passed = sum(p for p, _ in steps.values()); total = sum(t for _, t in steps.values())
    clean = 0
    for k in sorted(steps):
        if steps[k][1] and steps[k][0] == steps[k][1]:
            clean += 1
        else:
            break
    return {"hidden": f"{passed}/{total}", "steps_clean_in_a_row": clean, "per_step": {k: f"{p}/{t}" for k, (p, t) in steps.items()}}


def arm(model_effort):
    model, effort = model_effort
    d = Path(tempfile.mkdtemp(prefix=f"ladder-{model}-"))
    shutil.copy(HERE / "SPEC.md", d / "SPEC.md")
    r = run_claude(PROMPT, model=model, effort=effort, cwd=d, budget=10, timeout=3600, log=OUT / f"{model}-{effort}.jsonl")
    res = {"arm": f"{model}-{effort}", "secs": round(r.seconds), "cost": round(r.cost, 3), "turns": r.result.get("num_turns"),
           "done_marker": "TASK-DONE" in r.text, "subtype": r.result.get("subtype"), "dir": str(d), **score(d)}
    (OUT / f"{model}-{effort}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res), flush=True)
    return res


with ThreadPoolExecutor(max_workers=len(ARMS)) as ex:
    rows = list(ex.map(arm, ARMS))
print("\n| arm | hidden | clean steps | secs | turns | cost |\n|---|---|---|---|---|---|")
for r in rows:
    print(f"| {r['arm']} | {r['hidden']} | {r['steps_clean_in_a_row']}/10 | {r['secs']} | {r['turns']} | ${r['cost']} |")
