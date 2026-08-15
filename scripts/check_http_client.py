#!/usr/bin/env python3
"""HTTP-client guard — the frontend talks to the backend through exactly one
module, `frontend/src/lib/api.ts` (ADR-0056, #977). This is a *fitness gate*,
the fallback for a boundary that cannot be a single runtime choke point.

Why this boundary earns a gate (ADR-0056 §5 — blast radius of a silent breach):
every request must carry the open project's scope, injected in one place. Since
#413 the scope rides the wire as headers built by `api.ts` (`scopeHeaders`); a
raw `fetch` from a component or store skips that injection and talks to the
*wrong project* — a data-corrupting bug that is completely invisible to an
author who does not read the code. That is precisely the case the ADR says to
gate. `api.ts` itself is the sanctioned client and is exempt.

What counts as a raw network call:
  * `new EventSource(...)`, `new WebSocket(...)`, `new XMLHttpRequest(...)`
  * `navigator.sendBeacon(...)`
  * `window.fetch(...)` / `globalThis.fetch(...)` (explicit global)
  * `fetch(` with a URL-shaped first argument — a template literal, or a string
    starting with `/` or `http`. This is what a real call looks like
    (`fetch(`${baseUrl}${path}`, …)`).
  * importing `axios` (reaching for a second HTTP client)

The URL-shaped requirement is deliberate: the frontend has a legitimate local
callback *named* `fetch` (`editorPanes.#openEntryDocument(…, fetch, …)`, invoked
as `fetch(id)`), and matching a bare `fetch(` would false-positive on it. Keying
on a URL-shaped literal argument distinguishes the network call from the
callback. The trade-off: `fetch(url)` where `url` is a variable is not caught —
accepted, because the failure mode this guards against is the *accidental*
`fetch(`/api/…`)` a cold session hardcodes at a component, which always carries
a literal URL at the call site. A local callback named `fetch` that is ever
invoked with a literal URL string would false-positive; grandfather or rename it.

FAILS (exit 1) on any raw call unless the file is grandfathered below. Files
outside `frontend/src/`, `api.ts`, and test files are ignored, so it is safe to
hand this the full staged-file list, a single edited file, or the whole tree.

Usage:
    python scripts/check_http_client.py <file> [<file> ...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Files exempt from the boundary, matched against the path tail (repo-relative,
# forward slashes). Empty and meant to stay empty: only api.ts makes network
# calls today. Add an entry only for a deliberate, PR-announced exception —
# growth is ratcheted by scripts/check_exemptions.py.
GRANDFATHERED: set[str] = set()

# The sanctioned client, and the test surfaces that are not the production
# boundary (tests may stub globals). Tail-matched.
CLIENT = "frontend/src/lib/api.ts"
TEST_MARKERS = (".test.", ".spec.", "frontend/src/lib/test/")

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bnew\s+(?:EventSource|WebSocket|XMLHttpRequest)\s*\("), "raw network primitive"),
    (re.compile(r"\bnavigator\s*\.\s*sendBeacon\s*\("), "navigator.sendBeacon"),
    (re.compile(r"\b(?:window|globalThis)\s*\.\s*fetch\s*\("), "window.fetch"),
    # bare fetch( with a URL-shaped literal: backtick template, or a quote then
    # `/` or `http`. Lookbehind so `obj.fetch(` / `myfetch(` don't match here.
    (re.compile(r"(?<![.\w])fetch\s*\(\s*(?:`|['\"](?:/|https?:))"), "raw fetch() to a URL"),
    (re.compile(r"""(?:from\s+['"]axios['"]|require\(\s*['"]axios['"]|import\s+axios\b)"""), "axios import"),
]


def strip_comments(text: str) -> str:
    """Blank out // and /* */ comments, preserving newlines so line numbers hold.
    A pattern token inside a comment is documentation, not a call."""
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def is_checked(path: Path) -> bool:
    posix = f"/{path.as_posix()}"
    if "/frontend/src/" not in posix:
        return False
    if path.suffix not in {".ts", ".js", ".svelte"}:
        return False
    if posix.endswith(f"/{CLIENT}"):
        return False
    return not any(marker in posix for marker in TEST_MARKERS)


def check_file(path: Path) -> list[tuple[int, str]]:
    """(line, label) for every raw network call in the file."""
    text = strip_comments(path.read_text(encoding="utf-8", errors="replace"))
    hits: list[tuple[int, str]] = []
    for pattern, label in PATTERNS:
        for match in pattern.finditer(text):
            hits.append((text.count("\n", 0, match.start()) + 1, label))
    return sorted(hits)


def is_grandfathered(posix_path: str) -> bool:
    return any(posix_path.endswith(entry) for entry in GRANDFATHERED)


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
        if is_grandfathered(rel):
            print(f"warn  {rel}: {len(hits)} raw network call(s) (grandfathered - clean up when you next work here).")
            continue
        failed = True
        for line_no, label in hits:
            print(f"FAIL  {rel}:{line_no}: {label} - route it through lib/api.ts")
    if failed:
        print("All backend I/O goes through lib/api.ts, the one client that injects project scope (ADR-0056, #413).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
