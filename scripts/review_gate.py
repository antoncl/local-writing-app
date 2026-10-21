#!/usr/bin/env python3
"""Review-before-push gate: no `git push` / `gh pr create` from a Claude
session until a code review has been recorded for the commit being pushed.

The rule it enforces (CLAUDE.md, "Everything lands via a PR"): run the
adversarial `/code-review` over the final diff BEFORE the first push, so the
review's fixes ride the same ~17-minute CI run. As prose the rule kept being
skipped — push first, review after, pay a second CI run — so it is a gate now.

Two modes, one file, so the marker's location and format are defined once:

  python scripts/review_gate.py mark   # after /code-review AND its fixes are committed
  python scripts/review_gate.py hook   # Claude Code PreToolUse hook (event JSON on stdin)

**The marker** is `<git-dir>/claude-reviewed-sha`: the full SHA of the commit
the review covered. The git dir is per-worktree, so each worktree carries its
own record and nothing is ever committed. `mark` refuses while tracked files
have uncommitted changes — the fixes must be *in* the commit it records.

**What the hook accepts**: the recorded SHA is `HEAD`, or `HEAD` descends from
it through merges and master's own commits only (bringing the branch up to
date with master is not new work). Any other new commit re-blocks until the
review is recorded again.

**The escape** is visible on purpose: a trailing comment on the command,

  git push -u origin my-branch  # review-gate: skip docs-only change

with a non-empty reason. It works the same in bash and PowerShell, and it sits
in the transcript where Anton can see it.

Also allowed unconditionally: `--dry-run` and branch deletion (`--delete`,
`-d`, `:branch`) — neither publishes unreviewed code.

The hook blocks with exit 2 and the reason on stderr (PreToolUse semantics:
stderr is fed back to the model). It only looks at commands that push; any
other event, or an unparseable one, passes with exit 0.
"""

from __future__ import annotations

import contextlib
import json
import re
import subprocess
import sys
from pathlib import Path

MARKER_NAME = "claude-reviewed-sha"
BASE_REF = "origin/master"

# `git [global opts] push`, where global opts may take a value (`-C dir`, `-c k=v`).
_GIT_PUSH = re.compile(
    r"(?:^|[\s;&|(])git(?:\.exe)?(?:\s+(?:-[Cc]\s+(?:\"[^\"]*\"|'[^']*'|\S+)|--?[\w-]+(?:=\S+)?))*\s+push\b"
)
_GH_PR_CREATE = re.compile(r"(?:^|[\s;&|(])gh(?:\.exe)?\s+pr\s+create\b")
_GIT_DASH_C = re.compile(r"\bgit(?:\.exe)?\s+-C\s+(\"[^\"]*\"|'[^']*'|\S+)")
# A git command that moves HEAD, chained with the push in the same tool call:
# the hook runs before any of it, so it would check the pre-commit HEAD.
_HEAD_MOVER = re.compile(
    r"\bgit(?:\.exe)?(?:\s+-\S+(?:\s+\S+)?)*?\s+"
    r"(?:commit|merge|pull|rebase|cherry-pick|am|revert|reset)\b"
)
_ESCAPE = re.compile(r"#\s*review-gate:\s*skip\b[ \t]*(\S.*)?$", re.MULTILINE)
_SAFE_PUSH = re.compile(r"\s(?:--dry-run|-n|--delete|-d)\b|\s:\S")

with contextlib.suppress(Exception):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def git(cwd: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def marker_path(cwd: Path) -> Path | None:
    git_dir = git(cwd, "rev-parse", "--absolute-git-dir")
    return Path(git_dir) / MARKER_NAME if git_dir else None


def recorded_sha(cwd: Path) -> str | None:
    path = marker_path(cwd)
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def review_covers_head(cwd: Path, reviewed: str, head: str) -> bool:
    """True when every non-merge commit since `reviewed` came from master."""
    if reviewed == head:
        return True
    if git(cwd, "merge-base", "--is-ancestor", reviewed, head) is None:
        return False
    exclude = [f"^{BASE_REF}"] if git(cwd, "rev-parse", "--verify", "-q", BASE_REF) else []
    unreviewed = git(cwd, "rev-list", "--no-merges", f"{reviewed}..{head}", *exclude)
    return unreviewed == ""


# --- mark -------------------------------------------------------------------

def mark(cwd: Path) -> int:
    head = git(cwd, "rev-parse", "HEAD")
    path = marker_path(cwd)
    if head is None or path is None:
        print("review_gate: not inside a git checkout", file=sys.stderr)
        return 1
    dirty = git(cwd, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        print(
            "review_gate: tracked files have uncommitted changes — commit the "
            "review fixes first, so the recorded commit contains them:\n" + dirty,
            file=sys.stderr,
        )
        return 1
    path.write_text(head + "\n", encoding="utf-8")
    subject = git(cwd, "log", "-1", "--format=%s") or ""
    print(f"review_gate: recorded review of {head[:12]} ({subject})")
    return 0


# --- hook -------------------------------------------------------------------

def push_kind(command: str) -> str | None:
    if _GH_PR_CREATE.search(command):
        return "gh pr create"
    match = _GIT_PUSH.search(command)
    if match and not _SAFE_PUSH.search(command[match.end():].split("#", 1)[0]):
        return "git push"
    return None


def command_cwd(command: str, event_cwd: Path) -> Path:
    match = _GIT_DASH_C.search(command)
    if not match:
        return event_cwd
    target = Path(match.group(1).strip("\"'"))
    return target if target.is_absolute() else event_cwd / target


def block(reason: str) -> int:
    print(
        f"review_gate: BLOCKED. {reason}\n"
        "Run /code-review over the branch's diff, fix the findings, commit the "
        "fixes, then `python scripts/review_gate.py mark` and retry. For a "
        "docs-only or emergency push, append a visible escape to the command: "
        "`  # review-gate: skip <reason>`.",
        file=sys.stderr,
    )
    return 2


def check(command: str, event_cwd: Path) -> int:
    kind = push_kind(command)
    if kind is None:
        return 0
    escape = _ESCAPE.search(command)
    if escape:
        if escape.group(1):
            return 0
        return block("The `# review-gate: skip` escape needs a reason after it.")
    if kind == "git push" and _HEAD_MOVER.search(command):
        return block(
            "This command moves HEAD and pushes in one call, so the hook can "
            "only see the commit from before it. Run them as separate calls."
        )
    cwd = command_cwd(command, event_cwd)
    head = git(cwd, "rev-parse", "HEAD")
    if head is None:
        return block(f"Could not resolve HEAD in {cwd}.")
    reviewed = recorded_sha(cwd)
    if reviewed is None:
        return block(f"No code review is recorded for this worktree (HEAD {head[:12]}).")
    if not review_covers_head(cwd, reviewed, head):
        return block(
            f"The recorded review covers {reviewed[:12]}, but HEAD is {head[:12]} "
            "and has new commits since."
        )
    return 0


def hook() -> int:
    try:
        event = json.load(sys.stdin)
        command = event["tool_input"]["command"]
        event_cwd = Path(event.get("cwd") or ".")
    except Exception:
        return 0
    if not isinstance(command, str):
        return 0
    return check(command, event_cwd)


def main(argv: list[str]) -> int:
    if argv[1:] == ["mark"]:
        return mark(Path.cwd())
    if argv[1:] == ["hook"]:
        return hook()
    print("usage: review_gate.py mark | hook", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
