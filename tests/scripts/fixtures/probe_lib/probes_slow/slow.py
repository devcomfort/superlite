"""20 probes that each sleep one second."""
from pack._common import P

CATEGORY = "slow"
PROBES = [P(f"sleep_{i}", "call", lambda n, ctx: "@sleep 1") for i in range(20)]
