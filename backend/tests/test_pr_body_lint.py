"""Rules for the PR-body hygiene guard (scripts/check_pr_body.py, #1419).

The script is not part of the backend package, so load it by path.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_pr_body.py"
_spec = importlib.util.spec_from_file_location("check_pr_body", _SCRIPT)
assert _spec and _spec.loader
check_pr_body = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_pr_body)
lint_pr_body = check_pr_body.lint_pr_body

BRANCH = "worktree-wizard-ollama-provider-1417"  # a conventional worktree branch


# ---- Rule A: comma-list after one keyword --------------------------------------


def test_comma_list_flags_the_trailing_numbers():
    errors = lint_pr_body("Closes #1410, #1411", "feature/x")
    assert len(errors) == 1
    assert "#1411" in errors[0]
    assert "#1410" in errors[0]  # names the one that DOES close, for the fix hint


def test_comma_list_three_issues():
    errors = lint_pr_body("Closes #1381, #1383, #1382", "feature/x")
    assert len(errors) == 1
    assert "#1383" in errors[0] and "#1382" in errors[0]


def test_and_joined_list_flagged():
    errors = lint_pr_body("Fixes #1 and #2", "feature/x")
    assert any("#2" in e for e in errors)


@pytest.mark.parametrize("body", [
    "Closes #1410, closes #1411",
    "Closes #1410, closes #1411, closes #1412",
    "Fixes #1. Resolves #2.",
    "Closes #1410 and closes #1411",
])
def test_per_issue_keyword_is_accepted(body):
    # Non-worktree branch so only Rule A is in play.
    assert lint_pr_body(body, "feature/x") == []


def test_case_insensitive_keyword():
    assert lint_pr_body("CLOSES #1, #2", "feature/x")


def test_a_single_close_is_fine():
    assert lint_pr_body("Closes #1410", "feature/x") == []


def test_reference_only_without_keyword_is_not_a_comma_list():
    # A bare "see #1, #2" is not a closing comma-list — Rule A must not fire.
    assert lint_pr_body("Related: #1, #2", "feature/x") == []


# ---- Rule B: a worktree branch's issue must close ------------------------------


def test_worktree_branch_requires_closing_its_issue():
    errors = lint_pr_body("Fixes the overflow. See #1417.", BRANCH)
    assert len(errors) == 1
    assert "#1417" in errors[0]


def test_worktree_branch_with_proper_close_passes():
    assert lint_pr_body("Closes #1417.\n\nDetails…", BRANCH) == []


def test_no_issue_marker_escapes_rule_b():
    assert lint_pr_body("No-issue: a pure chore.", BRANCH) == []


def test_release_branch_trailing_single_digit_is_skipped():
    # `worktree-release-0-9-0` ends in a single digit — not an issue number.
    assert lint_pr_body("Bump version strings.", "worktree-release-0-9-0") == []


def test_non_worktree_branch_is_not_subject_to_rule_b():
    # A human branch that merely references an issue is fine.
    assert lint_pr_body("Improves #1417 handling.", "feature/overflow") == []


def test_worktree_branch_without_trailing_number_is_skipped():
    assert lint_pr_body("Some cleanup.", "worktree-cleanup") == []


def test_both_rules_can_fire_together():
    # Comma-list AND the branch issue isn't closed.
    errors = lint_pr_body("Closes #10, #11", BRANCH)
    assert len(errors) == 2


# ---- The event-parsing seam (the blocking gate's input) -------------------------
# A wrong field path here would feed lint_pr_body("", "") and pass every PR while
# looking green, so pin the exact GitHub pull_request payload shape.


def test_load_event_extracts_body_and_branch(tmp_path, monkeypatch):
    event = {"pull_request": {"body": "Closes #1419", "head": {"ref": BRANCH}}}
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
    assert check_pr_body._load_event() == ("Closes #1419", BRANCH)


def test_load_event_null_body_and_missing_ref_are_empty(tmp_path, monkeypatch):
    # GitHub sends body: null for an empty description; head may lack a ref.
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"pull_request": {"body": None, "head": {}}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
    assert check_pr_body._load_event() == ("", "")


def test_load_event_no_path_is_empty(monkeypatch):
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    assert check_pr_body._load_event() == ("", "")
