"""Test double for pt_review.py: appends its argv to .superlite/pt_marker.txt, one line per call."""
import os
import sys

os.makedirs(".superlite", exist_ok=True)
with open(os.path.join(".superlite", "pt_marker.txt"), "a", encoding="utf-8") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
