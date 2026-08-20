#!/usr/bin/env python3
"""Stale-worktree cleanup, junction-safe (#359).

The worktree-first policy (#358) leaves linked worktrees accumulating under
`.claude/worktrees/`. Nothing removes the stale ones, and some predate the
tooling that made worktree deletes safe — so a naive `Remove-Item -Recurse` or
`git worktree remove -f` can walk a directory *junction* (a pre-#350
`frontend/node_modules` linked into the primary install) and gut the primary
tree (#350).

The safety gate is the whole point: this tool refuses to touch any worktree that
still contains a reparse point (a junction or symlink), and it never descends
*through* one while scanning. It REPORTS by default and removes only with
`--remove`, and only worktrees that are both clean (no uncommitted or untracked
files) and fully merged into `origin/master`. Everything else it leaves and
says why. `git worktree remove` is called *without* `--force`, so even a
mis-classification cannot delete a dirty tree.

It is a manual maintenance tool on purpose — not a session hook (auto-removing a
worktree is exactly the hazard the policy created) and not a CI gate (a runner
has no `.claude/worktrees/`).

Usage:
    python scripts/clean_worktrees.py             # report only
    python scripts/clean_worktrees.py --remove    # remove the STALE ones
    python scripts/clean_worktrees.py --no-fetch  # skip the origin/master refresh
"""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

WORKTREES_SUBDIR = (".claude", "worktrees")
# 0x400 = FILE_ATTRIBUTE_REPARSE_POINT. `stat` exposes it as a constant on every
# platform (0 on POSIX bit-tests), so junctions AND name-surrogate symlinks are
# caught on Windows; POSIX symlinks fall through to the S_ISLNK check below.
FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

STATUS_SKIP = "SKIP"        # the primary worktree, or the one we're running in
STATUS_BLOCKED = "BLOCKED"  # contains a reparse point — refuse until it's removed
STATUS_KEEP = "KEEP"        # uncommitted/untracked, or commits not yet on master
STATUS_STALE = "STALE"      # clean and fully merged — safe to remove


# ── git plumbing ────────────────────────────────────────────────────────────


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=30,
    )


@dataclass
class Worktree:
    path: Path
    branch: str | None
    head: str | None
    is_main: bool = False

    @property
    def name(self) -> str:
        return self.path.name


def list_worktrees(repo: Path) -> list[Worktree]:
    """Parse `git worktree list --porcelain`. The first record is the main tree."""
    out = _git(["worktree", "list", "--porcelain"], cwd=repo)
    if out.returncode != 0:
        raise SystemExit(f"git worktree list failed: {out.stderr.strip()}")
    records: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in out.stdout.splitlines():
        if not line.strip():
            if cur:
                records.append(cur)
                cur = {}
            continue
        key, _, val = line.partition(" ")
        cur[key] = val
    if cur:
        records.append(cur)

    trees: list[Worktree] = []
    for i, rec in enumerate(records):
        branch = rec.get("branch")
        if branch and branch.startswith("refs/heads/"):
            branch = branch[len("refs/heads/") :]
        trees.append(
            Worktree(path=Path(rec["worktree"]), branch=branch, head=rec.get("HEAD"), is_main=(i == 0))
        )
    return trees


# ── the reparse-point safety scan ───────────────────────────────────────────


def _is_reparse(st: os.stat_result) -> bool:
    if getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
        return True
    return stat.S_ISLNK(st.st_mode)


def find_reparse_points(root: Path) -> list[Path]:
    """Every junction/symlink at or under `root`, found WITHOUT descending into one.

    Reparse points are checked before recursion and skipped, so the walk can
    never step through a junction into the primary tree (the #350 hazard).
    """
    try:
        root_st = os.lstat(root)
    except OSError:
        return []
    if _is_reparse(root_st):
        return [root]

    found: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if _is_reparse(st):
                found.append(Path(entry.path))
                continue  # never descend into a reparse point
            if stat.S_ISDIR(st.st_mode):
                stack.append(Path(entry.path))
    return found


# ── classification ──────────────────────────────────────────────────────────


@dataclass
class Assessment:
    worktree: Worktree
    status: str
    reason: str
    reparse_points: list[Path] = field(default_factory=list)


def _is_within(inner: Path, outer: Path) -> bool:
    try:
        inner_r, outer_r = inner.resolve(), outer.resolve()
    except OSError:
        return False
    return inner_r == outer_r or outer_r in inner_r.parents


def assess(wt: Worktree, running_from: Path) -> Assessment:
    """Decide what to do with one worktree. Never returns STALE unless it is both
    free of reparse points and clean + fully merged into origin/master."""
    if wt.is_main:
        return Assessment(wt, STATUS_SKIP, "primary worktree")
    if _is_within(running_from, wt.path):
        return Assessment(wt, STATUS_SKIP, "current worktree (running from inside it)")
    if not wt.path.exists():
        return Assessment(wt, STATUS_KEEP, "registered path missing on disk — `git worktree prune` will drop it")

    reparse = find_reparse_points(wt.path)
    if reparse:
        return Assessment(
            wt, STATUS_BLOCKED, f"{len(reparse)} reparse point(s) — remove the link(s) by hand first", reparse
        )

    dirty = _git(["status", "--porcelain"], cwd=wt.path)
    if dirty.returncode != 0:
        return Assessment(wt, STATUS_KEEP, f"git status failed: {dirty.stderr.strip()}")
    if dirty.stdout.strip():
        return Assessment(wt, STATUS_KEEP, "uncommitted or untracked changes")

    ahead = _git(["rev-list", "--count", "origin/master..HEAD"], cwd=wt.path)
    if ahead.returncode != 0:
        return Assessment(wt, STATUS_KEEP, f"cannot compare to origin/master: {ahead.stderr.strip()}")
    if ahead.stdout.strip() != "0":
        return Assessment(wt, STATUS_KEEP, f"{ahead.stdout.strip()} commit(s) not in origin/master (unmerged work)")

    return Assessment(wt, STATUS_STALE, "clean and fully merged into origin/master")


# ── removal ─────────────────────────────────────────────────────────────────


def remove_worktree(wt: Worktree, main_root: Path) -> str:
    """Remove one worktree (no --force: a dirty tree is still refused), then its
    merged branch. Returns a human-readable outcome line."""
    rm = _git(["worktree", "remove", str(wt.path)], cwd=main_root)
    if rm.returncode != 0:
        return f"NOT removed: {rm.stderr.strip()}"
    if not wt.branch:
        return "removed (detached — no branch to delete)"
    br = _git(["branch", "-d", wt.branch], cwd=main_root)
    if br.returncode == 0:
        return f"removed; branch {wt.branch} deleted"
    return f"removed; branch {wt.branch} kept ({br.stderr.strip()})"


def orphan_dirs(main_root: Path, registered: set[Path]) -> list[Path]:
    """Directories under `.claude/worktrees/` that git no longer tracks — left
    behind when a worktree was unregistered but its files were not deleted."""
    wt_dir = main_root.joinpath(*WORKTREES_SUBDIR)
    if not wt_dir.is_dir():
        return []
    orphans: list[Path] = []
    for entry in os.scandir(wt_dir):
        if not entry.is_dir(follow_symlinks=False):
            continue
        try:
            resolved = Path(entry.path).resolve()
        except OSError:
            resolved = Path(entry.path)
        if resolved not in registered:
            orphans.append(Path(entry.path))
    return orphans


# ── CLI ─────────────────────────────────────────────────────────────────────


def _report(assessments: list[Assessment], main_root: Path, registered: set[Path]) -> None:
    for a in assessments:
        print(f"{a.status:<8}{a.worktree.name}  -  {a.reason}")
        for link in a.reparse_points:
            print(f"           reparse point: {link}")
    for orphan in orphan_dirs(main_root, registered):
        print(f"ORPHAN  {orphan.name}  -  on disk under .claude/worktrees/ but not a registered worktree")


def _remove_stale(stale: list[Assessment], main_root: Path) -> None:
    for a in stale:
        print(f"-> removing {a.worktree.name}: {remove_worktree(a.worktree, main_root)}")
    pruned = _git(["worktree", "prune"], cwd=main_root)
    print("git worktree prune: ok" if pruned.returncode == 0 else f"warn  'git worktree prune' failed: {pruned.stderr.strip()}")


def _remove_hint(stale: list[Assessment]) -> None:
    names = ", ".join(a.worktree.name for a in stale)
    print(f"\n{len(stale)} removable: {names}")
    print("Re-run with --remove to delete them (link-first safety already checked).")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Report or remove stale git worktrees, junction-safe (#359).")
    parser.add_argument("--remove", action="store_true", help="remove worktrees classified STALE (default: report only)")
    parser.add_argument("--no-fetch", action="store_true", help="skip 'git fetch origin master' before classifying")
    args = parser.parse_args(argv)

    running_from = Path.cwd()
    trees = list_worktrees(running_from)
    if not trees:
        print("No worktrees registered.")
        return 0
    main_root = next((t.path for t in trees if t.is_main), trees[0].path)

    if not args.no_fetch:
        fetched = _git(["fetch", "origin", "master"], cwd=main_root)
        if fetched.returncode != 0:
            print(f"warn  'git fetch origin master' failed ({fetched.stderr.strip()}); using the local ref.")

    assessments = [assess(t, running_from) for t in trees]
    _report(assessments, main_root, {t.path.resolve() for t in trees})

    stale = [a for a in assessments if a.status == STATUS_STALE]
    if args.remove:
        _remove_stale(stale, main_root)
    elif stale:
        _remove_hint(stale)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
