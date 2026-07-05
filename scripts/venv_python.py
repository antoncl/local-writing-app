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

import subprocess
from pathlib import Path


def _candidates(root: Path):
    """Interpreter paths to try under a repo root: Windows layout, then POSIX."""
    base = root / "backend" / ".venv"
    yield base / "Scripts" / "python.exe"
    yield base / "bin" / "python"


def _main_worktree_root(repo_root: Path) -> Path | None:
    """The primary worktree's root, or None if not a linked worktree / no git."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    common = Path(out.stdout.strip())
    if not common.is_absolute():
        common = (repo_root / common).resolve()
    # <main>/.git → parent is the main worktree root; other git-dir shapes: skip.
    return common.parent if common.name == ".git" else None


def find_venv_python(repo_root: Path) -> Path | None:
    """Return the backend venv interpreter, or None if it can't be found.

    Prefers `repo_root`'s own venv; from a linked worktree (no local `.venv`)
    falls back to the primary worktree's venv.
    """
    roots = [repo_root]
    main = _main_worktree_root(repo_root)
    if main and main != repo_root:
        roots.append(main)
    for root in roots:
        for cand in _candidates(root):
            if cand.is_file():
                return cand
    return None
