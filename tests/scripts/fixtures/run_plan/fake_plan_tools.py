"""Test double for plan_tools.py taskgraph: reads the `%% taskgraph` edges."""
import json
import re
import sys

plan = sys.argv[sys.argv.index("--plan") + 1]
text = open(plan, encoding="utf-8").read()
graph = {m: [] for m in re.findall(r"^### (T\d+[a-z]?)\b", text, re.M)}
block = text.split("%% taskgraph", 1)[1].split("```", 1)[0]
for a, b in re.findall(r"(T\d+[a-z]?)\s*-->\s*(T\d+[a-z]?)", block):
    graph[b].append(a)
print(json.dumps(graph))
