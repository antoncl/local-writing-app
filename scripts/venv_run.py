#!/usr/bin/env python3
"""Run the backend venv's Python with the given arguments.

pre-commit (on Windows) can't resolve a relative `.venv/Scripts/python.exe`
entry, but it can run `python scripts/venv_run.py ...` (plain `python` is on
PATH), which then locates the venv by absolute path. This keeps a single
source of truth for project tools (ruff, pytest) — the same venv the
PostToolUse hook and manual `ruff`/`pytest` invocations use.

Usage:
    python scripts/venv_run.py -m ruff check --force-exclude <files...>
    python scripts/venv_run.py -m pytest backend/tests -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VENV_PYTHON = REPO / "backend" / ".venv" / "Scripts" / "python.exe"  # POSIX: bin/python

if not VENV_PYTHON.is_file():
    sys.stderr.write(
        f"venv python not found at {VENV_PYTHON}\n"
        'Run: backend/.venv/Scripts/python.exe -m pip install -e "backend[dev]"\n'
    )
    raise SystemExit(1)

raise SystemExit(subprocess.run([str(VENV_PYTHON), *sys.argv[1:]]).returncode)
