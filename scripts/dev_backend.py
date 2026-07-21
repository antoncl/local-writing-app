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

Anton's own stack is deliberately NOT this: `backend` stays pinned to :8787 and
`frontend` to :5173, strict, so a stale server there is an error rather than a
silent port swap.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from venv_python import find_venv_python  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
PORT_FILE = REPO / "tmp" / "dev-backend-port"
DEFAULT_PORT = 8788


def resolve_port() -> int:
    """The port Claude Code assigned, or the historical default when run by hand."""
    raw = os.environ.get("PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        return int(raw)
    except ValueError:
        print(f"PORT={raw!r} is not a number; falling back to {DEFAULT_PORT}")
        return DEFAULT_PORT


def env_with_backend_first() -> dict[str, str]:
    """This worktree's `backend/` ahead of the venv's editable install (#352)."""
    env = dict(os.environ)
    backend = str(REPO / "backend")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{backend}{os.pathsep}{existing}" if existing else backend
    return env


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
    backend = str(REPO / "backend")
    PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    PORT_FILE.write_text(str(port), encoding="utf-8")
    print(f"backend on 127.0.0.1:{port} (published to {PORT_FILE})")

    cmd = [
        str(python), "-m", "uvicorn", "app.main:app",
        "--app-dir", backend,
        "--host", "127.0.0.1",
        "--port", str(port),
        "--reload", "--reload-dir", backend,
    ]
    try:
        return subprocess.run(cmd, env=env_with_backend_first()).returncode
    finally:
        # A stale file would point the next frontend at a dead backend, which
        # looks like a broken app rather than a stopped server.
        with contextlib.suppress(OSError):
            PORT_FILE.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
