"""Detect and unwrap a prose body that is entirely one fenced code block (#1628).

A copy-paste artifact: prose copied from something that presented it *as source*
— an AI panel's "copy raw markdown", a docs code sample, a "view source" pane —
lands with turndown serialising the whole document into a single fenced block,
so the entry renders monospaced instead of as prose. This module answers "is
this whole body one code fence?" and, if so, hands back the inner text so the
paste can be unwrapped back to prose.

The accidental-vs-intentional line is drawn at the **info string**, the one
signal that is explainable and does not guess at the content: only an empty or
``markdown``/``md`` info string is read as "prose shown as source". A body that
is entirely a ```` ```python ```` / ```` ```json ```` block is a legitimate code
note and is left alone. Even so the caller never rewrites silently — this only
*flags*; the unwrap is an explicit, reviewable action (never on load).
"""

from __future__ import annotations

import re

# The opening fence: up to three leading spaces (CommonMark allows that much
# indent), then a run of at least three backticks or tildes, then the rest of
# the line as the info string.
_OPEN_FENCE = re.compile(r"^ {0,3}(?P<marker>`{3,}|~{3,})(?P<info>[^\r\n]*)$")

# Info strings we read as "prose that was shown as source", not a real language.
_PROSE_INFO = frozenset({"", "markdown", "md"})


def _closing_fence(fence_char: str, fence_len: int) -> re.Pattern[str]:
    """A closing fence: the same character, at least as long, nothing else on
    the line (a closing fence carries no info string)."""
    return re.compile(rf"^ {{0,3}}{re.escape(fence_char)}{{{fence_len},}}[ \t]*$")


def unwrap_whole_body_code_fence(body: str) -> str | None:
    """The inner text if ``body`` is, ignoring blank edges, exactly one fenced
    code block with a prose-ish info string; otherwise ``None``.

    "Exactly one" is strict: the opening fence must be the first non-blank line
    and its matching close the last non-blank line, with nothing outside. A fence
    that closes early — leaving prose after it — is prose-that-contains-a-code-
    block, not a wrapped body, and is not unwrapped.
    """
    lines = body.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return None

    opener = _OPEN_FENCE.match(lines[0])
    if opener is None:
        return None
    if opener.group("info").strip().lower() not in _PROSE_INFO:
        return None

    marker = opener.group("marker")
    closing = _closing_fence(marker[0], len(marker))
    for index in range(1, len(lines)):
        if closing.match(lines[index]):
            # A close before the last line means content follows the fence — the
            # body is prose-with-a-code-block, not one wrapped body.
            if index != len(lines) - 1:
                return None
            return "\n".join(lines[1:index])
    return None  # opened but never closed
