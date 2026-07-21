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
"share this address" rather than BSD's "reuse a TIME_WAIT". So starting a
second server on a port another tree already holds **succeeds**: it logs
"Uvicorn running on ..." and "Application startup complete", owns nothing, and
the pre-existing server keeps answering. Every browser check then verifies the
wrong tree with no symptom at all. `/openapi.json` cannot tell them apart.

Three things close it, in order of who catches what:

- the default port is derived from *this checkout's path*, so two worktrees do
  not aim at the same port by construction (`resolve_port`);
- before starting, we bind the port ourselves with `SO_EXCLUSIVEADDRUSE`, which
  Windows does honour, and hard-fail if it is taken (`claim_port`);
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


def claim_port(port: int) -> bool:
    """Fail early if someone already holds the port, instead of shadow-binding it.

    `SO_EXCLUSIVEADDRUSE` is the Windows opt-out from the sharing behaviour that
    caused #364; elsewhere a plain bind already refuses an active listener. We
    release the socket before uvicorn starts, so a *simultaneous* start can still
    race — `verify_server` is what covers that. This check is for the common
    case: a server left running by another tree or an earlier session.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is not None:
        sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as exc:
        sys.stderr.write(
            f"\ndev_backend: port {port} is already in use ({exc.strerror or exc}).\n"
            "Another worktree's or an earlier session's server is holding it. "
            "uvicorn --reload would bind it anyway on Windows and serve nothing "
            "while that server kept answering (#364), so we stop here.\n"
            "Find the listener and kill the whole process tree (the --reload "
            "child outlives its parent):\n"
            f'  netstat -ano | Select-String ":{port}.*LISTENING"\n'
            f"Or pick another port:  PORT=<n> python scripts/dev_backend.py\n\n"
        )
        return False
    finally:
        sock.close()
    return True


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
            with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            # Something is answering and it does not know this route, so it is
            # not one of our wrappers — Anton's plain :8787 stack, say. Waiting
            # cannot improve that; fail now rather than after the full timeout.
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

    proc = subprocess.Popen(cmd, env=env_for_server(nonce))
    try:
        if not verify_server(port, nonce, proc):
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=10)
            return 1

        # Published only once the server is proven ours: `frontend/vite.config.js`
        # (`--mode claude`) reads this file to find the backend, so a file written
        # on faith would point the UI at another tree just as silently.
        PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        PORT_FILE.write_text(str(port), encoding="utf-8")
        print(f"backend on 127.0.0.1:{port} (published to {PORT_FILE})", flush=True)

        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=10)
        return 0
    finally:
        # A stale file would point the next frontend at a dead backend, which
        # looks like a broken app rather than a stopped server.
        with contextlib.suppress(OSError):
            PORT_FILE.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
