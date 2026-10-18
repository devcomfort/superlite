"""Build shape: `e.g.` examples, EXAMPLE and EDGE lint, prune, split NOTE, shape line."""
from __future__ import annotations

import json

from test_plan_tools import SCRIPTS, pt, run


def task(tid, produces=None, consumes=None, eg=(), comps=1, loc=100):
    lines = [f"### {tid} task {tid.lower()} · Complexity 3 · Est. context 30k", f"**Owns:** src/pkg/{tid.lower()}.py, tests/test_{tid.lower()}.py",
             f"**Components:** {comps}", f"**LOC owned:** {loc}", "**Tests:** fast"]
    if produces:
        lines.append(f"**Produces:** {produces}")
    lines += [f"e.g. {x}" for x in eg]
    if consumes:
        lines.append(f"**Consumes:** {consumes}")
    return "\n".join(lines) + "\n\n"


def plan(tmp_path, tasks, edges, name="plan.md"):
    head = ("# Plan\n**Goal:** x.\n**Tech stack:** TypeScript\n\n```mermaid\n%% taskgraph\nflowchart LR\n"
            + "".join(f"  {a} --> {b}\n" for a, b in edges) + "```\n\n")
    p = tmp_path / name
    p.write_text(head + "".join(tasks), encoding="utf-8")
    return p


PARSE = "lang.parse(src: string) -> Ast"
EG = 'lang.parse("1+2") -> Binary("+", Num(1), Num(2))'


def two(tmp_path, eg=(), ret="Ast", name="plan.md", extra_edge=True):
    prod = f"lang.parse(src: string) -> {ret}"
    cons = f"lang.parse(src: string) -> {ret}"
    return plan(tmp_path, [task("T1", prod, eg=eg), task("T2", None, cons)], [("T1", "T2")] if extra_edge else [], name)


def issues(p, *extra):
    return run(SCRIPTS / "plan_tools.py", "lint", "--plan", p, *extra).out


def test_examples_are_parsed_under_produces():
    import sys
    sys.path.insert(0, str(SCRIPTS))
    import plan_tools
    text = "```mermaid\n%% taskgraph\nflowchart LR\n  T1\n```\n\n" + task("T1", PARSE, eg=[EG, 'lang.parse("") -> Empty()'])
    t = plan_tools.Plan(text).tasks[0]
    assert t.examples == [EG, 'lang.parse("") -> Empty()'] and t.produces == [PARSE]


def test_example_lint_flags_a_consumer_of_structured_data_without_examples(tmp_path):
    out = issues(two(tmp_path))
    assert "ISSUE: EXAMPLE: T2 consumes lang.parse but its Produces line has no e.g." in out
    assert "EXAMPLE" not in issues(two(tmp_path, eg=[EG], name="ok.md"))


def test_example_lint_exempts_primitive_returns(tmp_path):
    assert "EXAMPLE" not in issues(two(tmp_path, ret="string", name="prim.md"))


def test_example_lint_makes_the_consumer_a_fix_task(tmp_path):
    pt("lint", "--stable", "--plan", two(tmp_path), cwd=tmp_path)
    data = json.loads((tmp_path / ".superlite" / "stable.json").read_text(encoding="utf-8"))
    assert data["stable"] == ["T1"] and any("EXAMPLE: T2" in r for f in data["fix"] for r in f["reasons"])
    pt("lint", "--stable", "--plan", two(tmp_path, eg=[EG]), cwd=tmp_path)
    assert json.loads((tmp_path / ".superlite" / "stable.json").read_text(encoding="utf-8"))["stable"] == ["T1", "T2"]


def test_edge_lint_names_a_removable_edge_with_the_new_critical_path(tmp_path):
    out = issues(two(tmp_path, eg=[EG]))
    assert "EDGE: T2 waits for T1 only for interfaces that have examples; drop the edge (critical path T" in out
    assert "EDGE" not in issues(two(tmp_path, name="noeg.md"))  # no example: not removable


def test_edge_is_not_removable_when_one_consumed_interface_lacks_an_example(tmp_path):
    prod = "lang.parse(src: string) -> Ast · lang.lex(src: string) -> Tokens"
    cons = "lang.parse(src: string) -> Ast · lang.lex(src: string) -> Tokens"
    p = plan(tmp_path, [task("T1", prod, eg=[EG]), task("T2", None, cons)], [("T1", "T2")])
    assert "EDGE:" not in issues(p)


def test_edge_without_a_consumed_interface_is_never_removable(tmp_path):
    p = plan(tmp_path, [task("T1", PARSE, eg=[EG]), task("T2")], [("T1", "T2")])
    assert "EDGE:" not in issues(p)


def test_prune_drops_removable_edges_and_recomputes_the_schedule(tmp_path):
    p = plan(tmp_path, [task("T1", PARSE, eg=[EG]), task("T2", "lang.run(a: Ast) -> Out", PARSE),
                        task("T3", None, "lang.run(a: Ast) -> Out"), task("T4")],
             [("T1", "T2"), ("T2", "T3"), ("T3", "T4")])
    before = run(SCRIPTS / "plan_tools.py", "schedule", "--plan", p).out
    assert "critical path: T1" in before
    cp = run(SCRIPTS / "plan_tools.py", "prune", "--plan", p, cwd=tmp_path)
    assert cp.returncode == 0, cp.both
    assert cp.out.strip() == "pruned: T1->T2"  # T3 lacks an example on T2's Produces; T4 consumes nothing
    text = p.read_text(encoding="utf-8")
    assert "T1 --> T2" not in text and "T2 --> T3" in text and "T3 --> T4" in text
    assert "%% schedule" in text  # schedule --insert ran again
    again = run(SCRIPTS / "plan_tools.py", "prune", "--plan", p, cwd=tmp_path)
    assert again.out.strip() == "pruned: no removable edges"


def test_prune_keeps_edges_of_dispatched_consumers(tmp_path):
    p = two(tmp_path, eg=[EG])
    sl = tmp_path / ".superlite"
    sl.mkdir()
    (sl / "pool.json").write_text(json.dumps({"agents": [{"id": "a", "tasks": ["T2"], "current": "T2"}]}), encoding="utf-8")
    cp = run(SCRIPTS / "plan_tools.py", "prune", "--plan", p, cwd=tmp_path)
    assert cp.out.strip() == "pruned: no removable edges" and "T1 --> T2" in p.read_text(encoding="utf-8")


def test_prune_rewrites_chains_and_groups(tmp_path):
    prod = "lang.parse(src: string) -> Ast"
    p = plan(tmp_path, [task("T1", prod, eg=[EG]), task("T2", None, prod), task("T3")], [])
    text = p.read_text(encoding="utf-8").replace("flowchart LR\n", "flowchart LR\n  T1 --> T2 --> T3\n  subgraph s\n  T3\n  end\n", 1)
    p.write_text(text, encoding="utf-8")
    assert run(SCRIPTS / "plan_tools.py", "prune", "--plan", p, cwd=tmp_path).out.strip() == "pruned: T1->T2"
    new = p.read_text(encoding="utf-8")
    assert "T2 --> T3" in new and "T1 --> T2" not in new and "subgraph s" in new
    assert run(SCRIPTS / "plan_tools.py", "lint", "--plan", p).returncode == 0


def test_split_note_for_a_multi_component_task_with_independent_consumes(tmp_path):
    cons = "server.start(port: int) -> Handle · ui.render(state: State) -> Html"
    p = plan(tmp_path, [task("T1", "server.start(port: int) -> Handle", eg=['server.start(0) -> Handle(8080)']),
                        task("T2", "ui.render(state: State) -> Html", eg=['ui.render(S()) -> Html("<p>")']), task("T3", None, cons, comps=2)],
             [("T1", "T3"), ("T2", "T3")])
    out = issues(p)
    assert "NOTE: T3 has 2 components and consumes independent interfaces (server.start, ui.render); consider splitting it" in out
    single = plan(tmp_path, [task("T1", "server.start(port: int) -> Handle", eg=['server.start(0) -> Handle(1)']), task("T3", None, "server.start(port: int) -> Handle", comps=2)],
                  [("T1", "T3")], name="single.md")
    assert "independent interfaces" not in issues(single)


def test_schedule_prints_the_shape_line(tmp_path):
    out = run(SCRIPTS / "plan_tools.py", "schedule", "--plan", two(tmp_path, eg=[EG])).out
    line = [ln for ln in out.splitlines() if ln.startswith("shape:")][0]
    assert "chain 2 tasks" in line and "removable edges 1" in line and "min without them)" in line
    plain = run(SCRIPTS / "plan_tools.py", "schedule", "--plan", two(tmp_path, name="p2.md")).out
    assert "removable edges 0" in plain and "without them" not in plain
    assert "shape" in json.loads(run(SCRIPTS / "plan_tools.py", "schedule", "--plan", two(tmp_path, name="p3.md"), "--json").out)


def test_example_lines_do_not_break_the_next_field(tmp_path):
    import sys
    sys.path.insert(0, str(SCRIPTS))
    import plan_tools
    text = "```mermaid\n%% taskgraph\nflowchart LR\n  T1\n```\n\n" + task("T1", PARSE, eg=[EG], consumes="other.f(x: int) -> int")
    t = plan_tools.Plan(text).tasks[0]
    assert t.produces == [PARSE] and t.consumes == ["other.f(x: int) -> int"] and t.examples == [EG]
