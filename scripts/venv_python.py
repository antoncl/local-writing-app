#!/usr/bin/env python3
"""Locate the backend venv's Python interpreter.

Single source of truth shared by `scripts/venv_run.py` (pre-commit gates) and
`.claude/hooks/check_edited_file.py` (in-session PostToolUse gate).

The subtlety this solves: venvs are **not** shared into git worktrees. A linked
worktree has its own checkout of these scripts but no `backend/.venv`, so a
naive `<repo>/backend/.venv/...` resolution fails there — silently skipping the
in-session ruff gate and hard-failing the pre-push pytest gate (issue #135).
So we prefer the caller's own repo root, then fall back to the *primary*
worktree's venv (found via `git --git-common-dir`). One venv, all worktrees.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worktree import main_worktree_root  # noqa: E402


def _candidates(root: Path):
    """Interpreter paths to try under a repo root: Windows layout, then POSIX."""
    base = root / "backend" / ".venv"
    yield base / "Scripts" / "python.exe"
    yield base / "bin" / "python"


def find_venv_python(repo_root: Path) -> Path | None:
    """Return the backend venv interpreter, or None if it can't be found.

    Prefers `repo_root`'s own venv; from a linked worktree (no local `.venv`)
    falls back to the primary worktree's venv.
    """
    roots = [repo_root]
    main = main_worktree_root(repo_root)
    if main:
        roots.append(main)
    for root in roots:
        for cand in _candidates(root):
            if cand.is_file():
                return cand
    return None
