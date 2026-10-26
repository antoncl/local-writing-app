"""Builder test of the prose harness (#2623): the follow-up rule, the leak check, the excerpt draw,
the tally and the two fixture files. Nothing here touches a backend or a model."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "benchmark" / "prose"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"prose_bench_{name}", _DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(_DIR))
core = _load("builder_core")

KEYS = ["crane", "chopin", "london", "wharton"]
AUTHORS = [{"key": k, "leak_terms": [k.capitalize()]} for k in KEYS]
NOTE = {"status": "ok", "note_body": "Plain diction.", "cost_usd": 0.1}


def test_a_contrast_question_needs_a_follow_up():
    reply = "Which is closer?\n\nA: She ran. B: She did run.\n\nThe mechanics and manner are open."
    assert core.needs_follow_up(reply)


def test_a_proposed_note_needs_none():
    assert not core.needs_follow_up("Ready to commit.\n\n## Mechanics\n- Dialogue: bare.\n\n## Manner\n- Frank.\n")
    assert not core.needs_follow_up("**Mechanics**\nx\n\n**manner:** y")
    assert not core.needs_follow_up("- **Mechanics:** x\n- *Manner* y")


def test_one_part_alone_still_needs_a_follow_up():
    assert core.needs_follow_up("## Mechanics\n- Dialogue: bare.")
    assert core.needs_follow_up("## Manner\n- Frank.")


def test_leaks_are_whole_words_ignoring_case():
    assert core.leaks("Written like crane's dialect.", ["Crane"]) == ["Crane"]
    assert core.leaks("the rum  alley mob", ["Rum Alley"]) == ["Rum Alley"]
    assert core.leaks("The Londoner left.", ["London"]) == []
    assert core.leaks("Bartholomew paid.", ["Bart"]) == []
    assert core.leaks("Plain diction.", ["Crane", "Maggie"]) == []


def test_excerpt_order_is_a_stable_permutation():
    order = core.excerpt_order("crane", "model-a", 1, KEYS)
    assert sorted(order) == sorted(KEYS)
    assert order == core.excerpt_order("crane", "model-a", 1, KEYS)


def test_the_true_author_moves_between_slots():
    slots = {core.excerpt_order(k, m, n, KEYS).index(k) for k in KEYS for m in ("a", "b") for n in (1, 2, 3)}
    assert len(slots) == 4
    for key in KEYS:
        assert len({core.excerpt_order(key, m, n, KEYS).index(key) for m in ("a", "b") for n in (1, 2, 3)}) > 1


def _drafts(model: str, correct: int, total: int = 12, status: str = "ok") -> list[dict]:
    out = []
    for i in range(total):
        key = KEYS[i % 4]
        order = [key, *(k for k in KEYS if k != key)]
        answer = "A" if i < correct else "B"
        out.append({"key": key, "model": model, "status": status, "cost_usd": 0.5,
                    "attribution": {"order": order, "answer": answer, "cost_usd": 0.01}})
    return out


def test_bar_is_nine_of_twelve():
    assert core.bar_for(12) == 9
    result = core.tally({k: dict(NOTE) for k in KEYS}, _drafts("m", 9) + _drafts("w", 8), AUTHORS)
    assert result["models"]["m"]["correct"] == 9 and result["models"]["m"]["passed"]
    assert not result["models"]["w"]["passed"]


def test_out_of_reach_drafts_count_against_the_bar():
    drafts = _drafts("m", 9, total=9) + _drafts("m", 0, total=3, status="out_of_reach")
    row = core.tally({k: dict(NOTE) for k in KEYS}, drafts, AUTHORS)["models"]["m"]
    assert (row["ok"], row["out_of_reach"], row["total"], row["bar"]) == (9, 3, 12, 9)


def test_a_leaking_author_fails_outright():
    notes = {k: dict(NOTE) for k in KEYS}
    notes["crane"]["note_body"] = "Written like Crane."
    result = core.tally(notes, _drafts("m", 12), AUTHORS)
    assert result["authors"]["crane"]["leaked"] == ["Crane"]
    assert result["authors"]["crane"]["correct"] == 3
    assert result["models"]["m"]["correct"] == 9
    notes["chopin"]["note_body"] = "Chopin."
    assert not core.tally(notes, _drafts("m", 12), AUTHORS)["models"]["m"]["passed"]


def test_a_failed_note_counts_its_missing_drafts_against_the_bar():
    # #2624 review: wharton's note failed, so it has no drafts; the bar must stay 9 of 12, not 7 of 9.
    notes = {k: dict(NOTE) for k in KEYS}
    notes["wharton"]["status"] = "out_of_reach"
    drafts = [d for d in _drafts("m", 12) if d["key"] != "wharton"]
    row = core.tally(notes, drafts, AUTHORS)["models"]["m"]
    assert (row["total"], row["out_of_reach"], row["bar"]) == (12, 3, 9)
    assert row["correct"] == 9 and row["passed"]
    fewer = [d for d in _drafts("m", 7) if d["key"] != "wharton"]
    assert not core.tally(notes, fewer, AUTHORS)["models"]["m"]["passed"]


def test_a_run_of_one_author_tallies_picks_of_the_others():
    # #2623 smoke run: --authors crane, and the judge picked Chopin's excerpt.
    crane = [a for a in AUTHORS if a["key"] == "crane"]
    draft = _drafts("m", 0, total=1)[0]  # crane's draft, answered "B": another author
    result = core.tally({"crane": dict(NOTE)}, [draft], crane)
    assert sum(result["authors"]["crane"]["answers"].values()) == 1
    assert result["models"]["m"]["correct"] == 0


def test_cost_sums_notes_drafts_and_attributions():
    result = core.tally({"crane": dict(NOTE)}, _drafts("m", 0, total=4)[:1], AUTHORS)
    assert result["cost_usd"] == 0.61


def test_result_is_markdown():
    text = core.render_result(core.tally({k: dict(NOTE) for k in KEYS}, _drafts("m", 9), AUTHORS))
    assert "| m | 9 | 12 | 0 | 9 of 12 | pass |" in text and "Total cost" in text


def test_authors_fixture():
    authors = core.load_authors()
    assert [a["key"] for a in authors] == KEYS
    for author in authors:
        assert len(author["pages"].split()) >= 1200 and len(author["excerpt"].split()) >= 250
        assert author["leak_terms"]


def test_builder_prompt_front_matter():
    front, body = core.split_front_matter(core.BUILDER_PROMPT.read_text(encoding="utf-8"))
    assert front["title"] == "Narration conventions"
    inputs = {i["name"]: i for i in front["inputs"]}
    assert "entry" in inputs and inputs["inherited"]["target"]["multiple"] is True
    assert front["context_strategy"]["output"]["handler"] == "extract_to_node"
    assert "Mechanics" in body


def test_first_user_turn_is_pages_then_the_fixed_message():
    assert core.first_user_turn("Pages.\n") == f"Pages.\n\n{core.FIRST_MESSAGE}"
