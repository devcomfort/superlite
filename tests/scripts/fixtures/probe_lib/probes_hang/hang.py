"""A call that never returns; it records its own pid first (path from PROBE_PIDFILE)."""
import os
from pack._common import P

CATEGORY = "hangy"
PROBES = [P("spin", "call", lambda n, ctx: "@spin " + os.environ["PROBE_PIDFILE"])]
