"""20 cheap requests: all should share one server."""
from pack._common import P

CATEGORY = "http"
PROBES = [P(f"echo_{i}", "request", lambda n, ctx, i=i: ("GET", f"/echo?i={i}", None)) for i in range(20)]
