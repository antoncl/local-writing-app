"""Generated documents for the snapshot-diff sweep (#409).

Eighteen adversarial fixtures is a good sample, not a proof, and the failure this
guards against is exactly what a hand-picked set misses: a combination of
constructs nobody thought to write down. This builds plausible scene bodies —
prose seeded with emphasis, links, code spans, markers, blockquotes, lists and
tables — and a plausible author edit over each.

It already earned its keep. Four defects came out of it that the eighteen never
touched, and each now has a named test of its own in `test_snapshot_diff.py`:
runs that stopped reassembling when a construct existed on one side only, a run
spanning a table cell's `|`, mis-paired nested emphasis, and a settle loop that
did not terminate.

**Two consumers, deliberately.** `test_snapshot_diff.py` runs it every build over
the invariants Python can check on its own — cheap, and no artifact in the tree.
`scripts/gen_diff_fixtures.py` runs it on demand to write a corpus the frontend
can put through the *real* renderer, which is the only thing that can answer
whether a run survives rendering. That output is gitignored: it is a sweep, not a
regression surface, and committing it put twelve thousand lines of generated JSON
in front of every reviewer.
"""

from __future__ import annotations

import os
import random

# Seeded, so a corpus is reproducible and so is a failure in it.
FUZZ_SEED = 409
DEFAULT_CASES = int(os.environ.get("FUZZ_CASES", "400"))

WORDS = ["tide", "harbour", "hull", "gull", "shutter", "water", "breath", "rope", "salt", "lamp", "boat", "quay", "stone", "morning", "father", "counted", "twice", "never", "once", "again", "slowly", "went", "out", "further", "kept", "going", "stood", "where", "she", "was", "nobody", "came", "to", "close", "it", "behind", "her", "the", "town"]

CONSTRUCTS = (
    "**{a} {b}**",
    "*{a}*",
    "~~{a}~~",
    "`{a} ** {b}`",
    "[{a} {b}](lore://loc-{a})",
    "[{a}](lore://char-{b})",
    "<!-- mutate:entity=char-{a};field=mood;value={b};id=m1 -->",
    "<!-- embedded-todo:id=t1;status=open;note={a} -->{b}<!-- /embedded-todo -->",
    "\\*{a}\\*",
)

BLOCK_SHAPES = ("para", "para", "para", "quote", "list", "heading", "table")


def _sentence(rng: random.Random) -> str:
    parts: list[str] = []
    for _ in range(rng.randint(4, 12)):
        if rng.random() < 0.22:
            shape = rng.choice(CONSTRUCTS)
            parts.append(shape.format(a=rng.choice(WORDS), b=rng.choice(WORDS)))
        else:
            parts.append(rng.choice(WORDS))
    return " ".join(parts)


def _block(rng: random.Random) -> str:
    shape = rng.choice(BLOCK_SHAPES)
    if shape == "quote":
        return "\n".join(f"> {_sentence(rng)}" for _ in range(rng.randint(1, 3)))
    if shape == "list":
        return "\n".join(f"- {_sentence(rng)}" for _ in range(rng.randint(1, 3)))
    if shape == "heading":
        return f"{'#' * rng.randint(1, 3)} {_sentence(rng)}"
    if shape == "table":
        rows = "\n".join(f"| {rng.choice(WORDS)} | {rng.choice(WORDS)} |" for _ in range(2))
        return f"| boat | state |\n| --- | --- |\n{rows}"
    return _sentence(rng)


def _document(rng: random.Random) -> str:
    return "\n\n".join(_block(rng) for _ in range(rng.randint(1, 4)))


def _edit(rng: random.Random, document: str) -> str:
    """A plausible author edit: replace, insert or delete a span of words, or
    split/join a block."""
    choice = rng.random()
    if choice < 0.12:
        return document.replace("\n\n", " ", 1) if "\n\n" in document else document
    if choice < 0.24:
        words = document.split(" ")
        if len(words) > 6:
            at = rng.randrange(3, len(words) - 2)
            return " ".join(words[:at]) + "\n\n" + " ".join(words[at:])
        return document
    words = document.split(" ")
    if len(words) < 4:
        return document + " " + rng.choice(WORDS)
    start = rng.randrange(0, len(words) - 2)
    end = min(len(words), start + rng.randint(1, 4))
    if choice < 0.5:
        replacement = [rng.choice(WORDS) for _ in range(rng.randint(1, 3))]
        return " ".join(words[:start] + replacement + words[end:])
    if choice < 0.75:
        return " ".join(words[:start] + [rng.choice(WORDS)] + words[start:])
    return " ".join(words[:start] + words[end:])


def fuzz_cases(count: int | None = None) -> list[dict[str, str]]:
    rng = random.Random(FUZZ_SEED)
    cases: list[dict[str, str]] = []
    for index in range(count if count is not None else DEFAULT_CASES):
        was = _document(rng)
        now = _edit(rng, was)
        if was == now:
            now = was + " " + rng.choice(WORDS)
        cases.append({"name": f"fuzz-{index:03d}", "why": "generated", "was": was, "now": now})
    return cases


