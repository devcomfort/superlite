"""routing_evidence band tables on synthetic samples (no files, no agents)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bench"))
import routing_evidence as re_  # noqa: E402


def sample(model, loc, ftp=True, **kw):
    s = {"source": "run", "model": model, "loc": loc, "components": 1, "tests": "fast", "hard_focus": False, "critical": None,
         "duration_s": 50.0, "cost_usd": 0.01, "tool_calls": 5, "ftp": ftp}
    return {**s, **kw}


def test_band_table_counts_and_no_data():
    rows = re_.band_table([sample("haiku", 80), sample("haiku", 90, ftp=False), sample("haiku", 85, ftp=None), sample("sonnet", 200)])
    get = lambda f, b, m: next(r for r in rows if (r["feature"], r["band"], r["model"]) == (f, b, m))  # noqa: E731
    h = get("loc", "<=100", "haiku")
    assert (h["n"], h["n_observed_pass"], h["first_time_pass"]) == (3, 2, 1)
    assert get("loc", "151-300", "haiku")["note"] == "NO DATA" and get("loc", "151-300", "sonnet")["n"] == 1
    assert get("tests", "slow", "sonnet")["note"] == "NO DATA"


def test_wilson_and_economics_break_even():
    assert re_.wilson_lower(0, 0) is None
    assert 0.69 < re_.wilson_lower(9, 9) < 0.72
    ab = lambda m, d, c, prime="full": sample(m, 80, source="ab:x:" + prime, duration_s=d, cost_usd=c, prime=prime)  # noqa: E731
    samples = [ab("sonnet", 72.0, 0.12)] * 3 + [ab("haiku", 82.0, 0.01)] * 40
    fixer = {"n": 4, "median_s": 100.0, "median_cost_usd": 0.1}
    e = re_.economics(samples, fixer)[0]
    v = e["vs_sonnet"]["full"]
    assert v["base_penalty_s"] == 10.0 and v["cost_saved_per_task_usd"] == 0.11
    # +30 s: 10 + (1-p)*100 <= 30  ->  p >= 0.8 ; +15 s: p >= 0.95 ; +60 s: p >= 0.5
    assert v["break_even_first_time_pass"] == {"+15s": 0.95, "+30s": 0.8, "+60s": 0.5}
    assert e["min_first_time_pass"] == 0.9 and e["decidable"] is True  # no slack info: overflow 110 s -> p >= 1 - 15/110
    roomy = re_.economics(samples, fixer, {"proxy_all_tasks": {"median_slack_s_of_off_path": 200.0}})[0]
    assert roomy["cost_break_even_first_time_pass"] == 0.476 and roomy["min_first_time_pass"] == 0.5
    assert re_.economics([sample("sonnet", 80)], fixer)[1]["decidable"] is False  # 101-150: no Haiku data
