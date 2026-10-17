"""E8: plan detail A/B. Sonnet builds one sitegen module from contracts only (SPEC section) vs contracts
plus verbatim tests (the reference suite's tests for that module). Scored by the hidden suite for that module."""
import ast, json, re, shutil, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import run_claude, pytest_counts, REPO

B = REPO / "bench"
spec = (B / "task" / "SPEC.md").read_text(encoding="utf-8")


def section(n):  # "## n. ..." up to the next "## "
    m = re.search(rf"^## {n}\..*?(?=^## )", spec, re.S | re.M)
    return m.group(0)


ref_src = (B / "reference" / "tests" / "test_units.py").read_text(encoding="utf-8")
tree = ast.parse(ref_src)
imports = "\n".join(ast.get_source_segment(ref_src, n) for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)))


def ref_tests(module):
    fns = [n for n in tree.body if isinstance(n, ast.FunctionDef) and module in ast.get_source_segment(ref_src, n)]
    return imports + "\n\n" + "\n\n".join(ast.get_source_segment(ref_src, n) for n in fns), len(fns)


MODULES = {"templates": 4, "markdown": 3}
OUT = Path(__file__).parent / "results"; OUT.mkdir(exist_ok=True)


def build(module, variant):
    d = Path(tempfile.mkdtemp(prefix=f"e8-{module}-{variant}-"))
    pkg = d / "src" / "sitegen"; pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy(B / "reference" / "src" / "sitegen" / "errors.py", pkg / "errors.py")
    contract = section(1) + "\n" + section(MODULES[module])
    extra, ntests = "", 0
    if variant == "tests":
        tests, ntests = ref_tests(module)
        (d / "tests").mkdir(); (d / "tests" / f"test_{module}.py").write_text(tests, encoding="utf-8")
        extra = f"\nThe plan's verbatim tests for this task are in tests/test_{module}.py ({ntests} tests); make them pass.\n"
    prompt = (f"Implement src/sitegen/{module}.py exactly per this contract (errors.py already exists).\n<contract>\n{contract}\n</contract>\n"
              f"{extra}Write your own tests as needed under tests/. Run tests with `PYTHONPATH=src uv run --no-project --with pytest python -m pytest -q`. "
              "Stdlib only. Reply DONE when finished.")
    r = run_claude(prompt, model="sonnet", effort="medium", cwd=d, budget=3, timeout=900)
    hd = d / "hidden"; hd.mkdir(); shutil.copy(B / "hidden_tests" / f"test_{module}.py", hd / f"test_{module}.py")
    p, t = pytest_counts(hd, pythonpath=pkg.parent)
    return {"module": module, "variant": variant, "hidden": f"{p}/{t}", "verbatim_tests": ntests, "cost": round(r.cost, 3), "secs": round(r.seconds)}


jobs = [(m, v) for m in MODULES for v in ("contracts", "tests")]
with ThreadPoolExecutor(max_workers=4) as ex:
    recs = list(ex.map(lambda a: build(*a), jobs))
(OUT / "e8.json").write_text(json.dumps(recs, indent=1), encoding="utf-8")
for r in recs:
    print(r)
