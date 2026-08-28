#!/usr/bin/env python3
"""Reliably (re)start Anton's pinned backend on :8787 — no reboot required.

Why this exists (#364 follow-up). The primary backend is pinned to :8787 and is
meant to be *strict*: a stale server should be a loud error, not a silent swap.
But it was launched with `uvicorn --reload`, which on Windows breaks that in two
compounding ways:

- `--reload` runs a reloader parent + a `multiprocessing` **worker child**.
  Stopping it (Ctrl+C, a "restart", the IDE's stop button) kills the reloader but
  orphans the child — Windows has no process group to signal, so nothing walks
  the tree. The orphan keeps :8787 and keeps serving the code it loaded at
  startup.
- `--reload` binds with `SO_REUSEADDR`, which Windows reads as "share this
  address". So the *next* start **shadow-binds** :8787, logs "startup complete",
  and receives nothing — the orphan answers 100% of requests. `git pull` then
  appears to do nothing until a reboot reaps the orphan. (Full autopsy:
  `scripts/dev_backend.py` docstring; `docs/development/worktrees.md`.)

This launcher makes `git pull && restart` dependable:

1. Kill whatever holds :8787 — the listening socket's owner *tree* (`taskkill /F
   /T`, which reaches an orphaned worker child), plus any lingering uvicorn
   process for this checkout. The orphan holds the socket, so it is the owner and
   gets reaped here.
2. Wait until :8787 is actually free (a plain, non-`SO_REUSEADDR` bind — so we
   fail loud if something we could not kill still holds it, instead of
   shadow-binding on top of it).
3. `exec` into a **plain** uvicorn (no `--reload`) — a single process. Because
   `exec` *replaces* this launcher, the tracked PID (whoever ran us — the IDE, a
   shell) IS the uvicorn process, so a later stop kills it cleanly with nothing
   left to orphan. No `--reload` means no worker child to orphan in the first
   place, and to pick up new code you restart (which is now fast and reliable).

Usage:  python scripts/restart_backend.py   (honours PORT=<n>, default 8787)
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from venv_python import find_venv_python  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 8787


def resolve_port() -> int:
    raw = os.environ.get("PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        return int(raw)
    except ValueError:
        print(f"PORT={raw!r} is not a number; using {DEFAULT_PORT}", flush=True)
        return DEFAULT_PORT


def _run_ps(script: str) -> str:
    """Run a PowerShell snippet and return stdout (empty on any failure)."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout or ""


def _port_owner_pids_windows(port: int) -> list[int]:
    out = _run_ps(
        f"Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction "
        "SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique"
    )
    pids: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def _uvicorn_pids_windows(port: int) -> list[int]:
    """Belt-and-braces: uvicorn processes for this checkout, in case the socket
    owner lookup names a dead reloader rather than the live worker."""
    out = _run_ps(
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' "
        f"-and $_.CommandLine -like '*uvicorn*' -and $_.CommandLine -like '*{port}*' "
        "} | Select-Object -ExpandProperty ProcessId"
    )
    return [int(x) for x in out.split() if x.strip().isdigit()]


def _kill_tree_windows(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False
    )


def _kill_holders_posix(port: int) -> None:
    # Best-effort on POSIX (Anton's stack is Windows). fuser sends the signal to
    # every process holding the port; the group-kill semantics differ from
    # Windows so we just SIGKILL the holders.
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True, check=False)


def kill_port_holders(port: int) -> None:
    if sys.platform == "win32":
        pids = set(_port_owner_pids_windows(port)) | set(_uvicorn_pids_windows(port))
        if not pids:
            print(f"restart_backend: nothing holding :{port}", flush=True)
            return
        for pid in pids:
            print(f"restart_backend: killing :{port} holder tree pid {pid}", flush=True)
            _kill_tree_windows(pid)
    else:
        _kill_holders_posix(port)


def port_free(port: int) -> bool:
    """True when we can take the port with a plain, exclusive bind (no
    SO_REUSEADDR) — i.e. nothing is actually serving it. This is the check that
    would have distinguished a real free port from a shadow-bindable one."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
    if exclusive is not None:
        sock.setsockopt(socket.SOL_SOCKET, exclusive, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError:
        return False
    finally:
        sock.close()
    return True


def wait_for_free(port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_free(port):
            return True
        time.sleep(0.3)
    return port_free(port)


def main() -> int:
    python = find_venv_python(REPO)
    if python is None:
        sys.stderr.write(
            f"venv python not found under {REPO / 'backend' / '.venv'}.\n"
            "Set it up:  cd backend; python -m venv .venv; "
            ".venv\\Scripts\\python -m pip install -r requirements.lock; "
            ".venv\\Scripts\\python -m pip install -e . --no-deps\n"
        )
        return 1

    port = resolve_port()
    kill_port_holders(port)
    if not wait_for_free(port):
        sys.stderr.write(
            f"\nrestart_backend: :{port} is still held after kill — something we "
            "could not reap is serving it. Refusing to shadow-bind on top of it "
            "(that is the #364 trap). Find and stop it, or reboot.\n\n"
        )
        return 1

    # Plain uvicorn: NO --reload. Single process, so a later stop kills it clean
    # and there is no worker child to orphan. `exec` replaces this launcher, so
    # the tracked pid becomes uvicorn itself.
    cmd = [
        str(python), "-m", "uvicorn", "app.main:app",
        "--app-dir", str(REPO / "backend"),
        "--host", "127.0.0.1",
        "--port", str(port),
    ]
    print(f"restart_backend: starting plain uvicorn on 127.0.0.1:{port}", flush=True)
    os.execv(str(python), cmd)
    return 0  # unreachable — execv replaces the process


if __name__ == "__main__":
    raise SystemExit(main())
