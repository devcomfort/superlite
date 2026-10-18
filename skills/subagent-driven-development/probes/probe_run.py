#!/usr/bin/env python3
"""Parallel probe runner (no agents). Stdlib only, Python >= 3.12.

    probe_run.py --adapter PATH [--root DIR] [--app-type T] [--probes DIR]
                 [--categories deep,numeric,...] [--files a,b | --commit SHA]
                 [--timeout 10] [--workers N] [--out .superlite/probes/probe-results.json]
                 [--log .superlite/incidents.jsonl] [--background]

Results file (--out, default <root>/.superlite/probes/probe-results.json):
    {"files": [...], "selected_categories": [...], "categories": {cat: {"status", "cached", "probes",
      "files", ...}}, "failures": [group, ...], "stats": {...}, "probes": [probe, ...]}
  probe: id, category, entry (call|run|request|raw), status, file, line, group_id, input_size,
         message (plus detail, size, elapsed, timeout). status is pass | crash | hang | leak |
         wrong-status; also inconsistent (state check failed), skip, error (probe bug).
         file and line are the innermost in-repo frame of the failure (null on a pass or when
         none is known); group_id points into "failures"; input_size is the size step reached.
  group (one incident each): group_id, key, category, kind, exc, count, probes, size,
         shrunk_size, file, line, regression_test, incident.

Exit code: 0 all probes passed, 1 at least one failure, 2 usage or adapter error.

How it works
  * Probe generators live in pack/<category>.py; project probes (written by the reviewer from the
    plan's Review Focus) go in a --probes DIR, same format (see pack/_common.py).
  * Workers are persistent subprocesses (one thread of a ThreadPoolExecutor drives each). A worker
    imports the adapter once, runs probes, and keeps one server (started on port 0) for all of its
    server probes. The server is health-checked after every probe and restarted only if it died.
  * A probe that does not answer within its category timeout (call 2 s, run 5 s, request 10 s) is a
    hang: that worker's process tree is killed by PID and the worker is replaced. Only PIDs this
    runner started are ever killed; never by image name.
  * Sized probes step up (e.g. 100, 2000, 10000) and stop at the first failure.
  * Failures are grouped by root cause (kind + exception + innermost in-repo file:line), shrunk by
    bisection (<= 5 s per group), turned into tests/regression/test_probe_<cat>_<n>.py and logged as
    one incident per group. Passing categories log a `verified` entry per file.
  * Passes are cached by (category, file, content hash) in <root>/.superlite/probes/cache.json. The
    hash covers the file, the adapter and the probe sources. Failures are always re-probed.
  * Categories with a `verified` entry (a reviewer's, or this runner's with the same hash) for a
    file are skipped for that file.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import importlib.util
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

IS_WIN = sys.platform == "win32"
ENTRY_TIMEOUT = {"call": 2.0, "run": 5.0, "request": 10.0, "raw": 10.0}
CATEGORY_ORDER = ["deep", "numeric", "encoding", "protocol", "file", "state"]
APP_TYPES = {
    "library": ["deep", "numeric", "encoding", "state"],
    "cli": ["protocol", "encoding", "state", "file"],
    "http": ["protocol", "encoding", "numeric", "state"],
    "web-ui": ["protocol", "encoding"],
    "file-io": ["file", "encoding", "deep"],
    "pipeline": ["numeric", "encoding", "state", "deep"],
    "concurrency": ["state", "protocol"],
    "auth": ["protocol", "state"],
}
APP_ALIASES = {"parser": "library", "evaluator": "library", "server": "http", "service": "http",
               "http-service": "http", "web": "web-ui", "ui": "web-ui", "generator": "file-io",
               "file": "file-io", "data-pipeline": "pipeline"}
TRACE_MARK = "Traceback (most recent call last)"
LEAK_MARKERS = ("root:x:0:0", "for 16-bit app support", "[extensions]")
BENIGN_5XX = {501, 505}
CODE_EXT = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb", ".java",
            ".cs", ".php", ".sh"}
SKIP_DIRS = {".git", ".superlite", "tests", "test", "__pycache__", "venv", ".venv", "node_modules",
             "regression", "site-packages", "dist", "build"}
SHRINK_BUDGET = 5.0
FRAME_RE = re.compile(r'File "([^"]+)", line (\d+)')


# ----------------------------------------------------------------------------- helpers
def kill_tree(proc: subprocess.Popen) -> None:
    """Kill the process we started and its descendants, by PID only."""
    pid = proc.pid
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                           timeout=15)
        else:
            import signal
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def load_module(path: Path):
    name = "_probemod_" + hashlib.md5(str(path).encode()).hexdigest()[:10]
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def probe_modules(extra: Path | None) -> list[Path]:
    mods = [HERE / "pack" / f"{c}.py" for c in CATEGORY_ORDER if (HERE / "pack" / f"{c}.py").exists()]
    if extra and extra.is_dir():
        mods += sorted(p for p in extra.glob("*.py") if not p.name.startswith("_"))
    return mods


def load_catalog(extra: Path | None) -> tuple[list[dict], list[str]]:
    catalog, errors = [], []
    for path in probe_modules(extra):
        try:
            mod = load_module(path)
            cat = mod.CATEGORY
            for p in mod.PROBES:
                catalog.append({"id": f"{cat}/{p['name']}", "category": cat, "name": p["name"],
                                "entry": p["entry"], "sizes": p["sizes"] or [None],
                                "module": str(path), "regress": p.get("regress", True),
                                "has_check": p.get("check") is not None})
        except Exception as e:
            errors.append(f"{path.name}: {type(e).__name__}: {e}")
    return catalog, errors


def frames_from_text(text: str) -> list[tuple[str, int]]:
    """Innermost-first frames from a Python traceback, a faulthandler dump or both."""
    if "most recent call first" in text:
        text = text[text.index("most recent call first"):]
        return [(f, int(n)) for f, n in FRAME_RE.findall(text)]
    if TRACE_MARK in text:
        chunk = text[text.rindex(TRACE_MARK):]
        return [(f, int(n)) for f, n in FRAME_RE.findall(chunk)][::-1]
    return []


def exc_from_text(text: str) -> str:
    for line in reversed([x for x in text.strip().splitlines() if x.strip()]):
        m = re.match(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning)?)\b:?", line)
        if m and not line.startswith((" ", "\t")):
            return m.group(1)
    return "Exception"


# ----------------------------------------------------------------------------- worker side
class _WorkerState:
    adapter = None
    ctx = None
    server_starts = 0
    port = None
    stop = None


def _start_server(st: _WorkerState) -> None:
    ad = st.adapter
    r = ad.start_server()
    stop = None
    if isinstance(r, tuple):
        port, stop = r[0], (r[1] if len(r) > 1 else None)
    elif hasattr(r, "server_address"):
        port, stop = r.server_address[1], getattr(r, "shutdown", None)
    else:
        port = int(r)
    st.port, st.stop = port, stop
    st.server_starts += 1
    ad.PORT = port
    os.environ["SUPERLITE_PROBE_PORT"] = str(port)


def _stop_server(st: _WorkerState) -> None:
    if st.stop:
        t = threading.Thread(target=lambda: _safe(st.stop), daemon=True)
        t.start()
        t.join(2)
    st.stop = None


def _safe(fn):
    try:
        fn()
    except Exception:
        pass


def _healthy(st: _WorkerState) -> bool:
    if hasattr(st.adapter, "health"):
        try:
            return bool(st.adapter.health())
        except Exception:
            return False
    try:
        socket.create_connection(("127.0.0.1", st.port), 1.0).close()
        return True
    except OSError:
        return False


def _raw_request(port: int, data: bytes, timeout: float) -> int:
    with socket.create_connection(("127.0.0.1", port), timeout) as s:
        s.settimeout(timeout)
        try:
            s.sendall(data)
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        buf = b""
        try:
            while len(buf) < 65536:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if b"\r\n" in buf and len(buf) > 12:
                    break
        except (ConnectionResetError, ConnectionAbortedError):
            pass
    m = re.match(rb"HTTP/\d\.\d (\d{3})", buf)
    return int(m.group(1)) if m else 0


def _bad_status(status: int, expect) -> str | None:
    if expect and expect.get("status"):
        return None if status in expect["status"] else f"status {status} not in {sorted(expect['status'])}"
    if 500 <= status < 600 and status not in BENIGN_5XX:
        return f"status {status}"
    return None


def _exec_one(st: _WorkerState, entry: str, item, expect, timeout: float):
    """Return (normalized_result, problem|None). problem = dict(status, detail, ...)."""
    ad = st.adapter
    expected = tuple(getattr(ad, "EXPECTED_ERRORS", (ValueError,)))
    try:
        if entry in ("request", "raw") and (st.port is None or not _healthy(st)):
            if st.port is not None:
                _stop_server(st)
            _start_server(st)
        if entry == "call":
            try:
                r = ad.call(item)
                res, text = ("ok", repr(r)[:500]), repr(r)
            except expected as e:
                res, text = ("err", type(e).__name__), ""
        elif entry == "run":
            try:
                rc, out, err = ad.run(*item)
            except expected as e:
                return ("err", type(e).__name__), None
            out = out.decode("utf-8", "replace") if isinstance(out, bytes) else str(out)
            err = err.decode("utf-8", "replace") if isinstance(err, bytes) else str(err)
            res, text = ("rc", rc, out[:500]), out
            if rc < 0 or rc >= 0xC0000000 or TRACE_MARK in err:
                return res, {"status": "crash", "exc": exc_from_text(err) if TRACE_MARK in err
                             else f"exit {rc}", "detail": err.strip()[-200:] or f"exit code {rc}",
                             "frames": frames_from_text(err)}
        elif entry == "request":
            try:
                status, js = ad.request(*item)
            except expected as e:
                return ("err", type(e).__name__), None
            res, text = ("status", status), "" if js is None else json.dumps(js, default=str)
            bad = _bad_status(status, expect)
            if bad:
                return res, {"status": "wrong-status", "detail": bad, "http": status}
        else:  # raw
            status = _raw_request(st.port, item, timeout)
            res, text = ("status", status), ""
            bad = None if status == 0 else _bad_status(status, expect)
            if bad:
                return res, {"status": "wrong-status", "detail": bad, "http": status}
    except BaseException as e:  # noqa: BLE001 - any unexpected exception is a crash
        frames = [(f.filename, f.lineno) for f in traceback.extract_tb(e.__traceback__)][::-1]
        return None, {"status": "crash", "exc": type(e).__name__, "detail": str(e)[:200],
                      "frames": frames}
    if TRACE_MARK in text:
        return res, {"status": "leak", "detail": "stack trace in output", "leak": "traceback"}
    for mark in LEAK_MARKERS:
        if mark in text:
            return res, {"status": "leak", "detail": f"system file content served ({mark})",
                         "leak": "file-disclosure"}
    return res, None


def _step(st: _WorkerState, msg: dict, modules: dict) -> dict:
    import faulthandler
    path = msg["module"]
    if path not in modules:
        modules[path] = load_module(Path(path))
    probe = next(p for p in modules[path].PROBES if p["name"] == msg["name"])
    entry, size, timeout = probe["entry"], msg["size"], msg["timeout"]
    out = {"status": "pass", "detail": "", "size": size}
    faulthandler.dump_traceback_later(max(0.2, timeout * 0.8), file=sys.stderr)
    t0 = time.perf_counter()
    inp = None
    try:
        try:
            inp = probe["make"](size, st.ctx)
        except BaseException as e:  # noqa: BLE001
            if type(e).__name__ == "Skip":
                return {"status": "skip", "detail": str(e), "size": size}
            return {"status": "error", "detail": f"make failed: {type(e).__name__}: {e}"[:200],
                    "size": size}
        items = list(inp) if type(inp).__name__ == "Seq" else [inp]
        results = []
        for item in items:
            res, problem = _exec_one(st, entry, item, probe.get("expect"), timeout)
            results.append(res)
            if problem:
                out.update(problem)
                break
        else:
            if probe.get("check"):
                try:
                    why = probe["check"](results, st.ctx)
                except BaseException as e:  # noqa: BLE001
                    why = f"check raised {type(e).__name__}: {e}"
                if why:
                    out.update(status="inconsistent", detail=str(why)[:200])
            if out["status"] == "pass":
                out["detail"] = " ".join(str(x) for x in results[-1][:2]) if results and results[-1] else "ok"
                if entry == "request" or entry == "raw":
                    out["detail"] = f"status {results[-1][1]}"
        if entry in ("request", "raw") and st.port is not None:
            if not _healthy(st):
                _stop_server(st)
                _start_server(st)  # restart only on a crash
                if out["status"] == "pass":
                    out.update(status="crash", exc="ServerDied",
                               detail="server stopped responding after this probe; restarted", frames=[])
    finally:
        faulthandler.cancel_dump_traceback_later()
    if out["status"] not in ("pass", "skip") and inp is not None:
        r = repr(inp)
        out["input"] = r if len(r) <= 200_000 else None
    out["elapsed"] = round(time.perf_counter() - t0, 4)
    return out


def worker_main(a) -> int:
    proto_in = os.fdopen(os.dup(0), "r", encoding="utf-8")
    proto_out = os.fdopen(os.dup(1), "w", encoding="utf-8")
    null = os.open(os.devnull, os.O_RDWR)
    os.dup2(null, 0)
    os.dup2(null, 1)
    sys.stdin = open(os.devnull, "r")
    sys.stdout = open(os.devnull, "w")
    import faulthandler
    faulthandler.enable(file=sys.stderr)

    def send(obj):
        proto_out.write(json.dumps(obj) + "\n")
        proto_out.flush()

    root = Path(a.root).resolve()
    tmp = Path(tempfile.mkdtemp(prefix="probe-"))
    st = _WorkerState()
    try:
        for p in (root / "src", root):
            if p.is_dir() and str(p) not in sys.path:
                sys.path.insert(1, str(p))
        adapter_path = Path(a.adapter).resolve()
        if str(adapter_path.parent) not in sys.path:
            sys.path.insert(1, str(adapter_path.parent))
        st.adapter = load_module(adapter_path)
        ad = st.adapter
        st.ctx = types.SimpleNamespace(
            adapter=ad, tmp=tmp, good_input=getattr(ad, "GOOD_INPUT", "1"),
            good_args=list(getattr(ad, "GOOD_ARGS", [])), good_stdin=getattr(ad, "GOOD_STDIN", ""),
            good_path=getattr(ad, "GOOD_PATH", "/"))
        entries = {"call": callable(getattr(ad, "call", None)),
                   "run": callable(getattr(ad, "run", None)),
                   "request": callable(getattr(ad, "request", None)),
                   "raw": callable(getattr(ad, "start_server", None))}
        send({"ready": True, "pid": os.getpid(), "tmp": str(tmp), "entries": entries})
    except BaseException as e:  # noqa: BLE001
        send({"ready": False, "error": f"{type(e).__name__}: {e}"})
        return 2
    modules: dict = {}
    for line in proto_in:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if msg.get("op") == "quit":
            break
        try:
            rep = _step(st, msg, modules)
        except BaseException as e:  # noqa: BLE001
            rep = {"status": "error", "detail": f"worker failure: {type(e).__name__}: {e}"[:200],
                   "size": msg.get("size")}
        rep["server"] = {"starts": st.server_starts, "port": st.port}
        send(rep)
    _stop_server(st)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


# ----------------------------------------------------------------------------- parent side
class Cfg:
    def __init__(self, root: Path, adapter: Path, probes_dir: Path | None, timeout: float):
        self.root, self.adapter, self.probes_dir, self.timeout = root, adapter, probes_dir, timeout
        self.stats_lock = threading.Lock()
        self.killed_pids: list[int] = []
        self.server_starts: dict[int, int] = {}
        self.server_ports: set[int] = set()
        self.workers_started = 0

    def in_repo(self, filename: str) -> bool:
        try:
            p = Path(filename).resolve()
        except (OSError, ValueError):
            return False
        if not p.is_relative_to(self.root) or p.is_relative_to(HERE) or p == self.adapter:
            return False
        if self.probes_dir and p.is_relative_to(self.probes_dir):
            return False
        return not ({"site-packages", ".venv", "venv", "node_modules", "__pycache__"} & set(p.parts))

    def rel(self, filename: str) -> str:
        try:
            return Path(filename).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return Path(filename).as_posix()


class Worker:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg
        self.dead = False
        self.errf = tempfile.NamedTemporaryFile(prefix="probe-worker-", suffix=".err", delete=False)
        cmd = [sys.executable, "-X", "utf8", str(HERE / "probe_run.py"), "--worker",
               "--root", str(cfg.root), "--adapter", str(cfg.adapter)]
        kw: dict = {}
        if IS_WIN:
            kw["creationflags"] = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                   SUPERLITE_PROBE_TIMEOUT=str(min(cfg.timeout, ENTRY_TIMEOUT["run"])))
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=self.errf, text=True, encoding="utf-8", bufsize=1,
                                  cwd=str(cfg.root), env=env, **kw)
        self.q: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        self.tmp = None
        self.real_pid = None
        self.entries: dict = {}
        with cfg.stats_lock:
            cfg.workers_started += 1
        try:
            ready = self.q.get(timeout=60)
        except queue.Empty:
            ready = None
        if not ready or not ready.get("ready"):
            err = (ready or {}).get("error") or self._stderr_tail()
            self.close(kill=True)
            raise RuntimeError(f"adapter failed to load: {err.strip()[-400:]}")
        self.real_pid, self.tmp, self.entries = ready["pid"], ready["tmp"], ready["entries"]

    def _read(self):
        try:
            for line in self.p.stdout:
                try:
                    self.q.put(json.loads(line))
                except ValueError:
                    pass
        except Exception:
            pass
        self.q.put(None)

    def _err_size(self) -> int:
        try:
            return os.path.getsize(self.errf.name)
        except OSError:
            return 0

    def _stderr_tail(self, off: int = 0) -> str:
        try:
            with open(self.errf.name, "rb") as f:
                f.seek(off)
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def _kill(self):
        pids = [x for x in (self.p.pid, self.real_pid) if x]
        kill_tree(self.p)
        with self.cfg.stats_lock:
            self.cfg.killed_pids.extend(pids)
        self.dead = True

    def step(self, meta: dict, size, timeout: float) -> dict:
        off = self._err_size()
        msg = {"op": "step", "module": meta["module"], "name": meta["name"], "size": size,
               "timeout": timeout}
        t0 = time.perf_counter()
        try:
            self.p.stdin.write(json.dumps(msg) + "\n")
            self.p.stdin.flush()
            rep = self.q.get(timeout=timeout)
        except queue.Empty:
            tail = self._stderr_tail(off)
            self._kill()
            return {"status": "hang", "detail": f"no response within {timeout:g}s",
                    "timeout": timeout, "size": size, "frames": frames_from_text(tail),
                    "elapsed": round(time.perf_counter() - t0, 3),
                    "killed_pids": [x for x in (self.p.pid, self.real_pid) if x]}
        except OSError:
            rep = None
        if rep is None:
            code = self.p.poll()
            tail = self._stderr_tail(off)
            self._kill()
            return {"status": "crash", "exc": "WorkerDied", "size": size,
                    "detail": f"worker process exited ({code}) {tail.strip()[-150:]}",
                    "frames": frames_from_text(tail), "elapsed": round(time.perf_counter() - t0, 3)}
        srv = rep.pop("server", None)
        if srv:
            with self.cfg.stats_lock:
                self.cfg.server_starts[self.p.pid] = srv["starts"]
                if srv["port"]:
                    self.cfg.server_ports.add(srv["port"])
        if rep["status"] in ("crash", "wrong-status", "leak") and not any(
                self.cfg.in_repo(f) for f, _ in rep.get("frames", [])):
            rep["frames"] = rep.get("frames", []) + frames_from_text(self._stderr_tail(off))
        return rep

    def close(self, kill: bool = False):
        if not kill:
            try:
                self.p.stdin.write(json.dumps({"op": "quit"}) + "\n")
                self.p.stdin.flush()
                self.p.wait(timeout=4)
            except Exception:
                kill = True
        if kill and self.p.poll() is None:
            self._kill()
        try:
            self.errf.close()
            os.unlink(self.errf.name)
        except OSError:
            pass
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)


class Pool:
    def __init__(self, cfg: Cfg, size: int):
        self.cfg, self.max = cfg, max(1, size)
        self.idle: queue.Queue = queue.Queue()
        self.all: list[Worker] = []
        self.lock = threading.Lock()

    def acquire(self) -> Worker:
        try:
            return self.idle.get_nowait()
        except queue.Empty:
            pass
        with self.lock:
            live = sum(1 for w in self.all if w is None or not w.dead)
            spawn = live < self.max
            if spawn:
                live_slot = len(self.all)
                self.all.append(None)  # reserve
        if spawn:
            try:
                w = Worker(self.cfg)
            except Exception:
                with self.lock:
                    self.all[live_slot] = types.SimpleNamespace(dead=True, close=lambda kill=False: None)
                raise
            with self.lock:
                self.all[live_slot] = w
            return w
        return self.idle.get()

    def release(self, w: Worker):
        if not w.dead:
            self.idle.put(w)

    def close(self):
        for w in self.all:
            if w is not None and not w.dead:
                w.close()
            elif w is not None and hasattr(w, "errf"):
                w.close(kill=True)


class Lease:
    def __init__(self, pool: Pool):
        self.pool, self.w = pool, None

    def step(self, meta, size, timeout):
        try:
            if self.w is None:
                self.w = self.pool.acquire()
        except RuntimeError as e:
            return {"status": "error", "detail": str(e)[:200], "size": size}
        out = self.w.step(meta, size, timeout)
        if self.w.dead:
            self.w.close(kill=True)
            self.w = None
        return out

    def close(self):
        if self.w is not None:
            self.pool.release(self.w)
            self.w = None


def timeout_for(meta: dict, cfg: Cfg) -> float:
    return min(ENTRY_TIMEOUT[meta["entry"]], cfg.timeout)


def run_probe(pool: Pool, cfg: Cfg, meta: dict) -> dict:
    lease = Lease(pool)
    res = {"id": meta["id"], "category": meta["category"], "entry": meta["entry"],
           "status": "pass", "size": None, "detail": "", "elapsed": 0.0}
    t0 = time.perf_counter()
    prev = None
    try:
        for size in meta["sizes"]:
            out = lease.step(meta, size, timeout_for(meta, cfg))
            if out["status"] != "pass":
                res.update(out)
                res["prev_pass_size"] = prev
                res["probe_meta"] = meta
                break
            prev = size
            res.update(status="pass", detail=out.get("detail", ""), size=size)
    finally:
        lease.close()
    res["elapsed"] = round(time.perf_counter() - t0, 3)
    return res


def group_key(res: dict, cfg: Cfg) -> tuple[str, tuple[str, int] | None]:
    st = res["status"]
    top = next(((f, n) for f, n in res.get("frames", []) if cfg.in_repo(f)), None)
    where = f"{cfg.rel(top[0])}:{top[1]}" if top else f"{res['category']}/{res['entry']}"
    if st == "crash":
        return f"crash|{res.get('exc')}|{where}", top
    if st == "hang":
        return f"hang|{where}", top
    if st == "leak":
        return f"leak|{res.get('leak')}|{where}", top
    if st == "wrong-status":
        return f"wrong-status|{res.get('http')}|{where}", top
    return f"{st}|{res['id']}", top


# ----------------------------------------------------------------------------- regression tests
REGRESSION_TEMPLATE = '''"""Generated by probe_run.py: {category} {kind} ({key}).
Minimal input shrunk from {orig_size}; probe {probe_id}. Fix the code, keep this test."""
import importlib.util
import json
import pathlib
import socket
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parents[2]
ADAPTER = ROOT / {adapter_rel!r}
ENTRY = {entry!r}
INPUT = {input_text}
EXPECT = {expect!r}
TIMEOUT = {timeout!r}
TRACE = "Traceback (most recent call last)"


def _load():
    for p in (ROOT / "src", ROOT, ADAPTER.parent):
        sys.path.insert(0, str(p))
    spec = importlib.util.spec_from_file_location("_probe_adapter", ADAPTER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _server(ad):
    r = ad.start_server()
    if isinstance(r, tuple):
        port, stop = r[0], (r[1] if len(r) > 1 else None)
    elif hasattr(r, "server_address"):
        port, stop = r.server_address[1], getattr(r, "shutdown", None)
    else:
        port, stop = int(r), None
    ad.PORT = port
    return port, stop


def _problem(ad):
    expected = tuple(getattr(ad, "EXPECTED_ERRORS", (ValueError,)))
    stop = None
    try:
        if ENTRY == "call":
            ad.call(INPUT)
        elif ENTRY == "run":
            rc, out, err = ad.run(*INPUT)
            if rc < 0 or rc >= 0xC0000000 or TRACE in str(err):
                return f"CLI crashed: exit {{rc}} {{str(err)[-200:]}}"
        else:
            port, stop = _server(ad)
            if ENTRY == "request":
                status = ad.request(*INPUT)[0]
            else:
                with socket.create_connection(("127.0.0.1", port), 5) as s:
                    s.sendall(INPUT)
                    s.shutdown(socket.SHUT_WR)
                    head = s.recv(64)
                status = int(head[9:12]) if head[:5] == b"HTTP/" else 0
            allowed = EXPECT.get("status") if EXPECT else None
            if allowed and status not in allowed:
                return f"status {{status}} not in {{allowed}}"
            if not allowed and 500 <= status < 600 and status not in (501, 505):
                return f"status {{status}}"
    except expected:
        return None
    finally:
        if stop:
            threading.Thread(target=stop, daemon=True).start()
    return None


def test_{test_name}():
    ad = _load()
    box = {{}}

    def go():
        try:
            box["p"] = _problem(ad)
        except BaseException as e:  # noqa: BLE001
            box["p"] = f"{{type(e).__name__}}: {{e}}"

    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(TIMEOUT)
    assert not t.is_alive(), f"hang: no result within {{TIMEOUT}}s"
    assert box["p"] is None, box["p"]
'''


_reg_lock = threading.Lock()


def write_regression(cfg: Cfg, group: dict, rep: dict, shrunk_size) -> str | None:
    with _reg_lock:
        return _write_regression(cfg, group, rep)


def _write_regression(cfg: Cfg, group: dict, rep: dict) -> str | None:
    meta = rep.get("probe_meta") or {}
    if not meta.get("regress", True) or meta.get("has_check") or not rep.get("input"):
        return None
    if rep["status"] == "leak" or rep["status"] == "inconsistent":
        return None
    expect = None
    try:
        mod = load_module(Path(meta["module"]))
        expect = next(p for p in mod.PROBES if p["name"] == meta["name"]).get("expect")
    except Exception:
        pass
    cat = group["category"]
    outdir = cfg.root / "tests" / "regression"
    existing = sorted(outdir.glob(f"test_probe_{cat}_*.py")) if outdir.is_dir() else []
    n = 1 + max([int(re.search(r"_(\d+)\.py$", p.name).group(1)) for p in existing] or [0])
    text = REGRESSION_TEMPLATE.format(
        category=cat, kind=group["kind"], key=group["key"].replace('"', "'"),
        orig_size=group.get("size"), probe_id=group["probe"], adapter_rel=cfg.rel(str(cfg.adapter)),
        entry=meta["entry"], input_text=rep["input"], expect=expect,
        timeout=timeout_for(meta, cfg), test_name=f"probe_{cat}_{n}")
    def body(t):
        return t[t.index("ROOT ="):t.index("def test_")]

    for p in existing:  # same content already written: reuse it
        if body(p.read_text(encoding="utf-8")) == body(text):
            return p.relative_to(cfg.root).as_posix()
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"test_probe_{cat}_{n}.py"
    path.write_text(text, encoding="utf-8")
    return path.relative_to(cfg.root).as_posix()


def shrink_group(pool: Pool, cfg: Cfg, group: dict, rep: dict) -> tuple[object, dict]:
    """Bisect the failing size down; returns (smallest failing size, its failing result)."""
    meta, best, key = rep["probe_meta"], rep, group["key"]
    hi = rep["size"]
    if hi is None or not isinstance(hi, int) or rep["status"] in ("error",):
        return hi, best
    lo = rep.get("prev_pass_size")
    lo = lo if isinstance(lo, int) else 0
    lease = Lease(pool)
    t0 = time.perf_counter()
    try:
        while hi - lo > 1 and time.perf_counter() - t0 < SHRINK_BUDGET:
            mid = (lo + hi) // 2
            out = lease.step(meta, mid, timeout_for(meta, cfg))
            out.setdefault("id", rep["id"])
            out.update(category=rep["category"], entry=rep["entry"], probe_meta=meta)
            if out["status"] != "pass" and out["status"] != "skip" and group_key(out, cfg)[0] == key:
                hi, best = mid, out
            else:
                lo = mid
    finally:
        lease.close()
    return hi, best


# ----------------------------------------------------------------------------- incidents
INCIDENT_SL = HERE.parent / "scripts" / "sl"
_append_lock = threading.Lock()


def _append_incident(log: Path, file: str, line: int, context: str, kind: str,
                     resolution: str | None) -> None:
    entry = {"file": file, "line": line, "context": context, "agent": "probe_run", "kind": kind}
    if resolution:
        entry["resolution"] = resolution
    entry["time"] = time.strftime("%H:%M:%S")
    log.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    with _append_lock:
        fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)


def _log_incident(log: Path, file: str, line: int, context: str, kind: str,
                  resolution: str | None = None) -> None:
    """Write one incident via `sl incident add` (D18); fall back to a direct append when sl is
    missing, has no Python (exit 3) or fails."""
    context = context if len(context) <= 200 else context[:199] + "…"
    if INCIDENT_SL.is_file() and shutil.which("bash"):
        cmd = ["bash", str(INCIDENT_SL), "incident", "add", "--file", file, "--line", str(line),
               "--context", context, "--agent", "probe_run", "--kind", kind, "--log", str(log)]
        if resolution:
            cmd += ["--resolution", resolution]
        try:
            if subprocess.run(cmd, capture_output=True, timeout=60).returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
    _append_incident(log, file, line, context, kind, resolution)


def read_log(log: Path) -> list[dict]:
    out = []
    if log.is_file():
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


# ----------------------------------------------------------------------------- files, cache
def norm_file(root: Path, f: str) -> str:
    f = f.strip().replace("\\", "/")
    p = Path(f)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(root).as_posix()
        except ValueError:
            return p.as_posix()
    return re.sub(r"^(\./)+", "", f)


def discover_files(root: Path, adapter: Path, probes_dir: Path | None) -> list[str]:
    base = root / "src" if (root / "src").is_dir() else root
    found = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if p.suffix in CODE_EXT and p.resolve() != adapter and not (
                    probes_dir and p.resolve().is_relative_to(probes_dir)):
                found.append(p.relative_to(root).as_posix())
    return found


def commit_files(root: Path, sha: str) -> list[str]:
    r = subprocess.run(["git", "-C", str(root), "diff-tree", "--no-commit-id", "--name-only", "-r",
                        "--root", "-z", "--relative", sha], capture_output=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"git diff-tree failed: {r.stderr.decode(errors='replace').strip()}")
    names = [n for n in r.stdout.decode("utf-8", "replace").split("\0") if n]
    keep = []
    for n in names:
        p = Path(n)
        if p.suffix in CODE_EXT and not (set(p.parts[:-1]) & SKIP_DIRS) and (root / n).exists():
            keep.append(p.as_posix())
    return keep


def sha_bytes(*parts: bytes) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(hashlib.sha256(p).digest())
    return h.hexdigest()


def load_cache(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d.get("entries"), dict) else {"version": 1, "entries": {}}
    except (OSError, ValueError, AttributeError):
        return {"version": 1, "entries": {}}


def save_cache(path: Path, new_entries: dict) -> None:
    cache = load_cache(path)  # re-read: another background run may have written meanwhile
    cache["entries"].update(new_entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    os.replace(tmp, path)


# ----------------------------------------------------------------------------- main run
def select_categories(a, catalog) -> list[str]:
    if a.categories:
        return [c.strip() for c in a.categories.split(",") if c.strip()]
    if a.app_type:
        t = APP_ALIASES.get(a.app_type.lower(), a.app_type.lower())
        if t not in APP_TYPES:
            raise SystemExit(f"probe_run: unknown --app-type {a.app_type!r}; "
                             f"use one of {', '.join(APP_TYPES)}")
        return list(APP_TYPES[t])
    extra = sorted({p["category"] for p in catalog} - set(CATEGORY_ORDER))
    return CATEGORY_ORDER + extra


def verified_index(entries: list[dict], root: Path) -> dict:
    idx: dict = {}
    for e in entries:
        if e.get("kind") != "verified":
            continue
        m = re.match(r"probe (\w+)", str(e.get("context", "")))
        if m:
            sm = re.search(r"\[sha:([0-9a-f]+)\]", e.get("context", ""))
            idx.setdefault((m.group(1), norm_file(root, str(e.get("file", "")))), []).append(
                (e.get("agent"), sm.group(1) if sm else None))
    return idx


def is_verified(idx: dict, cat: str, f: str, sha: str) -> bool:
    for agent, s in idx.get((cat, f), []):
        if agent != "probe_run" or (s and sha.startswith(s)):
            return True
    return False


def run_main(a) -> int:
    t_start = time.time()
    root = Path(a.root or os.getcwd()).resolve()
    adapter = Path(a.adapter).resolve() if a.adapter else root / ".superlite" / "probes" / "adapter.py"
    if not adapter.is_file():
        print(f"probe_run: adapter not found: {adapter}", file=sys.stderr)
        return 2
    probes_dir = Path(a.probes).resolve() if a.probes else None
    if probes_dir and not probes_dir.is_dir():
        print(f"probe_run: --probes is not a directory: {probes_dir}", file=sys.stderr)
        return 2

    def under_root(p: str) -> Path:
        return Path(p) if Path(p).is_absolute() else root / p

    out_path, log_path = under_root(a.out), under_root(a.log)
    cache_path = root / ".superlite" / "probes" / "cache.json"
    cfg = Cfg(root, adapter, probes_dir, a.timeout)

    if a.commit:
        try:
            files = commit_files(root, a.commit)
        except (RuntimeError, OSError) as e:
            print(f"probe_run: {e}", file=sys.stderr)
            return 2
    elif a.files:
        files = [norm_file(root, f) for f in a.files.split(",") if f.strip()]
    else:
        files = discover_files(root, adapter, probes_dir) or [cfg.rel(str(adapter))]

    catalog, load_errors = load_catalog(probes_dir)
    try:
        selected = select_categories(a, catalog)
    except SystemExit as e:
        print(e, file=sys.stderr)
        return 2

    pack_digest = sha_bytes(*[p.read_bytes() for p in probe_modules(probes_dir)])
    adapter_bytes = adapter.read_bytes()
    file_sha = {f: sha_bytes((root / f).read_bytes() if (root / f).is_file() else b"<missing>",
                             adapter_bytes, pack_digest.encode()) for f in files}
    log_entries = read_log(log_path)
    vidx = verified_index(log_entries, root)
    cache = load_cache(cache_path)["entries"]

    nworkers = a.workers or os.cpu_count() or 2
    pool = Pool(cfg, nworkers)
    results_run_seconds = 0.0
    results: dict = {"version": 1, "root": str(root), "adapter": cfg.rel(str(adapter)),
                     "files": files, "selected_categories": selected, "categories": {},
                     "probes": [], "failures": [], "load_errors": load_errors}
    try:
        try:
            w0 = pool.acquire()
        except RuntimeError as e:
            print(f"probe_run: {e}", file=sys.stderr)
            return 2
        entries = dict(w0.entries)
        pool.release(w0)

        pending: dict[str, list[str]] = {}
        for cat in selected:
            cprobes = [p for p in catalog if p["category"] == cat and entries.get(p["entry"])]
            if not cprobes:
                results["categories"][cat] = {"status": "n/a", "probes": 0,
                                              "reason": "no probe applies to this adapter's entries"}
                continue
            todo, skipped_v, cached = [], [], []
            for f in files:
                sha = file_sha[f]
                if f"{cat}|{f}|{sha}" in cache:
                    cached.append(f)
                elif is_verified(vidx, cat, f, sha):
                    skipped_v.append(f)
                else:
                    todo.append(f)
            if todo:
                pending[cat] = todo
            elif cached:
                results["categories"][cat] = {"status": "pass", "cached": True, "probes": 0,
                                              "files": cached, "skipped_verified": skipped_v}
            else:
                results["categories"][cat] = {"status": "skipped", "probes": 0, "files": skipped_v,
                                              "reason": "verified" if skipped_v else "no files"}

        tasks = [p for cat in pending for p in catalog
                 if p["category"] == cat and entries.get(p["entry"])]
        order = {p["id"]: i for i, p in enumerate(tasks)}
        done: list[dict] = []
        t_run = time.time()
        if tasks:
            with cf.ThreadPoolExecutor(max_workers=min(nworkers, len(tasks))) as ex:
                done = list(ex.map(lambda m: run_probe(pool, cfg, m), tasks))
        done.sort(key=lambda r: order[r["id"]])
        results_run_seconds = round(time.time() - t_run, 3)

        # group failures by root cause
        groups: dict[str, dict] = {}
        for r in done:
            if r["status"] in ("pass", "skip"):
                continue
            key, top = group_key(r, cfg)
            g = groups.setdefault(key, {"group_id": f"g{len(groups) + 1}", "key": key, "category": r["category"], "kind": r["status"],
                                        "exc": r.get("exc"), "count": 0, "probe": r["id"],
                                        "size": r.get("size"), "detail": r.get("detail", ""),
                                        "file": cfg.rel(top[0]) if top else None,
                                        "line": top[1] if top else 0, "probes": [], "_rep": r})
            g["count"] += 1
            g["probes"].append(r["id"])
            r["_group"] = groups[key]

        # shrink + regression tests, in parallel (one lease per group)
        def finish_group(g):
            rep = g.pop("_rep")
            if rep["status"] in ("crash", "hang", "wrong-status", "leak") and "probe_meta" in rep:
                size, best = shrink_group(pool, cfg, g, rep)
            else:
                size, best = rep.get("size"), rep
            g["shrunk_size"] = size
            try:
                g["regression_test"] = write_regression(cfg, g, best, size)
            except Exception as e:  # a failed test write must not lose the incident
                g["regression_test"] = None
                g["regression_error"] = f"{type(e).__name__}: {e}"
            return g

        glist = list(groups.values())
        if glist:
            with cf.ThreadPoolExecutor(max_workers=min(nworkers, len(glist))) as ex:
                glist = list(ex.map(finish_group, glist))
        results["failures"] = glist
    finally:
        pool.close()

    # per-category status, verified entries, cache
    failed_files: dict[str, set] = {}
    unattributed: set = set()
    for g in results["failures"]:
        (failed_files.setdefault(g["category"], set()).add(g["file"]) if g["file"]
         else unattributed.add(g["category"]))
    new_cache, verified_jobs = {}, []
    for cat, todo in pending.items():
        cres = [r for r in done if r["category"] == cat]
        bad = [r for r in cres if r["status"] not in ("pass", "skip")]
        entry_kinds = sorted({r["entry"] for r in cres})
        status = "fail" if bad else "pass"
        results["categories"][cat] = {"status": status, "cached": False, "probes": len(cres),
                                      "skipped_probes": sum(r["status"] == "skip" for r in cres),
                                      "failed_probes": len(bad), "files": todo, "entries": entry_kinds}
        has_error = any(r["status"] == "error" for r in cres)
        for f in todo:
            if has_error or cat in unattributed or f in failed_files.get(cat, set()):
                continue
            if any(r["status"] == "skip" for r in cres) and all(r["status"] == "skip" for r in cres):
                continue
            new_cache[f"{cat}|{f}|{file_sha[f]}"] = {"time": int(time.time()), "probes": len(cres)}
            maxsize = max([s for r in cres for s in [r.get("size")] if isinstance(s, int)] or [0])
            verified_jobs.append((
                f, f"probe {cat}: {len(cres)} probes pass ({'/'.join(entry_kinds)}), "
                   f"sizes up to {maxsize} [sha:{file_sha[f][:12]}]"))
    results["probes"] = []
    for r in done:
        g = r.get("_group")
        entry = {k: v for k, v in r.items()
                 if k not in ("probe_meta", "input", "frames", "prev_pass_size", "_group")}
        entry.update(file=g["file"] if g else None, line=g["line"] if g else None,
                     group_id=g["group_id"] if g else None, input_size=r.get("size"),
                     message=r.get("detail", ""))
        results["probes"].append(entry)

    # incidents: one per group (deduplicated against the log), one verified per category+file
    seen = {(e.get("file"), e.get("line"), e.get("context")) for e in log_entries}
    jobs = []
    for g in results["failures"]:
        what = g.get("exc") or g["kind"]
        ctx = (f"probe {g['category']} {g['kind']} {what}: {g['detail'][:70]} "
               f"(size {g['shrunk_size']}, {g['count']} probe(s), e.g. {g['probe']})")
        if g.get("regression_test"):
            ctx += f"; test {g['regression_test']}"
        ctx = ctx if len(ctx) <= 200 else ctx[:199] + "…"
        f = g["file"] or cfg.rel(str(adapter))
        g["incident"] = (f, g["line"], ctx)
        kind = {"crash": "exception", "leak": "exception", "hang": "perf"}.get(g["kind"], "test-failure")
        if (f, g["line"], ctx) not in seen:
            jobs.append((f, g["line"], ctx, kind, "open"))
    for f, ctx in verified_jobs:
        jobs.append((f, 0, ctx, "verified", None))
    if jobs:
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(lambda j: _log_incident(log_path, *j), jobs))
    for g in results["failures"]:
        g["incident"] = {"file": g["incident"][0], "line": g["incident"][1]}
    results["verified_logged"] = [{"file": f, "category": c.split(":")[0].split()[1]} for f, c in verified_jobs]
    if new_cache:
        save_cache(cache_path, new_cache)

    results["stats"] = {
        "elapsed": round(time.time() - t_start, 3), "run_seconds": results_run_seconds,
        "probes_run": len(done),
        "workers_started": cfg.workers_started, "server_starts": sum(cfg.server_starts.values()),
        "server_ports": sorted(cfg.server_ports), "killed_pids": cfg.killed_pids,
        "failure_groups": len(results["failures"]),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    nfail = len(results["failures"]) + sum(r["status"] == "error" for r in done)
    print(f"probe_run: {len(done)} probes, {len(results['failures'])} failure group(s), "
          f"{results['stats']['elapsed']}s -> {out_path}")
    return 1 if nfail else 0


def spawn_background(argv: list[str]) -> int:
    args = [x for x in argv if x != "--background"]
    kw: dict = {}
    if IS_WIN:
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000
    else:
        kw["start_new_session"] = True
    p = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *args],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, **kw)
    print(json.dumps({"started": p.pid}))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--adapter", help="adapter module (default <root>/.superlite/probes/adapter.py)")
    ap.add_argument("--root", help="project root (default: cwd)")
    ap.add_argument("--app-type", help=f"one of {', '.join(APP_TYPES)}")
    ap.add_argument("--probes", help="directory of project probe modules")
    ap.add_argument("--categories", help="comma list; overrides --app-type")
    ap.add_argument("--files", help="comma list of files under test, relative to --root")
    ap.add_argument("--commit", help="probe only the files this commit touched")
    ap.add_argument("--timeout", type=float, default=10.0, help="cap on per-probe timeouts (s)")
    ap.add_argument("--workers", type=int, default=0, help="default: CPU count")
    ap.add_argument("--out", default=".superlite/probes/probe-results.json",
                    help="results file, relative to --root")
    ap.add_argument("--log", default=".superlite/incidents.jsonl")
    ap.add_argument("--background", action="store_true", help="detach and return at once")
    ap.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.worker:
        return worker_main(a)
    if a.background:
        return spawn_background(argv)
    return run_main(a)


if __name__ == "__main__":
    sys.exit(main())
