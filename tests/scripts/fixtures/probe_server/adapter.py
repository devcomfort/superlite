"""Probe adapter for the server fixture."""
import http.client
import json
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
import fixture_site  # noqa: E402

EXPECTED_ERRORS = (ValueError,)
PORT = None


def start_server():
    server = fixture_site.create_server(("127.0.0.1", 0))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1], server.shutdown


def request(method, path, body):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=8)
    try:
        if isinstance(body, str):
            body = body.encode("utf-8", "surrogateescape")
        conn.request(method, path, body=body)
        resp = conn.getresponse()
        data = resp.read()
        try:
            return resp.status, (json.loads(data) if data else None)
        except ValueError:
            return resp.status, None
    finally:
        conn.close()
