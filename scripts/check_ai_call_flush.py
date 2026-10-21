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

What is watched — derived, and fail-closed: every method of the API client
(`frontend/src/lib/api/*.ts`) whose route is under `/ai/` counts as a model call,
EXCEPT the ones listed in `NON_MODEL` with the reason they call no model over
project files. A new `/ai/` method is therefore watched the day it is added; only
a deliberate, reasoned entry here unwatches it. (Every route that calls a
provider lives in `routers/ai.py`, i.e. under `/ai/`; `test_gate_invariants.py`
pins that, so the derivation's premise can't silently rot.)

The rule, per call site of a watched method:
  * a flush (`FLUSH_CALLS`) runs within the `WINDOW` lines above the call, or
  * an `ai-flush: <reason>` comment sits on the call line or in the comment block
    directly above it (no code or blank line in between), saying where the flush
    happens instead — e.g. the caller that persists before reaching this code.
    A marker covers only the call directly below it, and a bare `ai-flush:` with
    no reason fails. It is a reasoned pointer a reviewer reads in the diff, not an
    exemption list.

Comments and string/template-literal contents are told apart from code by a small
lexer, so a call or a flush that only appears in a comment or a string is neither
a violation nor a flush, and `//` inside "http://" is not a comment.

Known limits (accepted; a gate makes each call site decide out loud, it does not
prove the flush runs on every path):
  * Only the literal `api.<method>(` spelling is seen. A method destructured or
    aliased off `api`, called through brackets, or passed as a reference and
    called elsewhere (an injected dep) is invisible. Call the client directly.
  * The flush window is textual: a flush in a neighbouring function within
    `WINDOW` lines satisfies a call that never flushes. Keep the flush next to
    the call, or mark where it really happens.
  * The lexer doesn't know regex literals (`/\\/*/` reads as a comment opener) or
    Svelte markup (an apostrophe in markup text reads as a string to end of line).
    Neither shape carries an `api.` model call in practice.

FAILS (exit 1) on any unsatisfied call. Files outside `frontend/src/`, the API
client itself (`lib/api.ts`, `lib/api/`) and test files are ignored, so it is safe
to hand this the staged-file list, a single edited file, or the whole tree.

Usage:
    python scripts/check_ai_call_flush.py <file> [<file> ...]
"""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API_DIR = REPO / "frontend" / "src" / "lib" / "api"

# `/ai/` methods that call no model over project files — each with its reason.
NON_MODEL: dict[str, str] = {
    "listAIProviders": "lists the configured providers",
    "listAIProviderModels": "lists a provider's model catalogue",
    "resolveAIProviderTier": "maps a tier name to a model id",
    "aiHealth": "a provider reachability ping that reads no project file",
    "checkOllamaHost": "an Ollama reachability ping",
    "refreshPrices": "refreshes the cached price table",
    "aiPreview": "renders the template for the preview and estimates; calls no model",
    "aiContextPreset": "builds a context preset; calls no model",
    "aiAppendInvocation": "writes an invocation-ledger row",
    "aiListInvocations": "reads the invocation ledger",
    "aiCostSummary": "sums the invocation ledger",
}
FLUSH_CALLS = ("flushBeforeAICall", "flushBeforeSceneRewrite", "persistEdits")
WINDOW = 25

CLIENT = "frontend/src/lib/api.ts"
CLIENT_DIR = "frontend/src/lib/api/"
TEST_MARKERS = (".test.", ".spec.", "frontend/src/lib/test/")

# A client method header at object-literal depth (two-space indent) — the shape
# every method in lib/api/*.ts has.
METHOD_RE = re.compile(r"^  ([a-zA-Z]\w*)\s*\(", re.MULTILINE)
AI_ROUTE_RE = re.compile(r"[`'\"]/ai/")
FLUSH_RE = re.compile(r"\b(?:" + "|".join(FLUSH_CALLS) + r")\s*(?:\?\.)?\s*\(")
# The reason must say something: at least a few characters after the colon.
MARKER_RE = re.compile(r"ai-flush:\s*\S.{4,}")


def ai_route_methods(api_dir: Path = API_DIR) -> set[str]:
    """Every client method whose body names a route under `/ai/`."""
    found: set[str] = set()
    for path in sorted(api_dir.glob("*.ts")):
        text = path.read_text(encoding="utf-8")
        headers = list(METHOD_RE.finditer(text))
        for index, header in enumerate(headers):
            end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
            if AI_ROUTE_RE.search(text, header.end(), end):
                found.add(header.group(1))
    return found


def model_calls(api_dir: Path = API_DIR) -> frozenset[str]:
    """The watched set: `/ai/` methods minus the reasoned non-model ones."""
    return frozenset(ai_route_methods(api_dir) - NON_MODEL.keys())


@lru_cache(maxsize=1)
def _call_re() -> re.Pattern[str]:
    names = sorted(model_calls(), key=len, reverse=True)
    if not names:  # fail closed: an unreadable client must not pass everything
        raise SystemExit(f"check_ai_call_flush: found no /ai/ methods under {API_DIR}")
    return re.compile(r"\bapi\s*\.\s*(" + "|".join(names) + r")\s*\(")


class _Lexer:
    """Splits JS/TS source into code and comments: one method per token kind,
    each taking the token's start index and returning the index after it."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.n = len(text)
        self.code = list(text)
        self.comments = ["\n" if ch == "\n" else " " for ch in text]
        self.template_depths: list[int] = []  # one brace depth per open `${`

    def run(self) -> tuple[str, str]:
        i = 0
        while i < self.n:
            ch, nxt = self.text[i], self.text[i + 1 : i + 2]
            if ch == "/" and nxt == "/":
                i = self._comment(i, self._line_end(i))
            elif ch == "/" and nxt == "*":
                i = self._comment(i, self._block_end(i))
            elif ch in "'\"":
                i = self._string(i)
            elif ch == "`" or self._closes_expression(ch):
                i = self._template(i)
            else:
                i = self._code(i)
        return "".join(self.code), "".join(self.comments)

    def _blank(self, start: int, end: int) -> None:
        for k in range(start, min(end, self.n)):
            if self.text[k] != "\n":
                self.code[k] = " "

    def _line_end(self, i: int) -> int:
        end = self.text.find("\n", i)
        return self.n if end < 0 else end

    def _block_end(self, i: int) -> int:
        end = self.text.find("*/", i + 2)
        return self.n if end < 0 else end + 2

    def _comment(self, start: int, end: int) -> int:
        for k in range(start, end):
            self.comments[k] = self.text[k]
        self._blank(start, end)
        return end

    def _string(self, i: int) -> int:
        quote, j = self.text[i], i + 1
        while j < self.n and self.text[j] not in (quote, "\n"):
            j += 2 if self.text[j] == "\\" else 1
        self._blank(i + 1, j)
        return j + 1

    def _closes_expression(self, ch: str) -> bool:
        """A `}` that ends a template literal's `${...}` resumes the literal."""
        return ch == "}" and bool(self.template_depths) and self.template_depths[-1] == 0

    def _template(self, i: int) -> int:
        """From an opening backtick, or the `}` closing a `${...}`: blank the
        literal text up to the closing backtick or the next `${`."""
        if self.text[i] == "}":
            self.template_depths.pop()
        j = i + 1
        while j < self.n and self.text[j] != "`" and self.text[j : j + 2] != "${":
            j += 2 if self.text[j] == "\\" else 1
        self._blank(i + 1, j)
        if self.text[j : j + 2] == "${":
            self.template_depths.append(0)
            return j + 2
        return j + 1

    def _code(self, i: int) -> int:
        if self.template_depths and self.text[i] in "{}":
            self.template_depths[-1] += 1 if self.text[i] == "{" else -1
        return i + 1


def split_source(text: str) -> tuple[str, str]:
    """(code, comments), each as long as `text` with newlines kept. `code` has
    comments and string/template-literal contents blanked; `comments` holds only
    comment text. `${...}` inside a template literal stays code."""
    return _Lexer(text).run()


def is_checked(path: Path) -> bool:
    posix = f"/{path.as_posix()}"
    if "/frontend/src/" not in posix:
        return False
    if path.suffix not in {".ts", ".js", ".svelte"}:
        return False
    if posix.endswith(f"/{CLIENT}") or f"/{CLIENT_DIR}" in posix:
        return False
    return not any(marker in posix for marker in TEST_MARKERS)


def _marked(code_lines: list[str], comment_lines: list[str], line: int) -> bool:
    """A reasoned marker on the call line, or in the comment block directly above."""
    if MARKER_RE.search(comment_lines[line]):
        return True
    k = line - 1
    while k >= 0 and not code_lines[k].strip() and comment_lines[k].strip():
        if MARKER_RE.search(comment_lines[k]):
            return True
        k -= 1
    return False


def check_text(text: str) -> list[tuple[int, str]]:
    """(line, method) for every watched call with neither a nearby flush nor a marker."""
    code, comments = split_source(text)
    code_lines, comment_lines = code.splitlines(), comments.splitlines()
    misses: list[tuple[int, str]] = []
    for match in _call_re().finditer(code):
        line = code.count("\n", 0, match.start())  # 0-based
        if any(FLUSH_RE.search(candidate) for candidate in code_lines[max(0, line - WINDOW) : line + 1]):
            continue
        if _marked(code_lines, comment_lines, line):
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
                f"with `// ai-flush: <reason>` directly above the call"
            )
    if failed:
        print("A model call reads project files from disk; persist what the author sees first (#2587, #2596, #2598).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
