#!/usr/bin/env python3
"""Guard the memory index: it may shrink, never grow.

`MEMORY.md` is loaded into every request of every session, so its size is paid
on every model step — at the time of writing, ~24 steps per user prompt. It has
no natural shrinking force: every session may add a memory, none removes one.
That is the same shape as the exemption ratchet (`scripts/check_exemptions.py`),
and it gets the same treatment — a high-water mark that only ever moves down.

Lower `MAX_BYTES` whenever a consolidation pass gets the file under it. Never
raise it: if a new memory does not fit, the answer is to merge or retire an old
one, which is the maintenance the file otherwise never receives.

The index is meant to be *pointers*, one line per memory, with the content in
the memo files. Prose that accumulates in the index is content in the wrong
place — it is paid on every step instead of being read on demand.

Usage:
    python scripts/check_memory_index.py --memory-dir <dir>
    python scripts/check_memory_index.py <path/to/MEMORY.md>

Exits 1 when a rule is violated, 0 otherwise. Output is deliberately terse: it
is injected into the session that triggered it, and a guard against context
bloat must not itself become context bloat.
"""

from __future__ import annotations

import argparse
import contextlib
import re
import sys
from pathlib import Path

# High-water mark. Ratchet DOWN after a consolidation pass; never up.
# Provisional: set just above the size at the time this guard landed, so it
# does not fire on day one. The consolidation pass that follows should drop it
# to whatever the trimmed file measures.
MAX_BYTES = 17_200

# A pointer line is one memory: a link, then a short hook. Anything longer has
# started summarising the memo instead of pointing at it.
MAX_POINTER_CHARS = 140

# The same ratchet applied to the structural rules. Both are already violated
# today (the index carries inline prose, and most hooks have grown into
# summaries), so an absolute rule would fire on every memory write and be
# tuned out within a day. Instead the counts may fall and never rise, which
# makes the guard silent until something gets worse. Ratchet these down after
# a consolidation pass too.
MAX_CONTENT_LINES = 8
MAX_LONG_POINTERS = 44

POINTER = re.compile(r"^\s*[-*]\s*\[[^\]]+\]\(([^)]+\.md)\)")
# Structural lines that legitimately are not pointers.
STRUCTURAL = re.compile(r"^\s*(#|$|<!--)")

MAX_EXAMPLES = 3


def check(index: Path) -> list[str]:
    text = index.read_text(encoding="utf-8", errors="replace")
    size = len(text.encode("utf-8"))
    problems: list[str] = []

    if size > MAX_BYTES:
        problems.append(
            f"MEMORY.md is {size:,} bytes, over the {MAX_BYTES:,} ratchet by "
            f"{size - MAX_BYTES:,}. Merge or retire a memory rather than raising the cap."
        )

    long_pointers: list[str] = []
    content_lines: list[str] = []
    dangling: list[str] = []

    for line in text.splitlines():
        match = POINTER.match(line)
        if match:
            if len(line) > MAX_POINTER_CHARS:
                long_pointers.append(line.strip()[:70])
            target = index.parent / match.group(1)
            if not target.exists():
                dangling.append(match.group(1))
        elif not STRUCTURAL.match(line):
            content_lines.append(line.strip()[:70])

    def summarise(items: list[str], budget: int, label: str) -> None:
        """Report only when a count exceeds its ratchet, with one example."""
        if len(items) <= budget:
            return
        example = items[0] if items else ""
        over = f"{len(items)} (was {budget})"
        problems.append(f"{label}: {over} — e.g. {example}")

    # A dangling pointer is a correctness bug, not a budget: no ratchet.
    summarise(dangling, 0, "pointer(s) to a missing memo")
    summarise(content_lines, MAX_CONTENT_LINES, "non-pointer line(s); content belongs in a memo")
    summarise(long_pointers, MAX_LONG_POINTERS, f"pointer(s) over {MAX_POINTER_CHARS} chars")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", nargs="?", help="path to MEMORY.md")
    parser.add_argument("--memory-dir", help="directory containing MEMORY.md")
    args = parser.parse_args()

    if args.memory_dir:
        index = Path(args.memory_dir) / "MEMORY.md"
    elif args.index:
        index = Path(args.index)
    else:
        parser.error("give a path to MEMORY.md or --memory-dir")

    if not index.is_file():
        return 0  # nothing to guard; never fail for a missing memory dir

    problems = check(index)
    if not problems:
        return 0
    # Memory files carry emoji and typographic dashes, and this runs on a
    # Windows console that defaults to cp1252 — echoing an offending line back
    # must not raise UnicodeEncodeError inside the guard.
    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(errors="replace")
    print("memory index:")
    for problem in problems:
        print(f"  - {problem}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
