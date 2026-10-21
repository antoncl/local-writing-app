#!/usr/bin/env python3
"""AI-call flush guard — every frontend call that makes the backend run a model
over project files must persist the author's pending editor edits first (#2598).

Why this earns a gate: the backend renders what a model call reads (the scene,
`use()` picks, lore) from disk, and an editor pane autosaves only after 6s idle.
A call made inside that window silently carries the previous saved version of
what the author is looking at (#2587, #2596). Nothing at runtime notices; the
model just answers about stale text. #2596 existed only because #2587 had fixed
one entry point, and the next new call would regress the same way, so the rule
is pinned here rather than remembered.

The rule, per call site of a model-calling API method (`MODEL_CALLS`):
  * a flush (`FLUSH_CALLS`) runs within the `WINDOW` lines above the call, or
  * an `ai-flush: <reason>` marker comment sits on the call line or one of the
    `MARKER_REACH` lines above it, saying where the flush happens instead (the
    caller that persists before reaching this code, e.g. `sendChat` before
    `streamAssistantReply`).
A marker is a reasoned pointer, not an exemption list: it lives at the call it
explains, a reviewer reads it in the diff, and a bare `ai-flush:` with no reason
fails. A gate can't prove the flush really happens on every path; it makes
each call site decide out loud.

`MODEL_CALLS` is the set of `api` methods whose endpoint runs a provider call
over project files. Previews, estimates and health checks call no model (or read
no project file) and are deliberately absent. Add a method here when you add one
to `lib/api/`. `test_gate_invariants.py` fails if a listed name no longer exists
on the client.

FAILS (exit 1) on any unsatisfied call. Files outside `frontend/src/`, the API
client itself (`lib/api.ts`, `lib/api/`) and test files are ignored, so it is safe
to hand this the staged-file list, a single edited file, or the whole tree.

Usage:
    python scripts/check_ai_call_flush.py <file> [<file> ...]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MODEL_CALLS = (
    "aiChat",
    "aiChatStream",
    "aiGenerateStream",
    "extractEntryPatch",
    "extractEntryDraft",
    "extractFlags",
)
FLUSH_CALLS = ("flushBeforeAICall", "flushBeforeSceneRewrite", "persistEdits")
WINDOW = 25
MARKER_REACH = 3

CLIENT = "frontend/src/lib/api.ts"
CLIENT_DIR = "frontend/src/lib/api/"
TEST_MARKERS = (".test.", ".spec.", "frontend/src/lib/test/")

CALL_RE = re.compile(r"\bapi\s*\.\s*(" + "|".join(MODEL_CALLS) + r")\s*\(")
FLUSH_RE = re.compile(r"\b(?:" + "|".join(FLUSH_CALLS) + r")\s*(?:\?\.)?\s*\(")
# The reason must say something: at least a few word characters after the colon.
MARKER_RE = re.compile(r"ai-flush:\s*\S.{4,}")


def strip_comments(text: str) -> str:
    """Blank out // and /* */ comments, preserving newlines so line numbers hold.
    A call or a flush named in a comment is documentation, not code."""
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def is_checked(path: Path) -> bool:
    posix = f"/{path.as_posix()}"
    if "/frontend/src/" not in posix:
        return False
    if path.suffix not in {".ts", ".js", ".svelte"}:
        return False
    if posix.endswith(f"/{CLIENT}") or f"/{CLIENT_DIR}" in posix:
        return False
    return not any(marker in posix for marker in TEST_MARKERS)


def check_text(text: str) -> list[tuple[int, str]]:
    """(line, method) for every model call with neither a nearby flush nor a marker."""
    raw_lines = text.splitlines()
    code = strip_comments(text)
    code_lines = code.splitlines()
    misses: list[tuple[int, str]] = []
    for match in CALL_RE.finditer(code):
        line = code.count("\n", 0, match.start())  # 0-based
        above = code_lines[max(0, line - WINDOW) : line + 1]
        if any(FLUSH_RE.search(candidate) for candidate in above):
            continue
        reach = raw_lines[max(0, line - MARKER_REACH) : line + 1]
        if any(MARKER_RE.search(candidate) for candidate in reach):
            continue
        misses.append((line + 1, match.group(1)))
    return misses


def main(argv: list[str]) -> int:
    failed = False
    for raw in argv:
        path = Path(raw)
        if not is_checked(path) or not path.is_file():
            continue
        for line_no, method in check_text(path.read_text(encoding="utf-8", errors="replace")):
            failed = True
            print(
                f"FAIL  {path.as_posix()}:{line_no}: api.{method}() with no pending-edits flush - "
                f"call editorPanes.flushBeforeAICall() first, or mark where it happens "
                f"with `// ai-flush: <reason>`"
            )
    if failed:
        print("A model call reads project files from disk; persist what the author sees first (#2587, #2596, #2598).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
