"""Probe adapter template. Copy to .superlite/probes/adapter.py and fill in what applies.

Define only the entry kinds the project has; probes for a missing kind are skipped.

  call(text)                 library entry: feed text, return a value, or raise one of
                             EXPECTED_ERRORS to reject it. Any other exception is a crash.
  run(args, stdin)           CLI entry: return (returncode, stdout, stderr). A negative or
                             0xC000xxxx return code, or a Traceback in stderr, is a crash.
  request(method, path, body)  server entry: return (status, parsed_json_or_None). The runner
                             sets PORT after calling start_server(); body is str, bytes or None.
  start_server()             start the server on port 0 and return (port, stop) where stop is a
                             callable or None; a server object with .server_address and
                             .shutdown() is accepted too. The runner starts one per worker,
                             health-checks it after every probe, and restarts it only if it died.

Optional knobs: EXPECTED_ERRORS, GOOD_INPUT, GOOD_ARGS, GOOD_STDIN, GOOD_PATH (a stateless valid
use of each entry, used by the state probes), and health() -> bool.
"""
import http.client
import json
import os
import subprocess
import sys

EXPECTED_ERRORS = (ValueError,)
GOOD_INPUT = "1"
GOOD_ARGS = []
GOOD_STDIN = ""
GOOD_PATH = "/"

PORT = None  # set by the runner

# The runner passes the per-probe timeout so a CLI that hangs is stopped with its own children.
TIMEOUT = float(os.environ.get("SUPERLITE_PROBE_TIMEOUT", "5"))
CLI = [sys.executable, "-m", "your_package"]  # edit: how to start the CLI


def call(text):
    from your_package import evaluate  # edit: the library entry point
    return evaluate(text)


def run(args, stdin):
    p = subprocess.run(CLI + list(args), input=stdin if isinstance(stdin, bytes) else stdin.encode("utf-8", "surrogateescape"),
                       capture_output=True, timeout=TIMEOUT)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def start_server():
    from your_package.server import create_server  # edit: factory that binds ("127.0.0.1", 0)
    import threading
    server = create_server(("127.0.0.1", 0))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1], server.shutdown


def request(method, path, body):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=TIMEOUT)
    try:
        if isinstance(body, str):
            body = body.encode("utf-8", "surrogateescape")
        conn.request(method, path, body=body)
        resp = conn.getresponse()
        data = resp.read()
        try:
            parsed = json.loads(data) if data else None
        except ValueError:
            parsed = data[:200].decode("utf-8", "replace")
        return resp.status, parsed
    finally:
        conn.close()
