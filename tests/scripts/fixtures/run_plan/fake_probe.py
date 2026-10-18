"""Test double for probe_run.py: records its argv."""
import sys

with open("probe_marker.txt", "w", encoding="utf-8") as f:
    f.write(" ".join(sys.argv[1:]))
