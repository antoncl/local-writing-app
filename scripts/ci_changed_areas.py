#!/usr/bin/env python3
"""Changed-area classifier — which gates.yml jobs a PR's files can affect.

Every PR used to pay for all four required jobs whatever it touched: a change to
two prompt Markdown files ran svelte-check, the build, vitest and the browser
smoke in full. This maps each changed path to the areas whose jobs can see it,
and gates.yml skips a job whose area is untouched. A job skipped by its `if`
reports as passed, so the four required checks still always report.

The mapping is **fail-open**: a path that matches no rule runs everything, and
so does a change to the gate machinery itself (this script, the workflow, the
shared corpora both runtimes test against). The cost of a wrong guess must be a
slower run, never a skipped job that should have gone red.

Areas (the `changes` job's outputs):
  * backend  — the pytest suite, on Linux and Windows. The `backend` job's lint
               and guard steps are cheap and repo-wide, so they always run.
  * frontend — svelte-check, the build and vitest.
  * e2e      — the browser smoke: the built bundle served by the real backend.

Reads changed paths from stdin, one per line; writes `area=true|false` lines to
stdout, ready to append to $GITHUB_OUTPUT. An empty list runs everything — an
empty diff is far likelier a broken `git diff` than a PR with no files.

Usage:
    git diff --name-only --no-renames HEAD^1 HEAD | python scripts/ci_changed_areas.py
"""

from __future__ import annotations

import sys

AREAS = ("backend", "frontend", "e2e")
EVERYTHING = frozenset(AREAS)
NOTHING: frozenset[str] = frozenset()

# First match wins, so a narrower prefix sits above the broader one it carves out
# of. A prefix ending in "/" matches a directory; anything else is an exact path.
RULES: tuple[tuple[str, frozenset[str]], ...] = (
    # The gate machinery: the workflow, the scripts it runs (and pytest tests),
    # the hooks pytest tests, the lint config and checkout line endings.
    (".github/workflows/gates.yml", EVERYTHING),
    ("scripts/", EVERYTHING),
    (".claude/", EVERYTHING),
    (".ruff.toml", EVERYTHING),
    (".pre-commit-config.yaml", EVERYTHING),
    (".gitattributes", EVERYTHING),
    # Corpora that pin the Python and TypeScript runtimes to each other.
    ("spec/", EVERYTHING),
    # Nothing in gates.yml reads these. Only these: anything else under
    # `.github/` (a local action gates.yml might use) falls through to everything.
    (".github/workflows/", NOTHING),
    (".github/pull_request_template.md", NOTHING),
    ("packaging/", NOTHING),
    ("site/", NOTHING),
    ("README.md", NOTHING),
    ("AGENTS.md", NOTHING),
    ("CLAUDE.md", NOTHING),
    ("LICENSE", NOTHING),
    (".gitignore", NOTHING),
    # Tests and the built-in prompt library reach no browser flow; pytest loads
    # and renders the library, the smoke never does.
    ("backend/tests/", frozenset({"backend"})),
    ("backend/app/builtin_library/", frozenset({"backend"})),
    ("backend/", frozenset({"backend", "e2e"})),
    # Guide and prompt-reference tests read the real docs.
    ("docs/", frozenset({"backend"})),
    # Frontend files the backend suite reads as parity fixtures, or regenerates
    # and compares (test_diff_fixtures_are_current).
    ("frontend/src/lib/views/__fixtures__/", EVERYTHING),
    ("frontend/src/lib/viewGrammar.generated.ts", EVERYTHING),
    ("frontend/src/lib/utils/diffRuns.fixtures.json", EVERYTHING),
    ("frontend/", frozenset({"frontend", "e2e"})),
)


def matches(path: str, prefix: str) -> bool:
    """A "/"-terminated prefix matches a whole directory; anything else, one path."""
    return path == prefix or (prefix.endswith("/") and path.startswith(prefix))


def areas_for_path(path: str) -> frozenset[str]:
    """The areas one changed path can affect; an unknown path affects them all."""
    for prefix, areas in RULES:
        if matches(path, prefix):
            return areas
    return EVERYTHING


def changed_areas(paths: list[str]) -> frozenset[str]:
    """The union over every changed path; no paths at all means everything."""
    paths = [p.strip() for p in paths if p.strip()]
    if not paths:
        return EVERYTHING
    hit: set[str] = set()
    for path in paths:
        hit |= areas_for_path(path)
    return frozenset(hit)


def main() -> int:
    hit = changed_areas(sys.stdin.read().splitlines())
    for area in AREAS:
        print(f"{area}={'true' if area in hit else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
