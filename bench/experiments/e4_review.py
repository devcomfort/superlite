"""E4: review value. Plant 6 SPEC-violating bugs in slug.py + search.py; reviewers on different tiers find them."""
import json, re, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import run_claude, REPO

ref = REPO / "bench" / "reference" / "src" / "sitegen"
spec = (REPO / "bench" / "task" / "SPEC.md").read_text(encoding="utf-8")
files = {"slug.py": (ref / "slug.py").read_text(encoding="utf-8"), "search.py": (ref / "search.py").read_text(encoding="utf-8")}
BUGS = [  # (id, file, original, mutated, description)
    ("B1", "slug.py", 'return s.strip("-")', 'return s.rstrip("-")', "leading hyphens not stripped"),
    ("B2", "slug.py", 'while f"{base}-{n}" in taken:', 'if f"{base}-{n}" in taken:', "unique_slug bumps only once"),
    ("B3", "search.py", 're.findall(r"[a-z0-9]+", s.lower())', 're.findall(r"[a-z0-9]+", s)', "tokenizer not lowercased"),
    ("B4", "search.py", "        seen.add(slug)\n", "", "duplicate slugs not detected"),
    ("B5", "search.py", "        if not p:\n            return []", "        if not p:\n            continue", "AND semantics broken"),
    ("B6", "search.py", "scored = [(-sum(postings[t][s] for t in terms), s) for s in candidates]\n    scored.sort()",
     "scored = [(sum(postings[t][s] for t in terms), s) for s in candidates]\n    scored.sort(reverse=True)", "tie-break order reversed"),
]
bug_lines = {}
for bid, f, a, b, _ in BUGS:
    assert a in files[f], bid
    files[f] = files[f].replace(a, b, 1)
for bid, f, a, b, _ in BUGS:  # locate each bug's line in the mutated file
    probe = (b or a).strip().splitlines()[0] if b else None
    lines = files[f].splitlines()
    if probe:
        bug_lines[bid] = (f, next(i + 1 for i, l in enumerate(lines) if probe in l))
    else:  # deletion: the line after 'if slug in seen' raise
        bug_lines[bid] = (f, next(i + 1 for i, l in enumerate(lines) if "duplicate slug" in l) + 1)

code = "\n\n".join(f"=== src/sitegen/{f} (new file) ===\n" + "\n".join(f"{i+1:4} {l}" for i, l in enumerate(t.splitlines())) for f, t in files.items())
prompt = f"""You are reviewing new code against its SPEC before merge. Find every place the code violates the SPEC or is incorrect.
<spec>\n{spec}\n</spec>
<code>\n{code}\n</code>
Reply with ONLY a JSON array, one object per defect: {{"file": "slug.py" or "search.py", "line": <line number>, "defect": "<one sentence>"}}. Report real defects only, not style."""
REVIEWERS = [("sonnet", "medium"), ("sonnet", "high"), ("opus", "max"), ("fable", "max")]
OUT = Path(__file__).parent / "results"; OUT.mkdir(exist_ok=True)


def review(model_effort):
    model, effort = model_effort
    r = run_claude(prompt, model=model, effort=effort, cwd=Path(tempfile.mkdtemp()), budget=3,
                   extra_args=["--disable-slash-commands", "--disallowedTools", "Bash Edit Write Read Glob Grep Agent WebFetch WebSearch"], timeout=900)
    m = re.search(r"\[.*\]", r.text, re.S)
    found = json.loads(m.group(0)) if m else []
    hits = {bid for bid, (f, ln) in bug_lines.items()
            if any(x.get("file", "").endswith(f) and abs(int(x.get("line", -99)) - ln) <= 3 for x in found)}
    return {"reviewer": f"{model}-{effort}", "found": sorted(hits), "recall": f"{len(hits)}/6",
            "reported": len(found), "false_or_extra": len(found) - len(hits), "cost": round(r.cost, 3), "secs": round(r.seconds)}


with ThreadPoolExecutor(max_workers=4) as ex:
    recs = list(ex.map(review, REVIEWERS))
(OUT / "e4.json").write_text(json.dumps({"bug_lines": bug_lines, "results": recs}, indent=1), encoding="utf-8")
for r in recs:
    print(r)
