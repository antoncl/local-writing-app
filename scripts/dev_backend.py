#!/usr/bin/env python3
"""Start the isolated ("claude") backend on the port Claude Code assigned.

Why this exists instead of a plain `uvicorn --port 8788` in launch.json:
under the worktree-first policy (CLAUDE.md, "Starting new work") several
sessions run at once, and a port baked into a *tracked* config is identical in
every worktree — so the second session to start collides with the first. The
port is not knowable when the config is written, so it must not be written.

`.claude/launch.json` marks this config `autoPort: true`, which makes Claude
Code pick a free port, point the Browser pane at it, and hand it to us as the
`PORT` environment variable. This wrapper binds that port and publishes it to
`tmp/dev-backend-port` so the frontend of the *same worktree* can find it
(see `frontend/vite.config.js`, `--mode claude`). `tmp/` is gitignored and
per-worktree, so each tree publishes its own and none of them collide.

It also runs the backend the way the gates do: the venv is located by absolute
path (a worktree has no `backend/.venv` of its own) and this checkout's
`backend/` goes on `PYTHONPATH`, so the dev server runs *this* worktree's code
rather than the primary tree's editable install (#352).

**#364 — none of the above was enough, and the reason is not the import path.**
A worktree's dev server served the primary tree's code silently. The import was
correct throughout; the *server* was not ours. On Windows `uvicorn --reload`
binds its socket with `SO_REUSEADDR` (`uvicorn/config.py::bind_socket`, taken
only on the reload/multiprocess path), and Windows reads `SO_REUSEADDR` as
"share this address" rather than BSD's "reuse a TIME_WAIT". When **both** sides
set it — and every `--reload` server does, which is every dev server we run —
the second bind **succeeds**: it logs "Uvicorn running on ..." and "Application
startup complete", receives nothing, and the pre-existing server keeps
answering. Measured: 100% of connections go to the first binder, deterministic
over 90 connections; a plain (non-reload) incumbent instead rejects the second
server with WSAEACCES, which is why this only ever bit dev. Every browser check
then verifies the wrong tree with no symptom at all. `/openapi.json` cannot tell
them apart.

The shadow server is not inert, either: it is an understudy. Close the
incumbent and it starts serving immediately (measured), so a hijack that begins
as "my changes do nothing" can turn into "my changes appeared after I restarted
something unrelated" — which is the shape of a bug nobody trusts a bisect on.

Three things close it, in order of who catches what:

- the default port is derived from *this checkout's path*, so two worktrees do
  not aim at the same port by construction (`resolve_port`);
- before starting, we bind the port ourselves *without* `SO_REUSEADDR` and
  hard-fail if it is taken (`claim_port`);
- after starting, we ask the server on that port to identify itself and refuse
  to publish the port file unless it answers with this launch's nonce
  (`verify_server`, served by `scripts/dev_backend_app.py`).

The last one is the guarantee; the first two just turn a silent collision into
an immediate, readable failure. A preview that quietly shows another tree's
code is worse than no preview — it produces confident, wrong verification.

Anton's own stack is deliberately NOT this: `backend` stays pinned to :8787 and
`frontend` to :5173, strict, so a stale server there is an error rather than a
silent port swap.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from venv_python import find_venv_python  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PORT_FILE = REPO / "tmp" / "dev-backend-port"

# Deliberately clear of Anton's pinned :8787 and of the historical shared
# :8788, which every worktree used to pick and which is what made the #364
# collision reachable in the first place.
PORT_BASE = 8800
PORT_SPAN = 100

PROBE_PATH = "/__dev_backend_provenance"
STARTUP_TIMEOUT = 60.0


def default_port() -> int:
    """A stable port for *this* checkout, so sibling worktrees don't collide.

    Derived from the checkout path rather than assigned randomly: restarting the
    same tree reuses the same port, which keeps `tmp/dev-backend-port` and any
    already-open browser tab valid. A hash collision between two checkouts is
    possible and harmless — `claim_port` turns it into a loud failure, which is
    the property that actually matters.
    """
    digest = zlib.crc32(str(REPO).encode("utf-8"))
    return PORT_BASE + digest % PORT_SPAN


def resolve_port() -> int:
    """The port Claude Code assigned, or this checkout's own default."""
    raw = os.environ.get("PORT", "").strip()
    if not raw:
        return default_port()
    try:
        return int(raw)
    except ValueError:
        fallback = default_port()
        print(f"PORT={raw!r} is not a number; falling back to {fallback}")
        return fallback


# Built without a ProxyHandler: `urlopen`'s default opener honours HTTP_PROXY,
# and a VPN client that sets it turns every probe of 127.0.0.1 into a 407/502
# from the proxy. That lands in the HTTPError branch and accuses a perfectly
# healthy server of being someone else's.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe_provenance(port: int, timeout: float = 2.0) -> dict | None:
    """Ask whatever holds `port` to identify itself, or None if it will not.

    Works against any server started by this launcher, in any worktree — which
    is the only reliable way to name the holder. See `claim_port` for why the
    OS-level answer cannot be trusted.
    """
    url = f"http://127.0.0.1:{port}{PROBE_PATH}"
    try:
        with _OPENER.open(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill the launcher's whole descendant tree, not just the process it spawned.

    `proc` is uvicorn's *reloader*, which spawns the real server as a
    `multiprocessing` child with a duplicated handle to the listening socket.
    Terminating the reloader alone leaves that child running and still holding
    the port — verified — which produces the worst state this script has: a
    healthy backend nobody can find, on a port `claim_port` now refuses.

    Windows has no process groups to signal, so use `taskkill /T`; elsewhere put
    the child in its own session and signal the group.
    """
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    else:
        import signal

        with contextlib.suppress(OSError):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=10)


def claim_port(port: int) -> bool:
    """Fail early if someone already holds the port, instead of shadow-binding it.

    What matters here is that we do **not** set `SO_REUSEADDR`. Windows only
    lets a second socket share an in-use address when *both* sides asked for
    `SO_REUSEADDR`, and uvicorn's reload path always does — so a plain bind
    already detects the incumbent, and `SO_EXCLUSIVEADDRUSE` below is
    belt-and-braces rather than the mechanism (measured; a plain bind and an
    exclusive bind both refuse a `SO_REUSEADDR` listener with WSAEADDRINUSE).

    We release the socket before uvicorn starts, so a *simultaneous* start can
    still race — `verify_server` is what covers that. This check is for the
    common case: a server left running by another tree or an earlier session.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is not None:
        sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as exc:
        _report_occupied_port(port, exc)
        return False
    finally:
        sock.close()
    return True


def _report_occupied_port(port: int, exc: OSError) -> None:
    """Name the process actually holding the port, because the OS will not.

    `netstat -ano` and `Get-NetTCPConnection` both report the uvicorn *reloader*
    pid, which is usually already dead: the socket is held by its
    `multiprocessing.spawn` child, whose command line is
    `python -c "from multiprocessing.spawn import spawn_main; ..."` — no port,
    no app name, nothing greppable. Killing the pid the OS names "succeeds" and
    changes nothing, which is precisely how #364's "I killed every listener on
    the port" step produced a false negative and sent the diagnosis after the
    import system for a day.

    So ask the server instead. Every server this launcher starts answers the
    provenance probe with its own real pid.
    """
    lines = [
        f"\ndev_backend: port {port} is already in use ({exc.strerror or exc}).",
        "uvicorn --reload would bind it anyway on Windows and serve nothing while "
        "that server kept answering (#364), so we stop here.",
    ]

    holder = probe_provenance(port)
    if holder:
        lines += [
            f"Held by: {holder.get('checkout')}",
            f"Kill THIS pid (not the one netstat reports): {holder.get('pid')}",
        ]
    else:
        lines += [
            "The holder does not answer the provenance probe, so it is not one of "
            "ours - Anton's pinned :8787 stack, or a stale orphan.",
            "Do NOT trust the pid from netstat/Get-NetTCPConnection; it names the "
            "dead reloader parent. Find the live child instead:",
            "  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "
            "'*multiprocessing*' } | Select ProcessId,ParentProcessId",
        ]

    lines.append("Or pick another port:  PORT=<n> python scripts/dev_backend.py\n\n")
    sys.stderr.write("\n".join(lines))


def env_for_server(nonce: str) -> dict[str, str]:
    """This worktree's `backend/` ahead of the venv's editable install (#352).

    `scripts/` joins it too, because the app uvicorn is pointed at is the
    provenance wrapper in `scripts/dev_backend_app.py`, which then imports the
    real `app.main:app`. Both entries must survive into uvicorn's `--reload`
    child; they do — the reloader spawns it with this environment.
    """
    env = dict(os.environ)
    parts = [str(REPO / "backend"), str(REPO / "scripts")]
    existing = env.get("PYTHONPATH")
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["DEV_BACKEND_CHECKOUT"] = str(REPO)
    env["DEV_BACKEND_NONCE"] = nonce
    # Handed over rather than duplicated: were the wrapper to serve a different
    # path than we probe, our own healthy server would 404 and `verify_server`
    # would report it as someone else's — a confident, false accusation.
    env["DEV_BACKEND_PROBE_PATH"] = PROBE_PATH
    return env


def _report_foreign_server(port: int, detail: str) -> None:
    """The #364 message: our server started fine, someone else owns the port."""
    sys.stderr.write(
        f"\ndev_backend: PORT {port} IS SERVED BY A DIFFERENT SERVER.\n"
        f"{detail}.\n"
        f"This checkout: {REPO}\n"
        "That is #364: on Windows uvicorn --reload can bind a port another "
        "server already holds, start cleanly, and never receive a request. "
        # Plain ASCII on purpose: this goes to a cp1252 console on Windows.
        "Refusing to publish the port file - a preview of the wrong tree is "
        "worse than none.\n\n"
    )


def verify_server(port: int, nonce: str, proc: subprocess.Popen) -> bool:
    """Confirm the server answering `port` is the one we just started.

    This is the check that would have caught #364. It cannot be done from inside
    the server — a hijacked launch's own process is healthy and simply never
    receives the request — so it has to be an HTTP round trip that carries a
    secret only this launch knows.
    """
    url = f"http://127.0.0.1:{port}{PROBE_PATH}"
    deadline = time.monotonic() + STARTUP_TIMEOUT
    last_error: str | None = None

    while time.monotonic() < deadline:
        if proc.poll() is not None:
            sys.stderr.write(
                f"\ndev_backend: server exited with code {proc.returncode} "
                "before it answered.\n\n"
            )
            return False
        try:
            with _OPENER.open(url, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            # Something is answering and it does not know this route, so it is
            # not one of our wrappers — Anton's plain :8787 stack, say. Waiting
            # cannot improve that; fail now rather than after the full timeout.
            # (`DEV_BACKEND_PROBE_PATH` is passed to the wrapper from the single
            # constant below, so our own server can never land here by drifting.)
            _report_foreign_server(port, f"HTTP {exc.code} from {PROBE_PATH}")
            return False
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last_error = repr(exc)
            time.sleep(0.3)
    else:
        sys.stderr.write(
            f"\ndev_backend: {url} never answered within {STARTUP_TIMEOUT:.0f}s "
            f"(last error: {last_error}).\n\n"
        )
        return False

    if payload.get("nonce") != nonce:
        _report_foreign_server(
            port,
            f"it reports checkout {payload.get('checkout')!r} "
            f"(pid {payload.get('pid')}), not this one",
        )
        return False

    print(
        f"dev_backend: verified {payload['app_file']} is serving 127.0.0.1:{port}",
        flush=True,
    )
    return True


def main() -> int:
    python = find_venv_python(REPO)
    if python is None:
        sys.stderr.write(
            f"venv python not found under {REPO / 'backend' / '.venv'} "
            "(or the primary worktree's venv)\n"
            'Run: backend/.venv/Scripts/python.exe -m pip install -e "backend[dev]"\n'
        )
        return 1

    port = resolve_port()
    if not claim_port(port):
        return 1

    backend = str(REPO / "backend")
    nonce = secrets.token_hex(16)
    cmd = [
        str(python), "-m", "uvicorn", "dev_backend_app:app",
        "--app-dir", backend,
        "--host", "127.0.0.1",
        "--port", str(port),
        "--reload", "--reload-dir", backend,
    ]

    # POSIX: own session so `kill_tree` can signal the whole group. Windows has
    # no equivalent at spawn time; `taskkill /T` walks the tree instead.
    popen_kwargs = {} if sys.platform == "win32" else {"start_new_session": True}
    proc = subprocess.Popen(cmd, env=env_for_server(nonce), **popen_kwargs)
    published = False
    try:
        if not verify_server(port, nonce, proc):
            kill_tree(proc)
            return 1

        # Published only once the server is proven ours: `frontend/vite.config.js`
        # (`--mode claude`) reads this file to find the backend, so a file written
        # on faith would point the UI at another tree just as silently.
        PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        PORT_FILE.write_text(str(port), encoding="utf-8")
        published = True
        print(f"backend on 127.0.0.1:{port} (published to {PORT_FILE})", flush=True)

        return proc.wait()
    except KeyboardInterrupt:
        kill_tree(proc)
        return 0
    finally:
        # A stale file would point the next frontend at a dead backend, which
        # looks like a broken app rather than a stopped server. Only ever remove
        # *our* entry: a second launcher in this worktree (a different PORT)
        # shares this path, and deleting on the way out of a failed start would
        # strand the working server that wrote it.
        if published:
            with contextlib.suppress(OSError):
                if PORT_FILE.read_text(encoding="utf-8").strip() == str(port):
                    PORT_FILE.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
