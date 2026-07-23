"""Where a run boundary may fall in a block of markdown (ADR-0044 Amendment 1).

Constraint 2 of Amendment 1 says a run boundary must never land *between* an
inline construct's delimiters: `**very` + `tired**` renders as damage, while
`**very tired**` as one run renders on its own. This module answers the only
question that needs answering for that — **which character ranges is a boundary
forbidden to fall strictly inside** — and it answers it with a single
left-to-right scan rather than a list of independent regexes.

The spike (#396) used regexes and said so: enough to establish that *a* snapping
rule suffices, but blind to escaped delimiters, code spans containing asterisks,
and unbalanced markup. This is the production form.

**The safety property, which matters more than the precision.** The scan does not
have to agree with the renderer everywhere; it has to never *under*-protect,
because under-protection is what produces damage the author sees. So:

- where precision and safety trade off, it **over-protects** — a wider interval
  costs only a coarser diff, which Amendment 1 already accepts and argues reads
  better near markup anyway;
- and a block it cannot account for confidently returns `None`, which the caller
  turns into a **stacked** run — rendered whole and wrapped around the rendered
  output, never an inline wrapper injected into source we did not understand.

That second rule is what makes unfamiliar input degrade instead of corrupt, and
it is why this can be conservative without being fragile. It came out of driving
marked's own lexer over the fixtures (#409): the obvious failsafe — "if unsure,
protect the whole block" — is *not* safe. Protecting a whole block puts the
wrapper at column 0 of a line, and a line that begins `> ` or `- ` stops being a
blockquote or a list item the moment anything precedes the marker.

The renderer's agreement is checked in CI rather than assumed: the fixtures in
`scripts/gen_diff_fixtures.py` run these runs through the real
`sceneMarkdownToHtml` and assert well-formedness and no leaked syntax.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import NamedTuple

Interval = tuple[int, int]

# Line-leading block structure. A boundary may not fall at the start of such a
# line, nor inside its marker: an inline wrapper opening before `> ` or `- `
# destroys the block.
LINE_MARKER = re.compile(r"^[ \t]*(?:>[ \t]?|(?:[-*+]|\d+[.)])[ \t]+|#{1,6}[ \t]+|\|)")

# Delimiters that open and close an inline construct by pairing with themselves.
EMPHASIS = "*_~"

# `[text][ref]` and a `[ref]: url` definition line. Both are constructs the
# renderer resolves as a unit, and neither contains the `(` `_link_end` looks
# for.
REFERENCE_LINK = re.compile(r"\[[^\]\n]*\]\[[^\]\n]*\]")
REFERENCE_DEF = re.compile(r"\[[^\]\n]+\]:[ \t]*\S+")

# The marker pairs `sceneMarkdownToHtml` rewrites as a UNIT. Protecting each
# comment on its own kept every comment whole and still let a boundary fall
# BETWEEN an anchor's two markers, so the preprocessing then matched across the
# injected wrapper and stranded its closing tag.
MARKER_PAIRS = (
    ("<!-- embedded-todo:", "<!-- /embedded-todo -->"),
    ("<!-- character:", "<!-- /character -->"),
)


def _marker_pair_end(block: str, start: int, comment_end: int) -> int:
    """Extend an opening marker comment to cover its closing partner."""
    for opener, closer in MARKER_PAIRS:
        if block.startswith(opener, start):
            close = block.find(closer, comment_end)
            if close >= 0:
                return close + len(closer)
    return comment_end


class Scanned(NamedTuple):
    """What one construct handler made of the text at the cursor.

    `end` is where the scan resumes, and has no default: every handler that
    claims a position must say where it ends.

    A handler that does not recognise its construct at the cursor returns `None`
    instead, and the dispatcher offers the position to the next one — so "this
    is not mine" and "this is mine and protects nothing" stay distinguishable,
    which is the difference between `[` opening a link and `[` being ordinary
    text.
    """

    end: int
    span: Interval | None = None
    delimiter: tuple[int, int, str] | None = None


class Unscannable:
    """A construct a handler recognises but cannot bound.

    There is no honest interval to return, so the whole block degrades to a
    stacked run rather than being cut somewhere we guessed.

    **A distinct type rather than a flag on `Scanned`**, because a flag needs an
    `end` to fill in, and every plausible filler is a real offset: `0` sends the
    scan back to the start of the block and loops forever, the cursor makes no
    progress and loops forever. Both are hangs inside a synchronous request, and
    both are one statement away — the dispatcher would only have to read `end`
    before checking the flag. This module exists to be extended a construct at a
    time, so the invariant belongs in the type rather than in statement order.
    """

    __slots__ = ()


UNSCANNABLE = Unscannable()

# What a handler may answer: an interval it bounded, `Unscannable`, or `None`
# for "not my construct, try the next one".
Scan = Scanned | Unscannable | None
Scanner = Callable[[str, int], Scan]


def _scan_escape(block: str, index: int) -> Scan:
    """A backslash escape: two characters that must travel together, and the
    escaped character is emphatically not a delimiter."""
    if block[index] != "\\" or index + 1 >= len(block):
        return None
    return Scanned(end=index + 2, span=(index, index + 2))


def _scan_html_comment(block: str, index: int) -> Scan:
    """An HTML comment, counted as one construct.

    This is what keeps the mutation, embedded-todo and character markers whole —
    the failure mode neither ADR anticipated, because `sceneMarkdownToHtml`
    rewrites those comments into spans with regexes *before* marked runs, so a
    boundary inside one silently degrades the pill to a raw comment.
    """
    if not block.startswith("<!--", index):
        return None
    close = block.find("-->", index + 4)
    if close < 0:
        return UNSCANNABLE  # unterminated: we cannot say where it ends
    end = _marker_pair_end(block, index, close + 3)
    return Scanned(end=end, span=(index, end))


def _scan_reference_link(block: str, index: int) -> Scan:
    """A reference-style link and its definition.

    There is no `(`, so `_link_end` cannot see these and a boundary landed
    inside the label: the link vanished and the definition block, which should
    render to nothing, became a visible paragraph of raw source.
    """
    if block[index] != "[":
        return None
    reference = REFERENCE_LINK.match(block, index) or REFERENCE_DEF.match(block, index)
    if not reference:
        return None
    return Scanned(end=reference.end(), span=reference.span())


def _scan_code_span(block: str, index: int) -> Scan:
    """A run of backticks closed by a run of exactly the same length.

    Its contents are literal, so any delimiter inside it must not be seen as one
    — which is where a list of regexes goes wrong.
    """
    if block[index] != "`":
        return None
    run = _run_length(block, index, "`")
    close = _find_backtick_run(block, index + run, run)
    if close < 0:
        return UNSCANNABLE  # unterminated: everything after it is ambiguous
    return Scanned(end=close + run, span=(index, close + run))


def _scan_autolink(block: str, index: int) -> Scan:
    """An autolink or a raw tag: `<...>` on one line."""
    if block[index] != "<":
        return None
    close = block.find(">", index + 1)
    if close > 0 and "\n" not in block[index:close]:
        return Scanned(end=close + 1, span=(index, close + 1))
    return UNSCANNABLE


def _scan_link(block: str, index: int) -> Scan:
    """A link or image: the whole of `[text](target)` is one construct, the
    target included — it is not prose, and a boundary inside it leaks
    `](lore://…)` into the reader's text."""
    if block[index] != "[" and not (block[index] == "!" and block.startswith("![", index)):
        return None
    end = _link_end(block, index)
    if end is None:
        # A bare `[` with no link shape is ordinary text; consume the character
        # and protect nothing, so it is not mistaken for a link.
        return Scanned(end=index + 1)
    return Scanned(end=end, span=(index, end))


def _scan_emphasis(block: str, index: int) -> Scan:
    """A run of delimiters that opens or closes by pairing with itself.

    Emitted as a delimiter rather than a span because it is only half a
    construct here — `_pair_delimiters` turns the pairs into intervals once the
    whole block has been seen.
    """
    char = block[index]
    if char not in EMPHASIS:
        return None
    run = _run_length(block, index, char)
    # Keyed by the whole delimiter RUN, not the character: `**` and `*` are
    # different constructs, and sharing one stack pairs an opening `**` with a
    # closing `*` — which mis-bounds every nested emphasis.
    return Scanned(end=index + run, delimiter=(index, index + run, char * run))


# Every handler, in order, against the characters that can open its construct.
#
# **The order is load-bearing**: an escape hides the character behind it from
# every later handler, a code span's contents are literal, and a `[` must be
# offered to the reference forms before the inline one because only the
# reference forms lack the `(` `_link_end` looks for. It is written out linearly
# here, and `_dispatch_table` derives the per-character lists from it, so the
# ordering cannot be broken by editing the table.
TRIGGERS: tuple[tuple[str, Scanner], ...] = (
    ("\\", _scan_escape),
    ("<", _scan_html_comment),
    ("[", _scan_reference_link),
    ("`", _scan_code_span),
    ("<", _scan_autolink),
    ("![", _scan_link),
    (EMPHASIS, _scan_emphasis),
)


def _dispatch_table() -> dict[str, tuple[Scanner, ...]]:
    """`TRIGGERS` inverted: opening character -> its handlers, in order.

    **Dispatching on the character rather than trying every handler is worth a
    named function.** Prose is overwhelmingly characters that open nothing, and
    offering each one to all seven handlers cost seven Python calls to reach the
    same answer — measured at 3.5x the whole scan on a plain-prose block, on a
    path that runs twice per block pair inside a synchronous request. A dict miss
    answers it once.
    """
    table: dict[str, tuple[Scanner, ...]] = {}
    for characters, scanner in TRIGGERS:
        for character in characters:
            table[character] = (*table.get(character, ()), scanner)
    return table


SCANNERS = _dispatch_table()


def _scan_at(block: str, index: int) -> Scan:
    """The first handler that recognises a construct at `index`, or `None`.

    A handler still re-checks its own opening character. That is deliberate
    redundancy: it keeps each one correct called on its own — which is how the
    tests call them — so the table stays an optimisation rather than a
    precondition the handlers silently depend on.
    """
    for scanner in SCANNERS.get(block[index], ()):
        scanned = scanner(block, index)
        if scanned is not None:
            return scanned
    return None


def protected_intervals(block: str) -> list[Interval] | None:
    """Ranges a run boundary may not fall strictly inside, or `None` to stack.

    `block` is one block of markdown — it contains no blank line, which is
    constraint 1's job and is what lets this ignore block structure beyond the
    line markers above.

    One left-to-right pass, dispatching each position to the handlers above; a
    position no handler claims is ordinary prose and a boundary may fall on it.
    """
    spans: list[Interval] = []
    delimiters: list[tuple[int, int, str]] = []  # (start, end, marker)
    index = 0
    length = len(block)

    while index < length:
        scanned = _scan_at(block, index)
        if scanned is None:
            index += 1
            continue
        if isinstance(scanned, Unscannable):
            return None
        if scanned.span is not None:
            spans.append(scanned.span)
        if scanned.delimiter is not None:
            delimiters.append(scanned.delimiter)
        index = scanned.end

    paired = _pair_delimiters(delimiters)
    if paired is None:
        return None
    spans.extend(paired)
    spans.extend(_line_marker_intervals(block))
    return _merge(spans)


def _run_length(block: str, start: int, char: str) -> int:
    index = start
    while index < len(block) and block[index] == char:
        index += 1
    return index - start


def _find_backtick_run(block: str, start: int, run: int) -> int:
    """The offset of the next backtick run of exactly `run`, or -1."""
    index = start
    while index < len(block):
        if block[index] != "`":
            index += 1
            continue
        here = _run_length(block, index, "`")
        if here == run:
            return index
        index += here
    return -1


def _link_end(block: str, start: int) -> int | None:
    """The offset just past `[text](target)` / `![text](target)`, or None.

    Brackets nest (a link's text may contain one) and so may the parentheses in
    a target, so both are matched by depth rather than by the first closer.
    """
    index = start + (2 if block[start] == "!" else 1)
    depth = 1
    while index < len(block) and depth:
        if block[index] == "\\":
            index += 2
            continue
        if block[index] == "[":
            depth += 1
        elif block[index] == "]":
            depth -= 1
        index += 1
    if depth or index >= len(block) or block[index] != "(":
        return None
    depth = 1
    index += 1
    while index < len(block) and depth:
        if block[index] == "\\":
            index += 2
            continue
        if block[index] == "(":
            depth += 1
        elif block[index] == ")":
            depth -= 1
        index += 1
    return index if not depth else None


def _pair_delimiters(delimiters: list[tuple[int, int, str]]) -> list[Interval] | None:
    """Pair emphasis runs into intervals, or `None` if any is left unpaired.

    Deliberately cruder than CommonMark's flanking rules, in the safe direction:
    an intraword `_` pairs with the next one and protects a little more text
    than it needs to, which costs precision only. An *unpaired* run is the case
    that cannot be made safe by widening — we do not know whether the renderer
    reads it as emphasis — so the block stacks instead.
    """
    spans: list[Interval] = []
    open_runs: dict[str, list[tuple[int, int]]] = {}
    for start, end, marker in delimiters:
        stack = open_runs.setdefault(marker, [])
        if stack:
            opened = stack.pop()
            spans.append((opened[0], end))
        else:
            stack.append((start, end))
    if any(stack for stack in open_runs.values()):
        return None
    return spans


def _line_marker_intervals(block: str) -> list[Interval]:
    """Protect each line's leading block marker, *including the newline before
    it*.

    The newline is the load-bearing part. `snap` only moves a boundary that
    falls strictly inside an interval, so an interval starting exactly at the
    line start would leave a boundary at the line start untouched — and that is
    precisely the damaging position, because the wrapper then opens before the
    marker. Reaching back over the newline makes the line start interior, so the
    boundary snaps out to before the newline and the marker stays line-leading.
    """
    spans: list[Interval] = []
    for match in re.finditer(r"^.*$", block, re.MULTILINE):
        marker = LINE_MARKER.match(match.group(0))
        if not marker or not marker.group(0):
            continue
        line_start = match.start()
        spans.append((max(0, line_start - 1), line_start + len(marker.group(0))))
    return spans


def first_line_is_structural(block: str) -> bool:
    """Whether the block's first line carries a line marker.

    Such a block has no position before its marker to snap a boundary back to,
    so a change reaching its very start cannot be wrapped inline at all.
    """
    marker = LINE_MARKER.match(block.split("\n", 1)[0])
    return bool(marker and marker.group(0))


# A GFM table's delimiter row. Leading pipes are OPTIONAL in GFM, so `LINE_MARKER`
# alone — which anchors `|` at line start — declared `a | b\n--- | ---\nc | d` to
# be ordinary prose, and a run then wrapped straight across a cell boundary.
TABLE_DELIMITER = re.compile(r"^[ \t]*:?-{1,}:?([ \t]*\|[ \t]*:?-{1,}:?)+[ \t]*$")

# A setext underline turns the line ABOVE it into a heading, so an inline run
# that swallows it collapses the heading and leaks the underline as text.
SETEXT_UNDERLINE = re.compile(r"^[ \t]*(=+|-{2,})[ \t]*$")

# A code fence, and an indented (4-space or tab) code line.
CODE_FENCE = re.compile(r"^[ \t]*(```|~~~)")
INDENTED_CODE = re.compile(r"^(?: {4}|\t)")


def is_code_block(block: str) -> bool:
    """Whether this block is code, fenced or indented.

    Code is the one place a wrapper cannot go *anywhere*. Inside a fence the
    injected `<span>` is content, so the reader sees the markup as literal text
    — and the fence itself was being scanned as a code span, so the whole block
    came back as a single inline run whose wrapper opened at column 0 and
    dissolved the fence entirely. An indented block behaves the same way.

    So code never gets a word-level diff; it stacks, and the author reads the
    two versions whole. That is the honest rendering of a change to code.
    """
    lines = [line for line in block.split("\n") if line.strip()]
    if not lines:
        return False
    if CODE_FENCE.match(lines[0]):
        return True
    return all(INDENTED_CODE.match(line) for line in lines)


def is_structured(block: str) -> bool:
    """Whether any line of the block carries block-level structure.

    In such a block the line — and in a table the *cell* — is a container an
    inline wrapper may not escape, quite apart from where the delimiters are.

    Line markers are only part of it. A GFM table may be written without leading
    pipes, and a setext heading's structure is the line *below* the text, so both
    are checked in their own right rather than inferred from a leading character.
    """
    lines = block.split("\n")
    return any(
        LINE_MARKER.match(line) or TABLE_DELIMITER.match(line) or SETEXT_UNDERLINE.match(line)
        for line in lines
    ) or is_code_block(block)


# Characters that end a structural container mid-block: a newline ends a
# blockquote line, a list item or a table row, and `|` ends a table cell. A run
# wrapping either of them produces markup the parser tears apart — `<td><span
# class="r-was">stone</td>` and a `<span>` that never closes.
CONTAINER_BREAKS = ("\n", "|")


def escapes_container(block: str, start: int, end: int) -> bool:
    """Whether wrapping `block[start:end]` would cross a structural container."""
    return is_structured(block) and any(char in block[start:end] for char in CONTAINER_BREAKS)


def _merge(spans: list[Interval]) -> list[Interval]:
    if not spans:
        return []
    spans = sorted(spans)
    merged = [spans[0]]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
