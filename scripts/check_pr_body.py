#!/usr/bin/env python3
"""PR-body hygiene guard — make merges close the issues they resolve.

GitHub auto-closes an issue only when a closing keyword *directly precedes each
number*. `Closes #1410, #1411` closes ONLY #1410; the trailing bare numbers are
mentions. This silently leaked six 1.0.0 issues open until swept by hand (#1419),
and it recurs. Two high-precision rules catch both faces of the mistake:

  * Rule A (comma-list): a closing keyword followed by comma/`and`-joined bare
    `#N` — the trailing ones will NOT close. Applies to every branch; near-zero
    false positives (nobody writes `Closes #A, #B` intending only #A to close).
  * Rule B (branch issue): a `worktree-…-<digits>` branch encodes its primary
    issue, so the body must `Closes #<that number>`. Catches "forgot the keyword
    entirely". Skips non-worktree branches; escapable with a `No-issue` marker in
    the body for a chore/release worktree that closes nothing.

The fix in both cases is to repeat the keyword per issue: `Closes #A, closes #B`.

Usage (CI reads the event payload automatically):
    python scripts/check_pr_body.py                      # reads $GITHUB_EVENT_PATH
    python scripts/check_pr_body.py --body-file b.md --branch worktree-x-42
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

# close/closes/closed · fix/fixes/fixed · resolve/resolves/resolved — GitHub's
# closing keywords (case-insensitive).
_KEYWORD = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)"

# Rule A: keyword + #N, then one or more `, #M` / ` and #M` where the trailing
# number carries NO keyword of its own. The separator must be followed directly
# by `#`, so the correct `Closes #A, closes #B` form never matches.
_COMMA_LIST = re.compile(
    rf"(?i)\b{_KEYWORD}\s+#\d+(?:(?:\s*,\s*|\s+and\s+)#\d+)+"
)

# The trailing `-<digits>` of a worktree branch = its primary issue number.
_BRANCH_ISSUE = re.compile(r"-(\d{2,})$")

# Escape hatch: a worktree branch whose PR closes nothing (a chore/release) opts
# out of Rule B by putting this marker anywhere in the body.
_NO_ISSUE = re.compile(r"(?i)\bno-issue\b")


def _closes(body: str, number: str) -> bool:
    """True when `body` closes issue `number` with a keyword right before it."""
    return re.search(rf"(?i)\b{_KEYWORD}\s+#{number}\b", body) is not None


def lint_pr_body(body: str, branch: str) -> list[str]:
    """Return a list of hygiene errors for this PR body (empty = clean)."""
    body = body or ""
    errors: list[str] = []

    for match in _COMMA_LIST.finditer(body):
        text = match.group(0)
        numbers = re.findall(r"#\d+", text)
        # The first number closes; every later one is a silent mention.
        leaked = ", ".join(numbers[1:])
        errors.append(
            f"Comma-list closing: {text!r} closes only {numbers[0]} - "
            f"{leaked} will NOT close. Repeat the keyword per issue "
            f'(e.g. "Closes {numbers[0]}, closes {numbers[1]}").'
        )

    branch_match = branch.startswith("worktree-") and _BRANCH_ISSUE.search(branch)
    if branch_match and not _NO_ISSUE.search(body):
        number = branch_match.group(1)
        if not _closes(body, number):
            errors.append(
                f"Branch '{branch}' targets issue #{number}, but the body has no "
                f'"Closes #{number}". Add it, or put "No-issue" in the body if this '
                f"PR intentionally closes nothing."
            )

    return errors


def _load_event() -> tuple[str, str]:
    """(body, branch) from the GitHub Actions pull_request event payload."""
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return "", ""
    with open(path, encoding="utf-8") as handle:
        event = json.load(handle)
    pr = event.get("pull_request") or {}
    body = pr.get("body") or ""
    branch = (pr.get("head") or {}).get("ref") or ""
    return body, branch


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="PR-body hygiene guard")
    parser.add_argument("--body-file", help="path to a file holding the PR body")
    parser.add_argument("--branch", default="", help="the PR head branch name")
    args = parser.parse_args(argv)

    if args.body_file:
        with open(args.body_file, encoding="utf-8") as handle:
            body = handle.read()
        branch = args.branch
    else:
        body, branch = _load_event()

    errors = lint_pr_body(body, branch)
    if errors:
        print("PR-body hygiene check failed:\n", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "\nGitHub auto-closes an issue only when a keyword directly precedes "
            "each number.",
            file=sys.stderr,
        )
        return 1

    print("PR-body hygiene: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
