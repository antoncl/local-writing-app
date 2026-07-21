"""The quality gates' own invariants (#352).

These assert properties of the *test run itself*, not of the app. They exist
because a gate that validates the wrong code fails in the two worst ways: red
when nothing is broken, and green when something is.
"""

from __future__ import annotations

from pathlib import Path

import app

REPO = Path(__file__).resolve().parents[2]


def test_app_under_test_belongs_to_this_checkout():
    """`import app` must resolve inside the tree these tests were collected from.

    The shared venv installs the backend editable against the *primary* git
    worktree, so from a linked worktree `app` resolves there unless something
    puts this checkout's `backend/` first (scripts/venv_run.py does). Without
    that, pytest runs one tree's tests against another tree's code — and the
    primary tree normally carries uncommitted WIP.
    """
    app_dir = Path(app.__file__).resolve().parent
    expected = (REPO / "backend" / "app").resolve()
    assert app_dir == expected, (
        f"tests collected from {REPO} but `app` imported from {app_dir}.\n"
        "Run the suite via `python scripts/venv_run.py -m pytest backend/tests`, "
        "which puts this checkout's backend/ on PYTHONPATH."
    )
