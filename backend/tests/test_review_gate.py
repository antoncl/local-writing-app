"""The review-before-push gate (`scripts/review_gate.py`).

Each test drives the real script against a throwaway git repo with a bare
`origin`, through the same stdin JSON the PreToolUse hook receives — so what is
pinned is the hook's verdict on a command, not a helper's return value.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "review_gate.py"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "master", str(work)], check=True)
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "t")
    _git(work, "config", "commit.gpgsign", "false")
    _git(work, "remote", "add", "origin", str(origin))
    _commit(work, "base")
    _git(work, "push", "-q", "origin", "master")
    _git(work, "fetch", "-q", "origin")
    _git(work, "checkout", "-q", "-b", "topic")
    return work


def _hook(repo: Path, command: str, tool: str = "Bash") -> subprocess.CompletedProcess:
    event = {"tool_name": tool, "tool_input": {"command": command}, "cwd": str(repo)}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "hook"],
        input=json.dumps(event), capture_output=True, text=True, encoding="utf-8",
    )


def _mark(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "mark"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
    )


PUSH = "git push -u origin topic"


def test_push_is_blocked_before_any_review(repo):
    _commit(repo, "work")
    result = _hook(repo, PUSH)
    assert result.returncode == 2
    assert "No code review is recorded" in result.stderr


def test_pr_create_is_blocked_before_any_review(repo):
    _commit(repo, "work")
    assert _hook(repo, 'gh pr create --title "x" --body-file b.md').returncode == 2


def test_push_is_allowed_after_mark_then_reblocked_by_a_new_commit(repo):
    _commit(repo, "work")
    assert _mark(repo).returncode == 0
    assert _hook(repo, PUSH).returncode == 0
    _commit(repo, "more work")
    result = _hook(repo, PUSH)
    assert result.returncode == 2
    assert "new commits since" in result.stderr


def test_bringing_the_branch_up_to_date_with_master_needs_no_re_review(repo):
    _commit(repo, "work")
    assert _mark(repo).returncode == 0
    # master moves on origin; the branch merges it in.
    _git(repo, "checkout", "-q", "master")
    _commit(repo, "someone else's change")
    _git(repo, "push", "-q", "origin", "master")
    _git(repo, "checkout", "-q", "topic")
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "merge", "-q", "--no-edit", "origin/master")
    assert _hook(repo, PUSH).returncode == 0


def test_mark_refuses_uncommitted_review_fixes(repo):
    _commit(repo, "work")
    (repo / "work").write_text("fixed", encoding="utf-8")
    result = _mark(repo)
    assert result.returncode == 1
    assert "uncommitted" in result.stderr
    assert _hook(repo, PUSH).returncode == 2


def test_the_escape_needs_a_reason(repo):
    _commit(repo, "work")
    assert _hook(repo, PUSH + "  # review-gate: skip docs-only change").returncode == 0
    assert _hook(repo, PUSH + "  # review-gate: skip").returncode == 2


def test_commit_and_push_in_one_call_is_blocked_even_when_reviewed(repo):
    """The hook runs before the commit, so it would vouch for the old HEAD."""
    _commit(repo, "work")
    assert _mark(repo).returncode == 0
    result = _hook(repo, 'git commit -am "late fix" && ' + PUSH)
    assert result.returncode == 2
    assert "separate calls" in result.stderr


@pytest.mark.parametrize("command", [
    "git push origin --delete topic",
    "git push -d origin topic",
    "git push origin :topic",
    "git push --dry-run origin topic",
    "git status",
    "git log --oneline origin/master..HEAD",
    "gh pr view 12",
    "echo push",
])
def test_commands_that_publish_nothing_pass(repo, command):
    _commit(repo, "work")
    assert _hook(repo, command).returncode == 0


@pytest.mark.parametrize("command", [
    "git -C {repo} push origin topic",
    "git -c core.quotepath=off push origin topic",
    "cd x; git push",
    "git.exe push origin topic",
])
def test_push_spellings_are_all_gated(repo, command):
    _commit(repo, "work")
    result = _hook(repo, command.format(repo=repo), tool="PowerShell")
    assert result.returncode == 2


def test_git_dash_c_checks_the_named_checkout(repo, tmp_path):
    """`git -C <repo> push` is judged by <repo>'s marker, not the session's cwd."""
    _commit(repo, "work")
    assert _mark(repo).returncode == 0
    event = {"tool_name": "Bash", "tool_input": {"command": f'git -C "{repo}" push'},
             "cwd": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "hook"],
        input=json.dumps(event), capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0


def test_an_unparseable_event_passes(repo):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "hook"],
        input="not json", capture_output=True, text=True,
    )
    assert result.returncode == 0
