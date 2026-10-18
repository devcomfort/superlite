"""30 deep-nesting variants; against an unguarded parser they all fail in the same place."""
import os
from pack._common import P

CATEGORY = "deep"
PROBES = [P(f"nest_{i}", "call", lambda n, ctx, i=i: "(" * (3000 + i) + "1" + ")" * (3000 + i))
          for i in range(30)]
