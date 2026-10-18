"""Test double for incident.py add: appends the arguments as one JSON line."""
import json
import sys

args = sys.argv[1:]
assert args[0] == "add"
entry = {}
for key, val in zip(args[1::2], args[2::2]):
    entry[key.lstrip("-")] = val
log = entry.pop("log")
import os
os.makedirs(os.path.dirname(os.path.abspath(log)), exist_ok=True)
entry["line"] = int(entry["line"])
with open(log, "a", encoding="utf-8") as f:
    f.write(json.dumps(entry) + "\n")
