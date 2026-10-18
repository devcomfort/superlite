"""20 requests with a server crash in the middle (GET /crash closes the listener)."""
from pack._common import P

CATEGORY = "http"
PROBES = [P(f"echo_{i}", "request", lambda n, ctx, i=i: ("GET", "/crash" if i == 10 else f"/echo?i={i}", None))
          for i in range(20)]
