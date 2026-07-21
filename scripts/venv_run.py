#!/usr/bin/env python3
"""Run the backend venv's Python with the given arguments.

pre-commit (on Windows) can't resolve a relative `.venv/Scripts/python.exe`
entry, but it can run `python scripts/venv_run.py ...` (plain `python` is on
PATH), which then locates the venv by absolute path. This keeps a single
source of truth for project tools (ruff, pytest) — the same venv the
PostToolUse hook and manual `ruff`/`pytest` invocations use. Venv resolution
(incl. the git-worktree fallback) lives in `scripts/venv_python.py`.

Usage:
    python scripts/venv_run.py -m ruff check --force-exclude <files...>
    python scripts/venv_run.py -m pytest backend/tests -q
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from venv_python import find_venv_python  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
VENV_PYTHON = find_venv_python(REPO)

if VENV_PYTHON is None:
    sys.stderr.write(
        f"venv python not found under {REPO / 'backend' / '.venv'} "
        "(or the primary worktree's venv)\n"
        'Run: backend/.venv/Scripts/python.exe -m pip install -e "backend[dev]"\n'
    )
    raise SystemExit(1)

def _env_with_backend_first() -> dict[str, str]:
    """Env with this repo's `backend/` ahead of the editable install (#352).

    The venv installs the backend editable against the *primary* worktree, so
    `import app` resolves there no matter which worktree invoked us. pytest
    would then collect the invoking worktree's tests and fixtures while
    importing the primary worktree's `app` — spurious red when the primary tree
    carries WIP, and worse, silent green when it doesn't. Putting our own
    `backend/` on PYTHONPATH makes the code under test match the code being
    pushed. Harmless for ruff (it never imports `app`); set unconditionally so
    there is one code path.
    """
    env = dict(os.environ)
    backend = str(REPO / "backend")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{backend}{os.pathsep}{existing}" if existing else backend
    return env


raise SystemExit(subprocess.run([str(VENV_PYTHON), *sys.argv[1:]], env=_env_with_backend_first()).returncode)
