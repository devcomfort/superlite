"""Probe adapter for the library fixture. The @-commands exist only so tests can provoke hangs."""
import os
import sys
import time

_here = os.path.dirname(os.path.abspath(__file__))
for _d in (os.path.join(_here, "src"), os.path.join(_here, "..", "..", "src")):
    sys.path.insert(0, _d)
import parser as fixture_parser  # noqa: E402

EXPECTED_ERRORS = (ValueError,)
GOOD_INPUT = "(1+2)-3"


def call(text):
    if text.startswith("@sleep "):
        time.sleep(float(text.split()[1]))
        return "slept"
    if text.startswith("@spin "):
        with open(text.split()[1], "w") as f:
            f.write(str(os.getpid()))
        while True:
            pass
    return fixture_parser.parse(text)
