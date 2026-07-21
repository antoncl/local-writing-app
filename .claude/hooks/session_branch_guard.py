#!/usr/bin/env python3
"""Claude Code SessionStart hook — branch-drift tripwire.

Every new session/thread inherits whatever branch the *shared* working tree is
on. There is only one worktree, so a `git checkout` in any other session or
spawned background task moves HEAD out from under the next session — and the
harness's own branch display can lag (it once showed `feat/...` while the tree
was actually on `design/...`). Git has no pre-checkout hook to *block* that, so
this surfaces the LIVE branch at session start and shouts if it changed since
this project's last Claude session.

SessionStart semantics: text on stdout is injected into the model's context, so
the first thing a new thread sees is the real branch + a warning if it drifted.
Detection, not prevention — verify before working; another session may have
switched it.

Always exits 0; a broken hook must never wedge a session start.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys

# The reflog subject echoed in a drift warning can carry non-ASCII (em dashes in
# commit messages, etc.). On a Windows cp1252 console that raises
# UnicodeEncodeError mid-print and swallows the warning — force UTF-8 so it
# always survives.
with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def git(*args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=8
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip()


def main() -> int:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if not branch:  # not a git repo / git unavailable — say nothing
        return 0
    head = git("rev-parse", "--short", "HEAD") or "?"

    # Per-repo record of the branch this project's last Claude session saw. Lives
    # inside the git dir, so it is never tracked and is worktree-local.
    git_dir = git("rev-parse", "--git-dir")
    record = None
    previous = None
    if git_dir:
        from pathlib import Path

        record = Path(git_dir) / "claude-session-branch"
        try:
            previous = record.read_text(encoding="utf-8").strip() or None
        except Exception:
            previous = None

    # ASCII only: this runs on a Windows cp1252 console where emoji/arrows raise
    # UnicodeEncodeError (matches the plain-text house style of the other hook).
    lines: list[str] = [f"On git branch `{branch}` ({head})."]

    if previous and previous != branch:
        last_move = git("reflog", "-1", "--format=%gs") or ""
        lines = [
            f"WARNING: git branch CHANGED since this project's last Claude "
            f"session: `{previous}` -> `{branch}` ({head}).",
            "Another session or background task may have run `git checkout` in "
            "the shared working tree. VERIFY this is the branch you intend to "
            "work on before editing or committing -- do not trust a stale "
            "branch display.",
        ]
        if last_move:
            lines.append(f"Most recent HEAD move: {last_move}")

    if record is not None:
        with contextlib.suppress(Exception):
            record.write_text(branch + "\n", encoding="utf-8")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        # A broken tripwire must never wedge a session start.
        raise SystemExit(0) from None
