"""The pure positional name matcher for implicit-context detection.

This is the backend half of ADR-0075 §3 — the Python mirror of the frontend's
`implicitContextMatcher.ts`. It is intentionally free of any project/scene
plumbing: given `(entry_id, [names])` pairs and a text, it returns positional
hits. `lore_selection._alias_match` layers policy filtering and effective-name
resolution on top; the §5 parity gate drives THESE functions directly against
the shared corpus, exactly as the vitest suite drives `compileMatcher`.

Parity is load-bearing, so the semantics here must stay identical to the
frontend's:

- **Longest match wins.** Refs are sorted `(-len(name), norm(name), entry_id)`
  before dedup — a total order independent of input order — so the
  alternation tries the longest candidate first at each start (maximal
  munch — regex alternation is otherwise leftmost-*first*, not
  leftmost-longest), and equal-length collisions resolve deterministically
  instead of on input order (§3 rule; the F1 tie-break).
- **Dedup by `norm(name)`, first-id-wins**, over that sorted order — the same
  order of operations as the frontend.
- **Space and hyphen are one separator; fusion is not.** A name's internal
  `[\\s-]+` run compiles to `[\\s-]+` in the fragment, so "Code Warrior"
  matches "code-warrior" but not "codewarrior" (§3 rule 4). `norm()` is the
  shared key for both the dedup/lookup map and the scan-time lookup, since
  matched text can now differ from the stored name.
- **A possessive/enclitic attaches, not part of the hit.** An optional,
  non-captured `'ll`/`'re`/`'ve`/`'s`/`'d`/`'` trails the name before the real
  boundary; the reported hit covers only the name capture group (§3 rule 3).
- **The boundary uses the explicit ASCII class `[A-Za-z0-9_']`, NOT `\\w`.**
  Python's `\\w` is Unicode by default and would diverge from JS's ASCII `\\w`,
  so non-ASCII characters must act as boundaries identically on both sides.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import NamedTuple

_SEPARATOR_RE = re.compile(r"[\s-]+")
_CLITIC = r"(?:'ll|'re|'ve|'s|'d|')?"
_BOUNDARY_LEFT = r"(?<![A-Za-z0-9_'])"
_BOUNDARY_RIGHT = r"(?![A-Za-z0-9_'])"


class NameMatch(NamedTuple):
    start: int
    end: int
    entry_id: str
    matched_text: str


class CompiledNameMatcher(NamedTuple):
    regex: re.Pattern[str]
    name_to_id: dict[str, str]


def _norm(name: str) -> str:
    """Collapse space/hyphen runs to a single ASCII space, strip, lowercase —
    the shared dedup/lookup key (§3 rule 4)."""
    return _SEPARATOR_RE.sub(" ", name).strip().lower()


def _build_fragment(name: str) -> str:
    """Split on `[\\s-]+`, escape each token, rejoin with `[\\s-]+` so space
    and hyphen are interchangeable in the compiled fragment (§3 rule 4);
    single-word names are unchanged."""
    tokens = [t for t in _SEPARATOR_RE.split(name) if t]
    return r"[\s\-]+".join(re.escape(t) for t in tokens).lower()


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
    refs.sort(key=lambda r: (-len(r[0]), _norm(r[0]), r[1]))

    name_to_id: dict[str, str] = {}
    fragments: list[str] = []
    for name, entry_id in refs:
        key = _norm(name)
        if key in name_to_id:
            continue
        name_to_id[key] = entry_id
        fragments.append(_build_fragment(name))

    if not name_to_id:
        return CompiledNameMatcher(regex=re.compile(r"(?!)"), name_to_id=name_to_id)

    src = _BOUNDARY_LEFT + "(" + "|".join(fragments) + ")" + _CLITIC + _BOUNDARY_RIGHT
    regex = re.compile(src, re.IGNORECASE)
    return CompiledNameMatcher(regex=regex, name_to_id=name_to_id)


def scan_name_matcher(matcher: CompiledNameMatcher, text: str) -> list[NameMatch]:
    """Run a compiled matcher over `text`, returning positional hits in original
    casing (the §3 core: longest-match, case-fold, apostrophe-aware boundary,
    possessive-attach). The hit covers the name capture group only — a
    trailing possessive/enclitic is consumed by the match but excluded from
    the reported span."""
    if not text:
        return []
    hits: list[NameMatch] = []
    for m in matcher.regex.finditer(text):
        matched = m.group(1)
        entry_id = matcher.name_to_id.get(_norm(matched))
        if not entry_id:
            continue
        hits.append(NameMatch(start=m.start(1), end=m.end(1), entry_id=entry_id, matched_text=matched))
    return hits
