#!/usr/bin/env python3
"""Runes guard — the frontend is on idiomatic Svelte 5 runes (#49), and this
locks in the one legacy construct that is a true Svelte *deprecation*:
`createEventDispatcher`. Svelte 5 deprecates it and Svelte 6 removes it; the #49
pass replaced every component event dispatcher with callback props (`onX`). This
gate stops one from creeping back — a cold session reaching for the Svelte-4
pattern it knows, which `svelte-check` does NOT flag (verified: a component using
`createEventDispatcher` compiles with zero warnings, even at `--threshold
warning`), so nothing else catches the regression.

Why a guard and not `svelte-check`: `createEventDispatcher` is deprecated at the
*API* level, not the compiler level — no warning code is emitted. And the repo
has no ESLint toolchain (which `svelte/no-*` rules would need). A small Python
guard is the repo idiom for exactly this kind of fitness gate (see
check_http_client.py, check_style_tokens.py) and costs no new dependency.

Scope, deliberately narrow: this bans `createEventDispatcher` only. The other
Svelte-4 constructs still present — `export let` (the two PlainTextEditor test
harnesses) and `on:` event directives (App, NodeEditor, a few transitional
edges into still-legacy children) — have legitimate remaining uses today, so
banning them now would throw false failures. Add them to PATTERNS once each
reaches zero across `frontend/src`.

FAILS (exit 1) on any `createEventDispatcher` in a `frontend/src` `.svelte` file
— there is no per-file exemption (#1681). Files outside `frontend/src/`,
non-svelte files, and test files are ignored, so it is safe to hand this the full
staged list, one edited file, or the whole tree.

Usage:
    python scripts/check_svelte_runes.py <file> [<file> ...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TEST_MARKERS = (".test.", ".spec.", "frontend/src/lib/test/")

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bcreateEventDispatcher\b"),
        "createEventDispatcher is deprecated (removed in Svelte 6) - "
        "use a callback prop (onX) instead",
    ),
]


def strip_comments(text: str) -> str:
    """Blank out // and /* */ comments, preserving newlines so line numbers hold.
    A pattern token inside a comment is documentation, not code (e.g. the
    MetadataPanel comment that names createEventDispatcher)."""
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def is_checked(path: Path) -> bool:
    posix = f"/{path.as_posix()}"
    if "/frontend/src/" not in posix:
        return False
    if path.suffix != ".svelte":
        return False
    return not any(marker in posix for marker in TEST_MARKERS)


def check_file(path: Path) -> list[tuple[int, str]]:
    """(line, label) for every banned construct in the file."""
    text = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    hits: list[tuple[int, str]] = []
    for pattern, label in PATTERNS:
        for match in pattern.finditer(text):
            hits.append((text.count("\n", 0, match.start()) + 1, label))
    return sorted(hits)


def main(argv: list[str]) -> int:
    failed = False
    for raw in argv:
        path = Path(raw)
        if not is_checked(path) or not path.is_file():
            continue
        hits = check_file(path)
        if not hits:
            continue
        rel = path.as_posix()
        failed = True
        for line_no, label in hits:
            print(f"FAIL  {rel}:{line_no}: {label}")
    if failed:
        print("The frontend is on Svelte 5 runes (#49). Component events use callback props, not createEventDispatcher.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
