"""Beyond-SPEC robustness probes for minisheet, scored separately from the hidden suite.

From the Opus review of the minisheet runs (2026-10-17). The SPEC is silent on most of these
(the reference implementation itself fails them), so they are a quality signal, not conformance:
a robust engine must not crash or leak non-finite numbers on hostile but plausible input.
"""
import http.client
import math
import subprocess
import sys
import threading

import pytest


def _set(raw):
    from minisheet.workbook import Workbook

    wb = Workbook()
    wb.set("A1", raw)
    return wb.get("A1")


@pytest.mark.parametrize("raw", [
    "=" + "(" * 100 + "1" + ")" * 100,
    "=" + "+".join(["1"] * 5000),
    "=" + "-" * 1500 + "1",
], ids=["parens100", "terms5000", "unary1500"])
def test_deep_or_long_formula_does_not_crash(raw):
    _set(raw)  # any value or error value is fine; an exception is not


def test_huge_literal_is_not_infinite():
    v = _set("=1e999")
    assert not (isinstance(v, float) and math.isinf(v))


def test_huge_argument_does_not_crash():
    _set('=LEFT("abc",1e999)')


def test_cli_survives_a_deep_formula():
    deep = "=" + "(" * 2000 + "1" + ")" * 2000
    proc = subprocess.run([sys.executable, "-m", "minisheet"], input=f"set A1 {deep}\nset B1 7\nget B1\n",
                          capture_output=True, text=True, timeout=60)
    assert "7" in proc.stdout.splitlines()[-1] if proc.stdout.strip() else False


def test_unsupported_http_method_gets_404_json():
    from minisheet import server
    from minisheet.workbook import Workbook

    srv = server.create_server(Workbook(), 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
        conn.request("TRACE", "/api/cells")
        resp = conn.getresponse()
        assert resp.status == 404 and b"not found" in resp.read()
    finally:
        srv.shutdown()
