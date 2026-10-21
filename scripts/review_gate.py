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
own record and nothing is ever committed. `mark` refuses while the worktree has
uncommitted or untracked changes — the fixes must be *in* the commit it records.

**What the hook accepts**: the recorded SHA is `HEAD`, or `HEAD` descends from
it through merges and master's own commits only (bringing the branch up to
date with master is not new work). Any other new commit re-blocks until the
review is recorded again. A push names only `HEAD` / the current branch: a
refspec for another branch, or `--all` / `--mirror` / `--branches`, is blocked,
since the review only ever covers `HEAD`.

**The escape** is visible on purpose: a trailing comment on the command,

  git push -u origin my-branch  # review-gate: skip docs-only change

with a non-empty reason. It works the same in bash and PowerShell, and it sits
in the transcript where Anton can see it.

Also allowed unconditionally: `--dry-run` and branch deletion (`--delete`,
`-d`, `:branch`) — neither publishes unreviewed code.

The command is judged one segment at a time (split at `;`, `&&`, `||`, `|`,
`&` and newlines, outside quotes), so a flag or `-C` in one command cannot
vouch for a push in another.

The hook blocks with exit 2 and the reason on stderr (PreToolUse semantics:
stderr is fed back to the model). It only looks at commands that push; any
other event, or an unparseable one, passes with exit 0.
"""

from __future__ import annotations

import contextlib
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

MARKER_NAME = "claude-reviewed-sha"
BASE_REF = "origin/master"

# Commands that move HEAD. Chained with a push in the same tool call, they run
# after the hook has already judged the pre-move HEAD.
_HEAD_MOVERS = {
    "commit", "merge", "pull", "rebase", "cherry-pick", "am", "revert", "reset",
    "checkout", "switch",
}
# git global options that take their value as the next token.
_GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
# push options that take their value as the next token.
_PUSH_VALUE_OPTS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
_PUSH_SAFE_OPTS = {"--dry-run", "-n", "--delete", "-d"}
_PUSH_ALL_REFS = {"--all", "--mirror", "--branches"}

_QUOTED = re.compile(r"\"(?:\\.|[^\"\\])*\"|'[^']*'")
_SEPARATOR = re.compile(r"&&|\|\||[;|&\n]")
# A redirection token (`>`, `2>`, `>>log`); the `2>` left over when `2>&1` is
# split at its `&` is one too, and the `1` after it a token of its own segment.
_REDIRECT = re.compile(r"^[\d*&]*(?:>>?|<)")
_ESCAPE = re.compile(r"#[ \t]*review-gate:[ \t]*skip\b([^\n]*)\Z")

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
    # Untracked files count: a review fix is often a new file (a test).
    dirty = git(cwd, "status", "--porcelain")
    if dirty:
        print(
            "review_gate: the worktree has uncommitted or untracked changes — "
            "commit the review fixes first, so the recorded commit contains "
            "them:\n" + dirty,
            file=sys.stderr,
        )
        return 1
    path.write_text(head + "\n", encoding="utf-8")
    subject = git(cwd, "log", "-1", "--format=%s") or ""
    print(f"review_gate: recorded review of {head[:12]} ({subject})")
    return 0


# --- hook: reading the command ---------------------------------------------

@dataclass
class Call:
    """One `git …` or `gh …` invocation inside the command."""

    program: str          # "git" | "gh"
    cwd: Path | None      # from `git -C <dir>`, if given
    args: list[str]       # everything after the global options


def _mask_quotes(command: str) -> str:
    """Same length as `command`, quoted contents replaced, so separators and
    `#` inside quotes cannot split a segment or start a comment."""
    return _QUOTED.sub(lambda m: m.group(0)[0] + "_" * (len(m.group(0)) - 2) + m.group(0)[-1], command)


def _segments(command: str, masked: str) -> list[str]:
    """Split at unquoted separators, dropping each segment's unquoted `# comment`."""
    bounds = [0]
    for match in _SEPARATOR.finditer(masked):
        bounds += [match.start(), match.end()]
    bounds.append(len(command))
    segments = []
    for start, end in zip(bounds[::2], bounds[1::2], strict=True):
        hash_at = masked.find("#", start, end)
        segments.append(command[start:end if hash_at < 0 else hash_at])
    return segments


def _tokens(segment: str) -> list[str]:
    try:
        raw = shlex.split(segment, posix=False)
    except ValueError:
        raw = segment.split()
    tokens = []
    skip_next = False
    for token in raw:
        if skip_next:
            skip_next = False
        elif _REDIRECT.match(token):
            # `> file` puts its target in the next token; `>file`, `2>&1` don't.
            skip_next = _REDIRECT.match(token).end() == len(token)
        else:
            quoted = len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'"
            tokens.append(token[1:-1] if quoted else token)
    return tokens


def _program(token: str) -> str:
    name = re.split(r"[\\/]", token)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def parse_calls(command: str) -> list[Call]:
    masked = _mask_quotes(command)
    calls = []
    for segment in _segments(command, masked):
        tokens = _tokens(segment.strip().lstrip("(&").strip())
        if not tokens or _program(tokens[0]) not in ("git", "gh"):
            continue
        program, rest, cwd = _program(tokens[0]), tokens[1:], None
        if program == "git":
            while rest and rest[0].startswith("-"):
                opt = rest.pop(0)
                if opt in _GIT_VALUE_OPTS and rest:
                    value = rest.pop(0)
                    if opt == "-C":
                        cwd = Path(value)
        calls.append(Call(program, cwd, rest))
    return calls


def is_push(call: Call) -> bool:
    if call.program == "gh":
        return call.args[:2] == ["pr", "create"]
    return call.args[:1] == ["push"]


def _push_args(call: Call) -> tuple[set[str], list[str]]:
    """A `git push` call's options and refspecs (the remote dropped)."""
    options, positional, args = set(), [], call.args[1:]
    while args:
        arg = args.pop(0)
        if arg.startswith("-"):
            options.add(arg)
            if arg in _PUSH_VALUE_OPTS and args:
                args.pop(0)
        else:
            positional.append(arg)
    return options, positional[1:]


def publishes_nothing(call: Call) -> bool:
    """A dry run, or a push that only deletes remote branches."""
    if call.program != "git":
        return False
    options, refspecs = _push_args(call)
    if options & _PUSH_SAFE_OPTS:
        return True
    return bool(refspecs) and all(spec.startswith(":") for spec in refspecs)


def ref_problem(call: Call, branch: str | None) -> str | None:
    """Why this push publishes refs other than HEAD, which the review covers."""
    if call.program != "git":
        return None
    options, refspecs = _push_args(call)
    if wide := options & _PUSH_ALL_REFS:
        return f"`{min(wide)}` pushes refs other than HEAD, which a review cannot cover."
    allowed = {"", "HEAD", "@"} |({branch, f"refs/heads/{branch}"} if branch else set())
    for spec in refspecs:
        source = spec.lstrip("+").split(":", 1)[0]
        if source not in allowed:
            return f"Refspec `{spec}` pushes something other than HEAD ({branch})."
    return None


# --- hook: the verdict ------------------------------------------------------

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


def check_push(call: Call, event_cwd: Path) -> str | None:
    cwd = event_cwd / call.cwd if call.cwd else event_cwd
    head = git(cwd, "rev-parse", "HEAD")
    if head is None:
        return f"Could not resolve HEAD in {cwd}."
    problem = ref_problem(call, git(cwd, "symbolic-ref", "--short", "-q", "HEAD"))
    if problem:
        return problem
    reviewed = recorded_sha(cwd)
    if reviewed is None:
        return f"No code review is recorded for this worktree (HEAD {head[:12]})."
    if not review_covers_head(cwd, reviewed, head):
        return (
            f"The recorded review covers {reviewed[:12]}, but HEAD is "
            f"{head[:12]} and has new commits since."
        )
    return None


def check(command: str, event_cwd: Path) -> int:
    calls = parse_calls(command)
    pushes = [c for c in calls if is_push(c) and not publishes_nothing(c)]
    if not pushes:
        return 0
    escape = _ESCAPE.search(_mask_quotes(command).rstrip())
    if escape:
        if escape.group(1).strip():
            return 0
        return block("The `# review-gate: skip` escape needs a reason after it.")
    if any(c.program == "git" and c.args[:1] and c.args[0] in _HEAD_MOVERS for c in calls):
        return block(
            "This command moves HEAD and pushes in one call, so the hook can "
            "only see the commit from before it. Run them as separate calls."
        )
    for call in pushes:
        problem = check_push(call, event_cwd)
        if problem:
            return block(problem)
    return 0


def hook() -> int:
    try:
        # Bytes, decoded as UTF-8: the locale codec (cp1252 on Windows) raises
        # on some UTF-8 sequences, and a decode error must not let a push by.
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
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
