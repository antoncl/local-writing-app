"""The changed-area classifier that lets gates.yml skip untouched jobs.

A wrong mapping fails silently: the job that should have gone red is skipped and
reports as passed. So the rules that matter are pinned case by case, and the
fail-open default — run everything — is pinned for the paths nobody mapped.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "_gate_ci_changed_areas", REPO / "scripts" / "ci_changed_areas.py"
)
ci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci)

ALL = {"backend", "frontend", "e2e"}


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        # The motivating PR: prompt Markdown + a backend test.
        (["backend/app/builtin_library/prompts/x.md", "backend/tests/test_x.py"], {"backend"}),
        (["backend/app/services/project_service.py"], {"backend", "e2e"}),
        (["backend/requirements.lock"], {"backend", "e2e"}),
        (["frontend/src/App.svelte"], {"frontend", "e2e"}),
        (["frontend/package-lock.json"], {"frontend", "e2e"}),
        (["docs/development/quality-gates.md"], {"backend"}),
        (["README.md", "site/index.html", ".github/workflows/release.yml"], set()),
        # Parity fixtures the backend suite reads from the frontend tree.
        (["frontend/src/lib/views/__fixtures__/default-view-specs.json"], ALL),
        (["frontend/src/lib/viewGrammar.generated.ts"], ALL),
        # The gate machinery itself.
        ([".github/workflows/gates.yml"], ALL),
        (["scripts/ci_changed_areas.py"], ALL),
        (["spec/selector-eval-corpus.json"], ALL),
        ([".claude/hooks/check_edited_file.py"], ALL),
    ],
)
def test_paths_map_to_the_jobs_that_can_see_them(paths, expected):
    assert ci.changed_areas(paths) == expected


def test_an_unmapped_path_runs_everything():
    assert ci.changed_areas(["somewhere-new/file.txt"]) == ALL


def test_a_prefix_only_matches_a_whole_directory():
    # `backend/` must not swallow a sibling like `backend-tools/`.
    assert ci.areas_for_path("backend-tools/x.py") == ci.EVERYTHING


def test_an_empty_diff_runs_everything():
    assert ci.changed_areas([]) == ALL
    assert ci.changed_areas(["", "  "]) == ALL


def test_every_tracked_file_is_mapped_by_a_rule():
    """Fail-open covers a new path at runtime; this makes someone map it."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    unmapped = sorted(
        {
            p.split("/")[0]
            for p in tracked
            if not any(
                p == prefix or (prefix.endswith("/") and p.startswith(prefix))
                for prefix, _ in ci.RULES
            )
        }
    )
    assert unmapped == []


def test_main_writes_one_github_output_line_per_area():
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ci_changed_areas.py")],
        input="frontend/src/App.svelte\n",
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.splitlines() == ["backend=false", "frontend=true", "e2e=true"]

