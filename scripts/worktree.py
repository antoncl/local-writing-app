#!/usr/bin/env python3
"""Shared git-worktree helper for the gate scripts.

A venv is **not** shared into a linked git worktree, so `venv_python.py` falls
back to the *primary* worktree's interpreter rather than demanding a venv per
worktree (#135). Locating that primary worktree lives here so there is a single
source of truth.

Note the asymmetry with the frontend: `npm_run.py` deliberately does **not**
reach for the primary worktree's install any more — it installs locally instead
(#350/#352). Borrowing an *interpreter* is safe; borrowing *code* is what broke
both gates.
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
