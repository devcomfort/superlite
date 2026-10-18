"""Shared helpers for running pytest from the superlite scripts. Stdlib only.

pytest_cmd(): command prefix that runs pytest. Uses the current interpreter when it can
import pytest, else `uv run --no-project --with pytest python -m pytest`, else raises
PytestUnavailable with a clear message (`sl` may have fallen back to a bare
`uv run --no-project python`, which has no pytest).

run_tree(cmd, timeout, **kw): subprocess.run that, on timeout, kills the whole process
tree of the child it started (POSIX: new session + killpg; Windows: new process group +
`taskkill /T /F /PID <child>`), never by name. Raises subprocess.TimeoutExpired.
"""
import importlib.util
import os
import shutil
import signal
import subprocess
import sys


class PytestUnavailable(RuntimeError):
    pass


def have_pytest():
    return importlib.util.find_spec("pytest") is not None


def pytest_cmd():
    if have_pytest():
        return [sys.executable, "-m", "pytest"]
    uv = shutil.which("uv")
    if uv:
        return [uv, "run", "--no-project", "--with", "pytest", "python", "-m", "pytest"]
    raise PytestUnavailable("pytest is not installed for this interpreter "
                            f"({sys.executable}) and uv is not on PATH; "
                            "install pytest (pip install pytest) or uv")


def kill_tree(proc):
    """Kill proc and all its descendants. Only the process we started."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, check=False)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


def run_tree(cmd, timeout=None, **kw):
    if os.name == "nt":
        kw["creationflags"] = kw.get("creationflags", 0) | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    kw.setdefault("stdout", subprocess.PIPE)
    kw.setdefault("stderr", subprocess.PIPE)
    if kw.pop("capture_output", False):
        kw["stdout"] = kw["stderr"] = subprocess.PIPE
    with subprocess.Popen(cmd, **kw) as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as e:
            kill_tree(proc)
            proc.communicate()
            raise subprocess.TimeoutExpired(cmd, timeout, e.output, e.stderr) from None
        except BaseException:
            kill_tree(proc)
            raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
