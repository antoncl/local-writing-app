"""The pure positional name matcher for implicit-context detection.

This is the backend half of ADR-0075 §3 — the Python mirror of the frontend's
`implicitContextMatcher.ts`. It is intentionally free of any project/scene
plumbing: given `(entry_id, [names])` pairs and a text, it returns positional
hits. `helpers._alias_match` layers policy filtering and effective-name
resolution on top; the §5 parity gate drives THESE functions directly against
the shared corpus, exactly as the vitest suite drives `compileMatcher`.

Parity is load-bearing, so the semantics here must stay identical to the
frontend's:

- **Longest match wins.** Refs are stable-sorted name-length DESCENDING before
  dedup, so the alternation tries the longest candidate first at each start
  (maximal munch — regex alternation is otherwise leftmost-*first*, not
  leftmost-longest).
- **Dedup by `name.lower()`, first-id-wins**, over that sorted order — the same
  order of operations as the frontend (sort, then dedup).
- **The boundary uses the explicit ASCII class `[A-Za-z0-9_']`, NOT `\\w`.**
  Python's `\\w` is Unicode by default and would diverge from JS's ASCII `\\w`,
  so non-ASCII characters must act as boundaries identically on both sides.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import NamedTuple


class NameMatch(NamedTuple):
    start: int
    end: int
    entry_id: str
    matched_text: str


class CompiledNameMatcher(NamedTuple):
    regex: re.Pattern[str]
    name_to_id: dict[str, str]


def compile_name_matcher(entries: Iterable[tuple[str, list[str]]]) -> CompiledNameMatcher:
    """Compile a positional, longest-match regex-OR over `(entry_id, [names])`
    pairs (title first, then aliases in order) — the pure §3 matcher mirrored
    from `implicitContextMatcher.ts`'s `compileMatcher`."""
    refs: list[tuple[str, str]] = []
    for entry_id, names in entries:
        for name in names:
            name = (name or "").strip()
            if name:
                refs.append((name, entry_id))
    refs.sort(key=lambda r: len(r[0]), reverse=True)

    name_to_id: dict[str, str] = {}
    for name, entry_id in refs:
        key = name.lower()
        if key not in name_to_id:
            name_to_id[key] = entry_id

    if not name_to_id:
        return CompiledNameMatcher(regex=re.compile(r"(?!)"), name_to_id=name_to_id)

    escaped = [re.escape(n) for n in name_to_id]
    src = r"(?<![A-Za-z0-9_'])(" + "|".join(escaped) + r")(?![A-Za-z0-9_'])"
    regex = re.compile(src, re.IGNORECASE)
    return CompiledNameMatcher(regex=regex, name_to_id=name_to_id)


def scan_name_matcher(matcher: CompiledNameMatcher, text: str) -> list[NameMatch]:
    """Run a compiled matcher over `text`, returning positional hits in original
    casing (the §3 core: longest-match, case-fold, apostrophe-aware boundary)."""
    if not text:
        return []
    hits: list[NameMatch] = []
    for m in matcher.regex.finditer(text):
        matched = m.group(1)
        entry_id = matcher.name_to_id.get(matched.lower())
        if not entry_id:
            continue
        hits.append(NameMatch(start=m.start(), end=m.end(), entry_id=entry_id, matched_text=matched))
    return hits
