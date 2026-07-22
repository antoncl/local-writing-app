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

Interval = tuple[int, int]

# Line-leading block structure. A boundary may not fall at the start of such a
# line, nor inside its marker: an inline wrapper opening before `> ` or `- `
# destroys the block.
LINE_MARKER = re.compile(r"^[ \t]*(?:>[ \t]?|(?:[-*+]|\d+[.)])[ \t]+|#{1,6}[ \t]+|\|)")

# Delimiters that open and close an inline construct by pairing with themselves.
EMPHASIS = "*_~"


def protected_intervals(block: str) -> list[Interval] | None:
    """Ranges a run boundary may not fall strictly inside, or `None` to stack.

    `block` is one block of markdown — it contains no blank line, which is
    constraint 1's job and is what lets this ignore block structure beyond the
    line markers above.
    """
    spans: list[Interval] = []
    delimiters: list[tuple[int, int, str]] = []  # (start, end, marker)
    index = 0
    length = len(block)

    while index < length:
        char = block[index]

        # A backslash escape is two characters that must travel together, and
        # the escaped character is emphatically not a delimiter.
        if char == "\\" and index + 1 < length:
            spans.append((index, index + 2))
            index += 2
            continue

        # An HTML comment is one construct. This is what keeps the mutation,
        # embedded-todo and character markers whole — the failure mode neither
        # ADR anticipated, because `sceneMarkdownToHtml` rewrites those comments
        # into spans with regexes *before* marked runs, so a boundary inside one
        # silently degrades the pill to a raw comment.
        if block.startswith("<!--", index):
            close = block.find("-->", index + 4)
            if close < 0:
                return None  # unterminated: we cannot say where it ends
            spans.append((index, close + 3))
            index = close + 3
            continue

        # A code span is delimited by a run of backticks and closed by a run of
        # exactly the same length. Its contents are literal, so any delimiter
        # inside it must not be seen as one — which is where a list of regexes
        # goes wrong.
        if char == "`":
            run = _run_length(block, index, "`")
            close = _find_backtick_run(block, index + run, run)
            if close < 0:
                return None  # unterminated: everything after it is ambiguous
            spans.append((index, close + run))
            index = close + run
            continue

        # An autolink or a raw tag: `<...>` on one line.
        if char == "<":
            close = block.find(">", index + 1)
            if close > 0 and "\n" not in block[index:close]:
                spans.append((index, close + 1))
                index = close + 1
                continue
            return None

        # A link or image: the whole of `[text](target)` is one construct, the
        # target included — it is not prose, and a boundary inside it leaks
        # `](lore://…)` into the reader's text.
        if char == "[" or (char == "!" and block.startswith("![", index)):
            end = _link_end(block, index)
            if end is None:
                # A bare `[` with no link shape is ordinary text; fall through
                # so it is not mistaken for one.
                index += 1
                continue
            spans.append((index, end))
            index = end
            continue

        if char in EMPHASIS:
            run = _run_length(block, index, char)
            # Keyed by the whole delimiter RUN, not the character: `**` and `*`
            # are different constructs, and sharing one stack pairs an opening
            # `**` with a closing `*` — which mis-bounds every nested emphasis.
            delimiters.append((index, index + run, char * run))
            index += run
            continue

        index += 1

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


def is_structured(block: str) -> bool:
    """Whether any line of the block carries block-level structure.

    In such a block the line — and in a table the *cell* — is a container an
    inline wrapper may not escape, quite apart from where the delimiters are.
    """
    return any(LINE_MARKER.match(line) for line in block.split("\n"))


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
