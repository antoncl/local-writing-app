#!/usr/bin/env python
"""One parser for the prompt vocabulary documented in ``docs/prompts/reference.md``.

Both the drift gate (``check_prompt_vocab_docs.py``) and the manifest generator
(``gen_prompt_vocab.py``) read the vocabulary through here — a single parser, so
the two can never disagree about what the reference says. Adding a second
independent parse of the reference would reintroduce the very duplication this
cluster (#1270) exists to remove.

The reference is four markdown tables — Variables, Helpers, Filters, Tags. Each
data row's first column is a code span (the name/signature); the second is a
one-line summary. ``### `` subsections (the Field-contract subtable) stay inside
their parent section.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[1]
REFERENCE = REPO / "docs" / "prompts" / "reference.md"

_KIND_RANK = {"variable": 0, "helper": 1, "filter": 2, "tag": 3}


class Symbol(NamedTuple):
    """One documented vocabulary symbol."""

    name: str  # the identifier a template author types
    kind: str  # "variable" | "helper" | "filter" | "tag"
    signature: str  # display / insertion form, e.g. `entry(x, at=scene)`
    summary: str  # the one-line description from reference.md


def load_reference() -> str:
    return REFERENCE.read_text(encoding="utf-8")


def _section(md: str, header: str) -> str:
    """Text under a ``## Header`` up to the next top-level ``## `` heading."""
    start = md.find(header)
    if start == -1:
        return ""
    rest = md[start + len(header) :]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _split_row(line: str) -> list[str]:
    """Split a markdown table row into cells, honouring ``\\|`` and code spans."""
    line = line.strip().strip("|")
    cells: list[str] = []
    buf: list[str] = []
    in_code = False
    prev = ""
    for ch in line:
        if ch == "`":
            in_code = not in_code
            buf.append(ch)
        elif ch == "|" and not in_code and prev != "\\":
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        prev = ch
    cells.append("".join(buf).strip())
    return cells


def _data_rows(section: str) -> list[list[str]]:
    """Table rows whose first cell is a code span (skips header/separator/prose)."""
    rows: list[list[str]] = []
    for line in section.splitlines():
        if line.lstrip().startswith("|"):
            cells = _split_row(line)
            if cells and cells[0].startswith("`"):
                rows.append(cells)
    return rows


def _code(cell: str) -> str:
    """The first backtick-span's content, with markdown pipe-escapes undone."""
    match = re.match(r"`([^`]*)`", cell)
    return (match.group(1) if match else cell).replace("\\|", "|")


def _summary(cells: list[str]) -> str:
    return cells[1] if len(cells) > 1 else ""


def _parse_variables(md: str) -> list[Symbol]:
    out: list[Symbol] = []
    for cells in _data_rows(_section(md, "## Variables")):
        for token in re.findall(r"`([^`]+)`", cells[0]):
            match = re.match(r"[a-z_][a-z0-9_]*", token)
            if match:  # one row can document two names (`text_before` / `text_after`)
                out.append(Symbol(match.group(), "variable", match.group(), _summary(cells)))
    return out


def _parse_helpers(md: str) -> list[Symbol]:
    out: list[Symbol] = []
    for cells in _data_rows(_section(md, "## Helpers")):
        sig = _code(cells[0])
        match = re.match(r"[a-z_][a-z0-9_]*", sig)
        if match:  # `{% … %}` / `{{ … }}` rows start with `{` and are skipped
            out.append(Symbol(match.group(), "helper", sig, _summary(cells)))
    return out


def _parse_filters(md: str) -> list[Symbol]:
    out: list[Symbol] = []
    for cells in _data_rows(_section(md, "## Filters")):
        sig = _code(cells[0])
        tail = re.split(r"\s*\|\s*", sig)[-1].strip()  # `value | json` -> json
        match = re.match(r"[a-z_][a-z0-9_]*", tail)
        if match:
            out.append(Symbol(match.group(), "filter", sig, _summary(cells)))
    return out


def _parse_tags(md: str) -> list[Symbol]:
    out: list[Symbol] = []
    for cells in _data_rows(_section(md, "## Tags")):
        sig = _code(cells[0])
        match = re.search(r"\{%\s*(\w+)", sig)  # first `{% <tag>` — not `{% end… %}`
        if match:
            out.append(Symbol(match.group(1), "tag", sig, _summary(cells)))
    return out


def parse_reference(md: str) -> list[Symbol]:
    """Every documented symbol, de-duplicated by (kind, name) and stably ordered."""
    found = _parse_variables(md) + _parse_helpers(md) + _parse_filters(md) + _parse_tags(md)
    unique: dict[tuple[str, str], Symbol] = {}
    for symbol in found:
        unique.setdefault((symbol.kind, symbol.name), symbol)
    return sorted(unique.values(), key=lambda s: (_KIND_RANK[s.kind], s.name))


def names_by_kind(symbols: list[Symbol]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {kind: set() for kind in _KIND_RANK}
    for symbol in symbols:
        out[symbol.kind].add(symbol.name)
    return out
