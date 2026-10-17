"""E5/E9: first-attempt pass rate (p) and retry recovery (q) per model tier on 6 small problems.
Each attempt is one headless agent run that may run the visible tests; scoring uses hidden tests."""
import json, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from common import run_claude, pytest_counts, CLAUDE, clean_env

P = {
 "clamp": ("easy", "def clamp(x, lo, hi) -> number: return x limited to [lo, hi]; raise ValueError if lo > hi.",
   "from solution import clamp\ndef test_mid(): assert clamp(5,0,10)==5\ndef test_low(): assert clamp(-1,0,10)==0\n",
   "import pytest\nfrom solution import clamp\ndef test_hi(): assert clamp(11,0,10)==10\ndef test_eq(): assert clamp(3,3,3)==3\ndef test_bad():\n    with pytest.raises(ValueError): clamp(1,5,0)\ndef test_float(): assert clamp(2.5,0,2)==2\n"),
 "palindrome": ("easy", "def is_palindrome(s: str) -> bool: True if s reads the same backwards considering only alphanumeric characters, case-insensitive. Empty string is a palindrome.",
   "from solution import is_palindrome\ndef test_basic(): assert is_palindrome('A man, a plan, a canal: Panama')\ndef test_no(): assert not is_palindrome('abc')\n",
   "from solution import is_palindrome\ndef test_empty(): assert is_palindrome('')\ndef test_punct(): assert is_palindrome('.,!')\ndef test_digits(): assert is_palindrome('12 21')\ndef test_case(): assert is_palindrome('Aa')\ndef test_unicode(): assert is_palindrome('été') is True\n"),
 "roman": ("medium", "def roman_to_int(s: str) -> int: convert a canonical Roman numeral (I..MMMCMXCIX). Raise ValueError for empty strings, invalid characters, or non-canonical forms such as 'IIII', 'VV', 'IC', 'IM', 'XM', 'MMMM'.",
   "from solution import roman_to_int\ndef test_basic(): assert roman_to_int('XIV')==14\ndef test_big(): assert roman_to_int('MCMXCIV')==1994\n",
   "import pytest\nfrom solution import roman_to_int\n@pytest.mark.parametrize('s',['','IIII','VV','IC','IM','XM','MMMM','ABC','iv','VX','LL','DD','IIV','XXXX'])\ndef test_bad(s):\n    with pytest.raises(ValueError): roman_to_int(s)\ndef test_max(): assert roman_to_int('MMMCMXCIX')==3999\ndef test_iv(): assert roman_to_int('IV')==4\ndef test_xl(): assert roman_to_int('XL')==40\n"),
 "intervals": ("medium", "def merge_intervals(iv: list[tuple[int,int]]) -> list[tuple[int,int]]: merge overlapping or touching closed intervals (a,b) with a<=b; return sorted by start. Raise ValueError if any a>b. Do not mutate the input.",
   "from solution import merge_intervals\ndef test_basic(): assert merge_intervals([(1,3),(2,6),(8,10)])==[(1,6),(8,10)]\n",
   "import pytest\nfrom solution import merge_intervals\ndef test_touch(): assert merge_intervals([(1,2),(2,3)])==[(1,3)]\ndef test_unsorted(): assert merge_intervals([(5,6),(1,2)])==[(1,2),(5,6)]\ndef test_empty(): assert merge_intervals([])==[]\ndef test_contained(): assert merge_intervals([(1,10),(2,3)])==[(1,10)]\ndef test_bad():\n    with pytest.raises(ValueError): merge_intervals([(3,1)])\ndef test_nomutate():\n    x=[(3,4),(1,2)]; merge_intervals(x); assert x==[(3,4),(1,2)]\n"),
 "expr": ("hard", "def evaluate(expr: str) -> float: evaluate an arithmetic expression with numbers (ints or decimals like 2.5), + - * /, parentheses, unary minus/plus, arbitrary whitespace, standard precedence and left associativity. Do NOT use eval/exec/ast. Raise ValueError for malformed input (empty, unbalanced parens, dangling operators, two numbers in a row) and ZeroDivisionError for division by zero.",
   "from solution import evaluate\ndef test_prec(): assert evaluate('2+3*4')==14\ndef test_paren(): assert evaluate('(2+3)*4')==20\n",
   "import pytest\nfrom solution import evaluate\ndef test_left(): assert evaluate('8-3-2')==3\ndef test_div(): assert evaluate('8/4/2')==1\ndef test_unary(): assert evaluate('-(-3)')==3\ndef test_unary2(): assert evaluate('2*-3')==-6\ndef test_dec(): assert evaluate(' 2.5 * 2 ')==5\ndef test_plus(): assert evaluate('+4')==4\n@pytest.mark.parametrize('s',['','(1+2','1+','1 2','*3','()','1+2)'])\ndef test_bad(s):\n    with pytest.raises(ValueError): evaluate(s)\ndef test_zero():\n    with pytest.raises(ZeroDivisionError): evaluate('1/(2-2)')\n"),
 "csv": ("hard", "def parse_csv_line(line: str) -> list[str]: parse one RFC 4180 CSV record (no trailing newline). Fields separated by commas; a field may be double-quoted, inside which commas are literal and a doubled quote \"\" is one quote. Unquoted fields are taken literally (spaces kept). An empty line is [''] . Raise ValueError for an unterminated quoted field or characters after a closing quote other than a comma.",
   "from solution import parse_csv_line\ndef test_basic(): assert parse_csv_line('a,b,c')==['a','b','c']\ndef test_quote(): assert parse_csv_line('\"a,b\",c')==['a,b','c']\n",
   "import pytest\nfrom solution import parse_csv_line\ndef test_esc(): assert parse_csv_line('\"he said \"\"hi\"\"\",x')==['he said \"hi\"','x']\ndef test_empty(): assert parse_csv_line('')==['']\ndef test_empties(): assert parse_csv_line(',,')==['','','']\ndef test_spaces(): assert parse_csv_line(' a , b ')==[' a ',' b ']\ndef test_qempty(): assert parse_csv_line('\"\",a')==['','a']\ndef test_trailing(): assert parse_csv_line('a,')==['a','']\n@pytest.mark.parametrize('s',['\"abc','\"a\"b,c','\"a\" ,b'])\ndef test_bad(s):\n    with pytest.raises(ValueError): parse_csv_line(s)\n"),
}
MODELS = ["haiku", "sonnet", "opus"]
OUT = Path(__file__).parent / "results"; OUT.mkdir(exist_ok=True)


def attempt(name, model):
    level, spec, visible, hidden = P[name]
    d = Path(tempfile.mkdtemp(prefix=f"e5-{name}-{model}-"))
    (d / "test_visible.py").write_text(visible, encoding="utf-8")
    prompt = (f"Create solution.py in the current directory implementing:\n{spec}\n\nA starter test file test_visible.py exists. "
              "Hidden tests also check the edge cases described. Run tests with `uv run --no-project --with pytest python -m pytest -q`. "
              "Stdlib only. When done, reply DONE.")
    r1 = run_claude(prompt, model=model, cwd=d, budget=1.5, effort="medium" if model != "haiku" else "low", timeout=600)
    hd = d / "hidden"; hd.mkdir(exist_ok=True); (hd / "test_hidden.py").write_text(hidden, encoding="utf-8")
    p1, tot = pytest_counts(hd, pythonpath=d)
    rec = {"problem": name, "level": level, "model": model, "pass1": p1 == tot, "score1": f"{p1}/{tot}",
           "cost1": round(r1.cost, 4), "secs1": round(r1.seconds)}
    if p1 < tot:  # one retry with the failing test output, resuming the same session
        fail = subprocess.run(["uv", "run", "--no-project", "--with", "pytest", "python", "-m", "pytest", "-q", "--tb=line", "-p", "no:cacheprovider"],
                              cwd=hd, capture_output=True, text=True, env={**__import__("os").environ, "PYTHONPATH": str(d)}).stdout[-2500:]
        sid = r1.result.get("session_id")
        r2 = run_claude(f"Review found failures in solution.py. Fix them.\n{fail}\nReply DONE.", model=model, cwd=d, budget=1.5,
                        effort="medium" if model != "haiku" else "low", extra_args=["--resume", sid] if sid else [], timeout=600)
        p2, _ = pytest_counts(hd, pythonpath=d)
        rec.update({"pass2": p2 == tot, "score2": f"{p2}/{tot}", "cost2": round(r2.cost, 4), "secs2": round(r2.seconds)})
    return rec


jobs = [(n, m) for n in P for m in MODELS]
with ThreadPoolExecutor(max_workers=9) as ex:
    recs = list(ex.map(lambda a: attempt(*a), jobs))
(OUT / "e5.json").write_text(json.dumps(recs, indent=1), encoding="utf-8")
for m in MODELS:
    rs = [r for r in recs if r["model"] == m]
    fails = [r for r in rs if not r["pass1"]]
    print(m, "p(first)=", f"{sum(r['pass1'] for r in rs)}/{len(rs)}", "q(retry)=", f"{sum(r.get('pass2', False) for r in fails)}/{len(fails)}",
          "cost=", round(sum(r['cost1'] + r.get('cost2', 0) for r in rs), 3),
          [(r["problem"], r["score1"], r.get("score2")) for r in rs])
