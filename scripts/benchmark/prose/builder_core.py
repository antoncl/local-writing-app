"""The pure parts of the builder test (#2623, measuring-prose-quality.md §4.3): what to say next,
the leak check, the match draw and prompt, the tally and the report. No I/O beyond reading the two
fixture files, so every rule here is unit-tested without a backend."""

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
# The shipped built-in (ADR-0101 Amendment 2): the test measures what ships, never a copy.
BUILDER_PROMPT = Path(__file__).resolve().parents[3] / "backend" / "app" / "builtin_library" / "prompts" / "build-a-style-note.md"
BUILDER_TITLE = "Build a style note"
NOTE_TYPE = "lore:style_note"

FIRST_MESSAGE = "Infer this writing's style from these pages and propose the note."
FOLLOW_UP = "No preference; propose the note from the pages."
MAX_FOLLOW_UPS = 3
# measuring-prose-quality.md §2: 9 of the 12 held-out excerpts (4 authors x 3) matched to the right
# note; chance is 3.
BAR_NUM, BAR_DEN = 9, 12
LABELS = "ABCD"
EXCERPTS_PER_AUTHOR = 3

SYSTEM_MATCH = (
    "You are shown a passage of fiction and four style notes, A to D, each inferred from a different "
    "writer's pages. Say which note describes the writing of the passage: diction, rhythm, how sentences "
    "and paragraphs are built, how dialogue and thought are set on the page. Do not judge quality, and "
    "do not go by subject or setting. Reply with ONLY a JSON object: "
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
    """A line that opens with `word` as a Markdown heading, a bold/italic label (a bullet allowed),
    or a plain label ending in a colon ("Mechanics:"), which GPT-4.1 mini writes (#2624)."""
    marked = rf"(?:[-*+][ \t]+)?(?:#{{1,6}}[ \t]*|\*{{1,2}}|_{{1,2}})[ \t]*{word}\b"
    plain = rf"{word}[ \t]*:"
    return re.compile(rf"^[ \t]*(?:{marked}|{plain})", re.I | re.M)


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


def match_order(model: str, key: str, i: int, keys: Sequence[str] | None = None) -> list[str]:
    """The authors in slot order A-D for one trial (author `key`'s excerpt `i`, the notes of `model`):
    a permutation fixed by a hash of the trial, so reruns agree and the true note does not always
    sit in the same slot."""
    seed = f"{model}/{key}/{i}"
    return sorted(keys or author_keys(), key=lambda k: hashlib.sha256(f"{seed}/{k}".encode()).digest())


def match_message(excerpt: str, notes: Sequence[str]) -> str:
    shown = "\n\n".join(f"Style note {label}:\n{text.strip()}" for label, text in zip(LABELS, notes, strict=False))
    return f"{shown}\n\nPassage:\n{excerpt.strip()}\n\nQuestion: which note describes the writing of this passage?"


def bar_for(total: int) -> int:
    """Correct matches needed out of `total` trials (9 of 12, scaled for fewer or more)."""
    return math.ceil(total * BAR_NUM / BAR_DEN)


def picked_author(match: dict[str, Any] | None) -> str | None:
    """The author whose note a recorded match chose, or None for a missing, errored or unparsed one."""
    record = match or {}
    answer, order = record.get("answer"), record.get("order") or []
    return order[LABELS.index(answer)] if answer in tuple(LABELS) and order else None


def tally(
    notes: dict[str, dict[str, dict[str, Any]]], matches: dict[str, dict[str, dict[str, Any]]],
    authors: list[dict[str, Any]], models: Sequence[str],
) -> dict[str, Any]:
    """Per builder model and per author. `notes[model][key]` is a note record and
    `matches[model]["<key>_<i>"]` a match record. A model is judged over every trial of the run
    (authors x 3): one with any note missing or not ok has none of them run, and a trial with no
    answer is out of reach; both count against the bar. A leaking author fails outright: its trials
    never count as correct. An answer that did not parse is wrong."""
    keys = [a["key"] for a in authors]
    result_models: dict[str, dict[str, Any]] = {}
    result_authors: dict[str, dict[str, dict[str, Any]]] = {}
    cost = 0.0
    for model in models:
        model_notes, model_matches = notes.get(model, {}), matches.get(model, {})
        runnable = all(model_notes.get(k, {}).get("status") == "ok" for k in keys)
        row = {"total": len(keys) * EXCERPTS_PER_AUTHOR, "correct": 0, "out_of_reach": 0}
        per_author = {
            a["key"]: {
                "status": model_notes.get(a["key"], {}).get("status", "missing"),
                "leaked": leaks(model_notes.get(a["key"], {}).get("note_body") or "", a["leak_terms"]),
                "correct": 0, "answers": dict.fromkeys(keys, 0),
            }
            for a in authors
        }
        for key in keys:
            per = per_author[key]
            for i in range(EXCERPTS_PER_AUTHOR):
                record = model_matches.get(f"{key}_{i}")
                if not runnable or record is None or record.get("answer") == "error":
                    row["out_of_reach"] += 1
                    continue
                picked = picked_author(record)
                if picked:
                    per["answers"][picked] = per["answers"].get(picked, 0) + 1
                if picked == key and not per["leaked"]:
                    per["correct"] += 1
                    row["correct"] += 1
        row["bar"] = bar_for(row["total"])
        row["passed"] = row["correct"] >= row["bar"]
        result_models[model], result_authors[model] = row, per_author
        cost += sum(n.get("cost_usd") or 0 for n in model_notes.values())
        cost += sum(m.get("cost_usd") or 0 for m in model_matches.values())
    return {
        "models": result_models, "authors": result_authors, "cost_usd": round(cost, 4),
        "partial": len(keys) < len(author_keys()),
    }


def render_result(result: dict[str, Any]) -> str:
    """The tally as Markdown, ready for a PR body."""
    lines = ["## Builder test (H3)", ""]
    if result["partial"]:
        lines += ["Partial run: only some of the authors were built and matched, so the bar is scaled.", ""]
    lines += ["### Matching by model", "", "| Model | Correct | Out of reach | Bar | Result |", "|---|---|---|---|---|"]
    for model, row in sorted(result["models"].items()):
        verdict = "pass" if row["passed"] else "FAIL"
        lines.append(f"| {model} | {row['correct']} | {row['out_of_reach']} | {row['bar']} of {row['total']} | {verdict} |")
    lines += ["", "### Authors", "", "| Model | Author | Note | Leak | Excerpts matched to |", "|---|---|---|---|---|"]
    for model, authors in sorted(result["authors"].items()):
        for key, row in authors.items():
            leak = "FAIL: " + ", ".join(row["leaked"]) if row["leaked"] else "none"
            matched = ", ".join(f"{k} {n}" for k, n in row["answers"].items() if n) or "-"
            lines.append(f"| {model} | {key} | {row['status']} | {leak} | {matched} |")
    return "\n".join([*lines, "", f"Total cost: ${result['cost_usd']:.2f}", ""])
