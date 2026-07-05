#!/usr/bin/env python3
"""Shared git-worktree helper for the gate scripts.

Venvs and node_modules are **not** shared into linked git worktrees, so the
gate scripts (`venv_python.py`, `npm_run.py`) fall back to the *primary*
worktree's install. Locating that primary worktree is the one bit of logic they
share — it lives here so there is a single source of truth (issues #135, #137).
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def main_worktree_root(repo_root: Path) -> Path | None:
    """The primary worktree's root, or None if not a linked worktree / no git.

    Resolves via `git --git-common-dir`: for a linked worktree the common dir is
    `<main>/.git`, whose parent is the primary worktree root. Returns None for
    the primary worktree itself, a bare repo, or when git is unavailable.
    """
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
    root = common.parent if common.name == ".git" else None
    return root if root != repo_root else None
