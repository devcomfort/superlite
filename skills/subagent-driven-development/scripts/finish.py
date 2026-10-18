#!/usr/bin/env python3
"""Print the closing summary of a run.

    finish.py [--ledger .superlite/progress.md] [--log .superlite/incidents.jsonl]

Collects, from the progress ledger, every `Ruling:` line (in order), the
commits and the last test counts, plus the open incidents from the log.
Deterministic: the same files give the same text. Stdlib only.
"""
# Complexity notation:
#   R = lines in the progress ledger, I = lines in the incident log, C = commits and G = rulings found,
#   w = width of one line
import argparse  # O(1)
import json  # O(1)
from datetime import datetime, timedelta  # O(1)
import re  # O(1)
import sys  # O(1)
from pathlib import Path  # O(1)

DEFAULT_LEDGER = ".superlite/progress.md"  # O(1)
DEFAULT_LOG = ".superlite/incidents.jsonl"  # O(1)
DEFAULT_LINT_LOG = ".superlite/lint-log.jsonl"  # O(1)
UNBLOCKED = re.compile(r"^\s*[-*+]?\s*unblocked:\s*dispatched\s+((?:T\d+[A-Za-z]?\s*)+?)\s*at\s+(\d\d:\d\d:\d\d)")  # O(1)

RULING = re.compile(r"^\s*(?:[-*+]\s+)?(?:\*\*)?Ruling:(?:\*\*)?\s*(.*?)\s*$")  # O(1)
COMMIT = re.compile(r"^\s*[-*+]?\s*commit\s+(T\d+[A-Za-z]?)\s+([0-9a-f]{7,40})\s*(.*?)\s*$")  # O(1)
TESTS = re.compile(r"^\s*[-*+]?\s*tests\s+(\w+)\s+passed=(\d+)\s+failed=(\d+)"  # O(1)
                   r"\s+skipped=(\d+)\s+seconds=([\d.]+)")  # O(1)


def read_ledger(path):  # O(R*w)
    p = Path(path)  # O(1)
    if not p.exists():  # O(1) stat
        return [], [], None  # O(1)
    rulings, commits, tests = [], [], None  # O(1)
    for line in p.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n"):  # O(R) iterations; read + split O(ledger bytes)
        m = RULING.match(line)  # O(w) regex
        if m:  # O(1)
            rulings.append(m.group(1))  # O(1)
            continue  # O(1)
        m = COMMIT.match(line)  # O(w) regex
        if m:  # O(1)
            commits.append(m.groups())  # O(1)
            continue  # O(1)
        m = TESTS.match(line)  # O(w) regex
        if m:  # O(1)
            tests = m.groups()  # O(1)
    return rulings, commits, tests  # O(1)


def open_incidents(path):  # O(I*w)
    p = Path(path)  # O(1)
    out = []  # O(1)
    if not p.exists():  # O(1) stat
        return out  # O(1)
    for ln in p.read_text(encoding="utf-8").splitlines():  # O(I) iterations; read O(log bytes)
        try:  # O(1)
            e = json.loads(ln)  # O(w)
        except json.JSONDecodeError:  # O(1)
            continue  # O(1)
        if (isinstance(e, dict) and "file" in e and e.get("kind") != "verified"  # O(1)
                and e.get("resolution") in (None, "open", "unresolved")):  # O(1)
            out.append(e)  # O(1)
    return out  # O(1)


def unblocked_report(ledger, lint_log):  # O(R*w + L*n)
    """One line: were all stable tasks dispatched before the next patch, and the largest stable-to-dispatch lag."""
    lp = Path(lint_log)  # O(1)
    if not lp.exists():  # O(1)
        return "unblocked: no lint log recorded"  # O(1)
    runs = []  # O(1)
    for ln in lp.read_text(encoding="utf-8").splitlines():  # O(L) iterations
        try:  # O(1)
            e = json.loads(ln)  # O(w)
            runs.append((datetime.fromisoformat(e["time"]), e))  # O(1)
        except (ValueError, KeyError, TypeError):  # O(1)
            continue  # O(1)
    if not runs:  # O(1)
        return "unblocked: no lint log recorded"  # O(1)
    sent = []  # (task, clock text) per `unblocked:` line | O(1)
    ledger_p = Path(ledger)  # O(1)
    for line in (ledger_p.read_text(encoding="utf-8").splitlines() if ledger_p.exists() else []):  # O(R)
        m = UNBLOCKED.match(line)  # O(w)
        if m:  # O(1)
            sent += [(t, m.group(2)) for t in m.group(1).split()]  # O(tasks)
    first_stable = {}  # task -> time it first became stable | O(1)
    for when, e in runs:  # O(L)
        for t in e.get("newly_stable") or []:  # O(n)
            first_stable.setdefault(t, when)  # O(1)
    sent_at = {}  # O(1)
    for t, clock in sent:  # O(tasks)
        if t in sent_at or t not in first_stable:  # O(1)
            continue  # O(1)
        base = first_stable[t]  # O(1)
        at = datetime.combine(base.date(), datetime.strptime(clock, "%H:%M:%S").time())  # O(1)
        sent_at[t] = at + timedelta(days=1) if at < base - timedelta(seconds=1) else at  # O(1)
    held = sorted({t for (_, a), (_, b) in zip(runs, runs[1:])  # stable at one lint, still pending at the next | O(L*n)
                   for t in set(a.get("pending") or []) & set(b.get("pending") or [])})
    lags = [(sent_at[t] - first_stable[t]).total_seconds() for t in sent_at]  # O(tasks)
    missing = sorted(t for t in first_stable if t not in sent_at and t in set(runs[-1][1].get("pending") or []))  # O(n)
    worst = f"max lag {max(0, max(lags)):.0f}s" if lags else "max lag n/a (no `unblocked:` lines)"  # O(1)
    if held:  # O(1)
        return f"unblocked: NO - {' '.join(held)} still waiting at the next lint; {worst}"  # O(1)
    if missing:  # O(1)
        return f"unblocked: NO - never dispatched: {' '.join(missing)}; {worst}"  # O(1)
    return f"unblocked: yes - every stable task was dispatched before the next patch; {worst}"  # O(1)


def history_section(plan, sl_dir):  # O(M + B + n*(n + e))
    """Append the run's rows to history (global and project), refresh stats, and report predicted against actual."""
    sl = Path(sl_dir)  # O(1)
    if not plan or not (sl / "metrics.jsonl").is_file():  # O(1)
        return "history: no metrics.jsonl or plan, nothing recorded"  # O(1)
    sys.path.insert(0, str(Path(__file__).resolve().parent))  # O(1)
    try:  # O(1)
        import history  # O(1)
        rows = history.record_run(plan, sl_dir)  # O(M + B)
    except Exception as e:  # noqa: BLE001 | O(1)
        return f"history: not recorded ({e})"  # O(1)
    out = [f"history: {len(rows)} rows appended; predicted vs actual (min):"]  # O(1)
    pred = act = 0.0  # O(1)
    for r in rows:  # O(n)
        a = (r["duration_s"] or 0) / 60.0  # O(1)
        p = r.get("pred_min")  # O(1)
        out.append(f"- {r['task']} {r['tier']} predicted {p if p is not None else 'n/a'} actual {a:.1f} ${r['cost_usd']:.3f}"  # O(1)
                   + ("" if r["first_time_pass"] is not False else " FIRST-TIME MISS"))
        pred += p or 0.0  # O(1)
        act += a  # O(1)
    out.append(f"run: predicted {pred:.1f} actual {act:.1f} task-min, cost ${sum(r['cost_usd'] + (r['rework_cost'] or 0) for r in rows):.2f}")  # O(n)
    return chr(10).join(out)  # O(n)


def summary(ledger, log, lint_log=DEFAULT_LINT_LOG, plan=None, sl_dir=None):  # O(R*w + I*w + C + G)
    rulings, commits, tests = read_ledger(ledger)  # O(R*w)
    incidents = open_incidents(log)  # O(I*w)
    out = ["# superlite run summary", ""]  # O(1)
    out.append(f"commits: {len(commits)}")  # O(1)
    out += [f"- {t} {sha[:10]} {title}".rstrip() for t, sha, title in commits]  # O(C)
    out.append("")  # O(1)
    out.append(f"rulings: {len(rulings)}")  # O(1)
    out += [f"- {r}" for r in rulings]  # O(G)
    out.append("")  # O(1)
    if tests:  # O(1)
        mode, p, f, s, sec = tests  # O(1)
        out.append(f"tests ({mode}): {p} passed, {f} failed, {s} skipped in {sec}s")  # O(1)
    else:  # O(1)
        out.append("tests: none recorded")  # O(1)
    out.append("")  # O(1)
    out.append(unblocked_report(ledger, lint_log))  # see unblocked_report
    out.append("")  # O(1)
    if plan is not None:  # O(1)
        out.append(history_section(plan or None, sl_dir or str(Path(ledger).parent)))  # see history_section
        out.append("")  # O(1)
    out.append(f"open incidents: {len(incidents)}")  # O(1)
    for e in incidents:  # O(I) iterations
        kind = e.get("kind") or "unknown"  # O(1)
        out.append(f"- {e['file']}:{e['line']} [{kind}] {e.get('context', '')}")  # O(w)
    return "\n".join(out) + "\n"  # O(R + C + G + I) join


def main(argv=None):  # O(R*w + I*w)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])  # O(1)
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)  # O(1)
    ap.add_argument("--log", default=DEFAULT_LOG)  # O(1)
    ap.add_argument("--plan", help="record this run into history (needs .superlite/metrics.jsonl)")  # O(1)
    ap.add_argument("--lint-log", help="default: lint-log.jsonl next to the ledger")  # O(1)
    a = ap.parse_args(argv)  # O(1)
    sys.stdout.reconfigure(encoding="utf-8")  # O(1)
    sys.stdout.write(summary(a.ledger, a.log, a.lint_log or str(Path(a.ledger).with_name("lint-log.jsonl")), a.plan))  # O(output)
    return 0  # O(1)


if __name__ == "__main__":  # O(1)
    sys.exit(main())  # O(1)
