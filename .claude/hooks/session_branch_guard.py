#!/usr/bin/env python3
"""Claude Code SessionStart hook — worktree + branch guard.

Policy (CLAUDE.md, "Starting new work"): the primary working tree belongs to
Anton. Every Claude session works in its own linked worktree, branched from
`origin/master`. That turns three former discipline rules into structure:

- Anton's uncommitted WIP cannot be swept into a commit, stashed by pre-commit,
  or reverted by its repo-wide `git checkout -- .` — it is in another directory.
- HEAD cannot drift out from under a session, because no other session shares
  this tree's HEAD.
- Work cannot accidentally land on `master`, which the `master gates` ruleset
  rejects at push time anyway.

This hook cannot *block* a session — SessionStart has no veto. What it can do is
put the truth in front of the model before it edits anything: which tree it is
in, which branch, and whether that is allowed. Enforcement proper lives in
`CLAUDE.md` (which arms the EnterWorktree tool) and in `.claude/settings.json`
(`worktree.baseRef`, pinning the base to origin/master).

Always exits 0; a broken guard must never wedge a session start.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
from pathlib import Path

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


def in_linked_worktree() -> bool | None:
    """True in a linked worktree, False in the primary tree, None if unknown.

    A linked worktree has its own `.git` file pointing at a per-worktree admin
    directory, so `--git-dir` and `--git-common-dir` diverge; in the primary
    tree they name the same place.
    """
    common = git("rev-parse", "--git-common-dir")
    own = git("rev-parse", "--git-dir")
    if not common or not own:
        return None
    try:
        return Path(common).resolve() != Path(own).resolve()
    except Exception:
        return None


def drift_warning(branch: str, head: str) -> list[str]:
    """Warn if the branch moved since this tree's last Claude session.

    Still worth keeping under the worktree policy: a session can `checkout`
    inside its own worktree, and the harness's branch display has lagged before.
    The record lives in the git dir, which is per-worktree, so each worktree
    tracks its own branch independently.
    """
    git_dir = git("rev-parse", "--git-dir")
    if not git_dir:
        return []
    record = Path(git_dir) / "claude-session-branch"
    previous = None
    try:
        previous = record.read_text(encoding="utf-8").strip() or None
    except Exception:
        previous = None

    with contextlib.suppress(Exception):
        record.write_text(branch + "\n", encoding="utf-8")

    if not previous or previous == branch:
        return []
    lines = [
        f"WARNING: git branch CHANGED since this tree's last Claude session: "
        f"`{previous}` -> `{branch}` ({head}). VERIFY this is the branch you "
        f"intend before editing or committing.",
    ]
    last_move = git("reflog", "-1", "--format=%gs") or ""
    if last_move:
        lines.append(f"Most recent HEAD move: {last_move}")
    return lines


def tree_lines(linked: bool | None, branch: str, head: str) -> list[str]:
    """The headline: which tree this session is in, and whether that is allowed."""
    if linked is False:
        return [
            "STOP: this session is in the PRIMARY working tree, which belongs "
            "to Anton and routinely holds his uncommitted WIP.",
            "Do NOT edit, stage, commit, or checkout here. Start the work with "
            'the EnterWorktree tool, which branches a fresh worktree from '
            'origin/master (CLAUDE.md, "Starting new work").',
            "Reading, searching, and answering questions in place is fine.",
        ]
    if linked is None:
        return [
            f"On git branch `{branch}` ({head}); could not tell whether this "
            f"is a linked worktree -- verify before editing."
        ]
    return [f"In a linked worktree on git branch `{branch}` ({head})."]


def main() -> int:
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if not branch:  # not a git repo / git unavailable — say nothing
        return 0
    head = git("rev-parse", "--short", "HEAD") or "?"

    # ASCII only: this runs on a Windows cp1252 console where emoji/arrows raise
    # UnicodeEncodeError (matches the plain-text house style of the other hook).
    lines = tree_lines(in_linked_worktree(), branch, head)

    if branch == "master":
        lines.append(
            "WARNING: HEAD is on `master`. The `master gates` ruleset rejects "
            "direct pushes, so commit to a topic branch instead."
        )

    lines += drift_warning(branch, head)

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        # A broken guard must never wedge a session start.
        raise SystemExit(0) from None
