"""The pure parts of the builder test (#2623, measuring-prose-quality.md §4.3): what to say next,
the leak check, the attribution draw and prompt, the tally and the report. No I/O beyond reading
the two fixture files, so every rule here is unit-tested without a backend."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

FIXTURE = Path(__file__).resolve().parent / "fixture"
AUTHORS_YAML = FIXTURE / "authors.yaml"
BUILDER_PROMPT = FIXTURE / "style-builder.md"

FIRST_MESSAGE = "Infer this writing's style from these pages and propose the note."
FOLLOW_UP = "No preference; propose the note from the pages."
MAX_FOLLOW_UPS = 3
# measuring-prose-quality.md §2: 9 of the 12 drafts (4 authors x 3) attributed correctly; chance is 3.
BAR_NUM, BAR_DEN = 9, 12
LABELS = "ABCD"

SYSTEM_ATTRIBUTION = (
    "You are shown a passage of fiction and four excerpts, A to D, each by a different writer. Say "
    "which writer the passage is closest to in style: diction, rhythm, how sentences and paragraphs are "
    "built, how dialogue and thought are set on the page. Do not judge quality, and do not go by "
    "subject or setting. Reply with ONLY a JSON object: "
    '{"answer": "A", "B", "C" or "D", "quote": "<the shortest passage that decides it, verbatim>"}'
)


def load_authors() -> list[dict[str, Any]]:
    return yaml.safe_load(AUTHORS_YAML.read_text(encoding="utf-8"))["authors"]


def author_keys() -> list[str]:
    return [a["key"] for a in load_authors()]


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """A prompt file as `(front matter, body)`: the YAML between the first two `---` lines, then the rest."""
    _, front, body = text.split("---\n", 2)
    return yaml.safe_load(front), body


def first_user_turn(pages: str) -> str:
    return f"{pages.strip()}\n\n{FIRST_MESSAGE}"


def _label(word: str) -> re.Pattern[str]:
    """A line that opens with `word` as a Markdown heading or a bold/italic label (a bullet allowed)."""
    return re.compile(rf"^[ \t]*(?:[-*+][ \t]+)?(?:#{{1,6}}[ \t]*|\*{{1,2}}|_{{1,2}})[ \t]*{word}\b", re.I | re.M)


MECHANICS, MANNER = _label("Mechanics"), _label("Manner")


def needs_follow_up(reply: str) -> bool:
    """True while the reply holds no proposed note: it lacks a Mechanics or a Manner heading/label."""
    return not (MECHANICS.search(reply) and MANNER.search(reply))


def leaks(note_body: str, leak_terms: Sequence[str]) -> list[str]:
    """The terms found in the note, case-insensitive and as whole words or phrases: "London" does not
    match "Londoner" and "Bart" does not match "Bartholomew", but "Crane" matches "Crane's"."""
    found = []
    for term in leak_terms:
        pattern = r"\s+".join(re.escape(part) for part in term.split())
        if re.search(rf"(?<!\w){pattern}(?!\w)", note_body, re.I):
            found.append(term)
    return found


def excerpt_order(key: str, model: str, n: int, keys: Sequence[str] | None = None) -> list[str]:
    """The authors in slot order A-D for one draft: a permutation fixed by a hash of its path, so
    reruns agree and the true author does not always sit in the same slot."""
    seed = f"{key}/{model}/{n}"
    return sorted(keys or author_keys(), key=lambda k: hashlib.sha256(f"{seed}/{k}".encode()).digest())


def attribution_message(draft: str, excerpts: Sequence[str]) -> str:
    shown = "\n\n".join(f"Excerpt {label}:\n{text.strip()}" for label, text in zip(LABELS, excerpts, strict=True))
    return f"{shown}\n\nPassage:\n{draft.strip()}\n\nQuestion: which excerpt's writer is this passage closest to in style?"


def bar_for(total: int) -> int:
    """Correct attributions needed out of `total` drafts (9 of 12, scaled for fewer or more)."""
    return math.ceil(total * BAR_NUM / BAR_DEN)


def picked_author(attribution: dict[str, Any] | None) -> str | None:
    """The author a recorded attribution chose, or None for a missing, errored or unparsed one."""
    record = attribution or {}
    answer, order = record.get("answer"), record.get("order") or []
    return order[LABELS.index(answer)] if answer in tuple(LABELS) and order else None


def tally(notes: dict[str, dict[str, Any]], drafts: list[dict[str, Any]], authors: list[dict[str, Any]]) -> dict[str, Any]:
    """Per model and per author. `drafts` are `{key, model, status, cost_usd, attribution}` (attribution
    may be None). A leaking author fails outright: its drafts never count as correct. The bar is taken
    over every draft recorded for the model, so one out of reach counts against it."""
    keys = [a["key"] for a in authors]
    leaked = {a["key"]: leaks(notes.get(a["key"], {}).get("note_body") or "", a["leak_terms"]) for a in authors}
    by_author = {
        key: {
            "status": notes.get(key, {}).get("status", "missing"), "leaked": leaked[key],
            "ok": 0, "correct": 0, "answers": dict.fromkeys(keys, 0),
        }
        for key in keys
    }
    models: dict[str, dict[str, Any]] = {}
    for draft in drafts:
        row = models.setdefault(draft["model"], {"total": 0, "ok": 0, "out_of_reach": 0, "correct": 0})
        row["total"] += 1
        if draft["status"] != "ok":
            row["out_of_reach"] += 1
            continue
        row["ok"] += 1
        per = by_author[draft["key"]]
        per["ok"] += 1
        picked = picked_author(draft.get("attribution"))
        if picked:
            # The judge can pick any of the four excerpts, also an author left out of this run.
            per["answers"][picked] = per["answers"].get(picked, 0) + 1
        if picked == draft["key"]:
            per["correct"] += 1
            row["correct"] += 0 if leaked[draft["key"]] else 1
    for row in models.values():
        row["bar"] = bar_for(row["total"])
        row["passed"] = row["correct"] >= row["bar"]
    cost = sum(n.get("cost_usd") or 0 for n in notes.values()) + sum(
        (d.get("cost_usd") or 0) + ((d.get("attribution") or {}).get("cost_usd") or 0) for d in drafts
    )
    return {"models": models, "authors": by_author, "cost_usd": round(cost, 4)}


def render_result(result: dict[str, Any]) -> str:
    """The tally as Markdown, ready for a PR body."""
    lines = ["## Builder test (H3)", "", "### Attribution by model", "",
             "| Model | Correct | Of ok drafts | Out of reach | Bar | Result |", "|---|---|---|---|---|---|"]
    for model, row in sorted(result["models"].items()):
        verdict = "pass" if row["passed"] else "FAIL"
        lines.append(f"| {model} | {row['correct']} | {row['ok']} | {row['out_of_reach']} | {row['bar']} of {row['total']} | {verdict} |")
    lines += ["", "### Authors", "", "| Author | Note | Leak | Drafts attributed to it |", "|---|---|---|---|"]
    for key, row in result["authors"].items():
        leak = "FAIL: " + ", ".join(row["leaked"]) if row["leaked"] else "none"
        lines.append(f"| {key} | {row['status']} | {leak} | {row['correct']} of {row['ok']} |")
    return "\n".join([*lines, "", f"Total cost: ${result['cost_usd']:.2f}", ""])
