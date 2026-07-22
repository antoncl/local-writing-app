"""Spike #396 — produce provenance-tagged runs for a set of scene-body pairs.

Throwaway harness for the spike in issue #396: does a word-level markdown diff
survive rendering (ADR-0044 §F/§G)?  This half is the *backend* half — it does
exactly what the runs endpoint would do: word-granularity
``difflib.SequenceMatcher`` over the two markdown sources, emitting
``equal / now / was`` runs.  The rendering half lives in
``frontend/spikes/396-diff-render.test.ts``, which consumes the JSON this
writes.

Run:  python scripts/spike_396_runs.py
Out:  frontend/spikes/396-runs.json
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

# Word granularity, the way a diff over prose has to do it: tokens are
# non-space runs and the whitespace between them, so a run boundary always
# falls between tokens and reassembling the tokens reproduces the source byte
# for byte.  This is the tokenisation the endpoint would use.
TOKEN = re.compile(r"\S+|\s+")


def tokenize(text: str) -> list[str]:
    return TOKEN.findall(text)


def runs_for(was: str, now: str) -> list[dict[str, str]]:
    """`[{kind: equal|now|was, text: ...}]`, in reading order.

    A ``replace`` opcode becomes an adjacent (was, now) pair — §F's "a
    modification is simply the two adjacent".
    """
    a, b = tokenize(was), tokenize(now)
    out: list[dict[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append({"kind": "equal", "text": "".join(a[i1:i2])})
        elif op == "insert":
            out.append({"kind": "now", "text": "".join(b[j1:j2])})
        elif op == "delete":
            out.append({"kind": "was", "text": "".join(a[i1:i2])})
        else:  # replace
            out.append({"kind": "was", "text": "".join(a[i1:i2])})
            out.append({"kind": "now", "text": "".join(b[j1:j2])})
    return out


# ── the candidate remedy ────────────────────────────────────────────────
# Two constraints, both applied to the runs before they leave the backend.
#
#   1. Diff per block, word-level only *inside* a block. A run can then never
#      contain a blank line, so a wrapper can never straddle `</p><p>`.
#      This is already §F's structural inline-vs-stacked rule, moved one layer
#      down into the diff itself.
#   2. Snap run boundaries out of inline constructs. A boundary that falls
#      between a construct's delimiters is expanded until the run encloses the
#      whole construct — so `**very` and `tired**` become one run `**very
#      tired**`, which renders on its own.
#
# An HTML comment counts as a construct, which is what keeps the mutation and
# todo markers whole.

BLOCK_SPLIT = re.compile(r"(\n[ \t]*\n)")

# Deliberately regex, not a parser: the spike is asking whether *a* snapping
# rule is enough, not what the production implementation should use.
PROTECTED = [
    re.compile(r"<!--[\s\S]*?-->"),
    re.compile(r"`[^`\n]*`"),
    re.compile(r"\[[^\]\n]*\]\([^)\n]*\)"),
    re.compile(r"\*\*[^\n]*?\*\*"),
    re.compile(r"~~[^\n]*?~~"),
    re.compile(r"(?<!\*)\*[^\n*][^\n]*?\*(?!\*)"),
    re.compile(r"(?<![A-Za-z0-9_])_[^\n_]+_(?![A-Za-z0-9_])"),
]


def protected_intervals(text: str) -> list[tuple[int, int]]:
    """Maximal character ranges a run boundary may not fall strictly inside."""
    spans = [m.span() for pattern in PROTECTED for m in pattern.finditer(text)]
    if not spans:
        return []
    spans.sort()
    merged = [spans[0]]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def snap(pos: int, intervals: list[tuple[int, int]], *, left: bool) -> int:
    for start, end in intervals:
        if start < pos < end:
            return start if left else end
    return pos


def word_runs(was: str, now: str) -> list[dict[str, str]]:
    """Word-level runs within one block, with boundaries snapped (constraint 2)."""
    a, b = tokenize(was), tokenize(now)
    a_off = _offsets(a)
    b_off = _offsets(b)
    a_int, b_int = protected_intervals(was), protected_intervals(now)

    # Changed regions as character ranges on each side.
    regions: list[tuple[int, int, int, int]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        regions.append((a_off[i1], a_off[i2], b_off[j1], b_off[j2]))

    # Expand out of every construct, then merge anything that now overlaps.
    changed = True
    while changed:
        changed = False
        grown: list[tuple[int, int, int, int]] = []
        for a1, a2, b1, b2 in regions:
            n = (
                snap(a1, a_int, left=True),
                snap(a2, a_int, left=False),
                snap(b1, b_int, left=True),
                snap(b2, b_int, left=False),
            )
            if n != (a1, a2, b1, b2):
                changed = True
            if grown and (n[0] <= grown[-1][1] or n[2] <= grown[-1][3]):
                prev = grown[-1]
                grown[-1] = (prev[0], max(prev[1], n[1]), prev[2], max(prev[3], n[3]))
                changed = True
            else:
                grown.append(n)
        regions = grown

    out: list[dict[str, str]] = []
    a_cursor = 0
    for a1, a2, b1, b2 in regions:
        if a1 > a_cursor:
            out.append({"kind": "equal", "text": was[a_cursor:a1]})
        if a2 > a1:
            out.append({"kind": "was", "text": was[a1:a2]})
        if b2 > b1:
            out.append({"kind": "now", "text": now[b1:b2]})
        a_cursor = a2
    if a_cursor < len(was):
        out.append({"kind": "equal", "text": was[a_cursor:]})
    return [run for run in out if run["text"]]


def _offsets(tokens: list[str]) -> list[int]:
    offsets = [0]
    for token in tokens:
        offsets.append(offsets[-1] + len(token))
    return offsets


def snapped_runs(was: str, now: str) -> list[dict[str, str]]:
    """Constraint 1 (per-block) wrapped around constraint 2 (snapped words)."""
    a_blocks = BLOCK_SPLIT.split(was)
    b_blocks = BLOCK_SPLIT.split(now)
    out: list[dict[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, a_blocks, b_blocks, autojunk=False
    ).get_opcodes():
        if op == "equal":
            out.append({"kind": "equal", "text": "".join(a_blocks[i1:i2])})
        elif op == "insert":
            out.append({"kind": "now", "text": "".join(b_blocks[j1:j2]), "stacked": True})
        elif op == "delete":
            out.append({"kind": "was", "text": "".join(a_blocks[i1:i2]), "stacked": True})
        elif i2 - i1 == j2 - j1:
            # Same number of blocks either side — each pair is a rewrite of one
            # block, so word granularity is safe inside it.
            for a_block, b_block in zip(a_blocks[i1:i2], b_blocks[j1:j2], strict=True):
                out.extend(word_runs(a_block, b_block))
        else:
            # Blocks appeared or vanished: §F says stack, so the whole region
            # is one was-then-now pair rather than words interleaved across a
            # boundary that only exists on one side. `stacked` is the flag the
            # renderer needs — such a run spans block boundaries, so it can
            # never be wrapped by an inline element (constraint 3).
            out.append({"kind": "was", "text": "".join(a_blocks[i1:i2]), "stacked": True})
            out.append({"kind": "now", "text": "".join(b_blocks[j1:j2]), "stacked": True})
    return _coalesce(out)


def _coalesce(runs: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for run in runs:
        if not run["text"]:
            continue
        if out and out[-1]["kind"] == run["kind"] and out[-1].get("stacked") == run.get("stacked"):
            out[-1] = {**out[-1], "text": out[-1]["text"] + run["text"]}
        else:
            out.append(dict(run))
    return out


MUTATE = "<!-- mutate:entity=char-maren;field=mood;value=stricken;id=m1 -->"
TODO_OPEN = "<!-- embedded-todo:id=t1;status=open;note=check%20the%20tide -->"
TODO_CLOSE = "<!-- /embedded-todo -->"

# Each case is a deliberate probe at one of the risks §G names.  The prose is
# real scene prose (the mockup's, extended), not lorem, because the failure is
# about markup meeting a word boundary and that needs real sentences around it.
CASES: list[dict[str, str]] = [
    {
        "name": "edit-inside-emphasis",
        "why": "the canonical case from the issue: **a bold phrase** -> **a bolder phrase**",
        "was": "The tide went out further than **she had ever seen it**, and kept going.",
        "now": "The tide went out further than **she had ever once seen it**, and kept going.",
    },
    {
        "name": "edit-straddles-emphasis-start",
        "why": "the edit consumes the opening delimiter and the word before it",
        "was": "She counted the hulls twice and was **very tired** by the end of it.",
        "now": "She counted the hulls twice and was quite **tired** by the end of it.",
    },
    {
        "name": "edit-straddles-emphasis-end",
        "why": "the edit consumes the closing delimiter and the word after it",
        "was": "She counted the hulls twice and was **very tired** by the end of it.",
        "now": "She counted the hulls twice and was **very** tired indeed by the end of it.",
    },
    {
        "name": "edit-inside-italic-inside-bold",
        "why": "nested inline markup — the boundary lands between two delimiter runs",
        "was": "The gulls had stopped, and **that was the *part* she remembered** afterwards.",
        "now": "The gulls had stopped, and **that was the *only part* she remembered** afterwards.",
    },
    {
        "name": "edit-inside-link-text",
        "why": "the run boundary falls inside [ ... ]",
        "was": "The eleventh was moored at [the harbour](lore://loc-corrant) all week.",
        "now": "The eleventh was moored at [the old harbour](lore://loc-corrant) all week.",
    },
    {
        "name": "edit-inside-link-target",
        "why": "the run boundary falls inside ( ... ) — the target is not prose",
        "was": "The eleventh was moored at [the harbour](lore://loc-corrant) all week.",
        "now": "The eleventh was moored at [the harbour](lore://loc-westquay) all week.",
    },
    {
        "name": "edit-adjacent-to-mutation-marker",
        "why": "the marker is an HTML comment in the body and must survive untouched",
        "was": f"Maren did not run. {MUTATE} She had never done the sensible thing quickly.",
        "now": f"Maren did not run. {MUTATE} She had never once done the sensible thing quickly.",
    },
    {
        "name": "edit-inside-mutation-marker",
        "why": "the author changed the marker's value — the diff cuts the comment itself",
        "was": f"Maren did not run. {MUTATE} She stood where she was.",
        "now": (
            "Maren did not run. "
            "<!-- mutate:entity=char-maren;field=mood;value=numb;id=m1 --> "
            "She stood where she was."
        ),
    },
    {
        "name": "edit-inside-embedded-todo",
        "why": "a todo anchor wraps prose across two comments; the edit lands between them",
        "was": f"The boats lay {TODO_OPEN}over on their sides{TODO_CLOSE} like something sleeping.",
        "now": f"The boats lay {TODO_OPEN}over on their black sides{TODO_CLOSE} like something sleeping.",
    },
    {
        "name": "paragraph-split",
        "why": "a block boundary appears where there was none",
        "was": "She counted the hulls twice. The eleventh was the Corrant. Her father was aboard.",
        "now": "She counted the hulls twice.\n\nThe eleventh was the Corrant. Her father was aboard.",
    },
    {
        "name": "paragraph-join",
        "why": "a block boundary disappears",
        "was": "She counted the hulls twice.\n\nThe eleventh was the Corrant, and her father was aboard.",
        "now": "She counted the hulls twice. The eleventh was the Corrant, and her father was aboard.",
    },
    {
        "name": "edit-inside-table-cell",
        "why": "the run boundary falls inside a table row, whose pipes are structural",
        "was": (
            "| boat | state |\n| --- | --- |\n| Corrant | at sea |\n| Maren's Luck | beached |\n"
        ),
        "now": (
            "| boat | state |\n| --- | --- |\n| Corrant | lost at sea |\n| Maren's Luck | beached |\n"
        ),
    },
    {
        "name": "edit-spanning-a-list-item-boundary",
        "why": "list markers are line-leading structure a word diff cannot see",
        "was": "- run for the high road\n- do not stop for anything you can carry\n",
        "now": "- run for the high road at once\n- do not stop for anything that can walk\n",
    },
    {
        "name": "clean-prose-control",
        "why": "the case the mockup already proves — must stay clean, or the harness is wrong",
        "was": "Somewhere behind her a shutter began to bang. Nobody came to close it.",
        "now": "Somewhere behind her, up in the town, a shutter began to bang. Nobody closed it.",
    },
]


def main() -> None:
    out = [
        {
            **case,
            "runs": runs_for(case["was"], case["now"]),
            "snapped": snapped_runs(case["was"], case["now"]),
        }
        for case in CASES
    ]
    # A run set that does not reassemble to the source is a bug in the harness,
    # not a finding — check it here rather than letting it read as damage.
    for case in out:
        for key in ("runs", "snapped"):
            for side, kinds in (("was", {"equal", "was"}), ("now", {"equal", "now"})):
                joined = "".join(r["text"] for r in case[key] if r["kind"] in kinds)
                assert joined == case[side], f"{case['name']}/{key}/{side} does not reassemble"
    target = Path(__file__).resolve().parents[1] / "frontend" / "spikes" / "396-runs.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} cases to {target}")


if __name__ == "__main__":
    main()
