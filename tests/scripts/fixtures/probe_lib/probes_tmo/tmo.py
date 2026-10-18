"""A 3 s library stall: past the 2 s library timeout, inside the 10 s default."""
import os
from pack._common import P

CATEGORY = "tmo"
PROBES = [P("stall", "call", lambda n, ctx: "@sleep 3")]
