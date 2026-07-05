#!/usr/bin/env python3
"""Source-file size guard — the machine-enforced half of the "no monolithic
files" rule (CLAUDE.md). Counts raw lines and:

  * FAILS (exit 1) if any checked file is >= HARD_FAIL lines, unless it is
    explicitly grandfathered below.
  * WARNS (still exit 0) from WARN lines up, so growth toward the cap is
    visible before it blocks.

Only source extensions are inspected; any other path is ignored, so it is safe
to hand this the full staged-file list (pre-commit) or a single edited file
(the Claude Code PostToolUse hook). Paths may be absolute or repo-relative.

Usage:
    python scripts/check_file_size.py <file> [<file> ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

WARN = 1200
HARD_FAIL = 1500
EXTENSIONS = {".py", ".svelte", ".ts", ".tsx"}

# Files knowingly over the cap, exempt from the hard FAIL until a dedicated
# split. They still warn. Remove an entry once it is back under HARD_FAIL.
# Stored repo-relative with forward slashes; matched against the path tail.
GRANDFATHERED = {
    "backend/app/main.py",
    "backend/tests/test_metadata_validation.py",
    # Already at the cap before #116 tipped it over; the metadata models are
    # entangled with shared base types, so the split is tracked separately (#117).
    "backend/app/models.py",
}


def line_count(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def is_grandfathered(posix_path: str) -> bool:
    return any(posix_path.endswith(entry) for entry in GRANDFATHERED)


def main(argv: list[str]) -> int:
    failed = False
    for raw in argv:
        path = Path(raw)
        if path.suffix not in EXTENSIONS or not path.is_file():
            continue
        rel = path.as_posix()
        count = line_count(path)
        if count >= HARD_FAIL and not is_grandfathered(rel):
            print(f"FAIL  {rel}: {count} lines (cap {HARD_FAIL}) - split before committing.")
            failed = True
        elif count >= HARD_FAIL:
            print(f"warn  {rel}: {count} lines (over {HARD_FAIL}, grandfathered - split when you next work here).")
        elif count >= WARN:
            print(f"warn  {rel}: {count} lines (approaching the {HARD_FAIL}-line cap).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
