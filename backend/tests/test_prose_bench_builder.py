"""Builder test of the prose harness (#2623): the follow-up rule, the leak check, the match draw,
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


def test_match_order_is_a_stable_permutation():
    order = core.match_order("model-a", "crane", 1, KEYS)
    assert sorted(order) == sorted(KEYS)
    assert order == core.match_order("model-a", "crane", 1, KEYS)


def test_the_true_note_moves_between_slots():
    trials = [(m, i) for m in ("a", "b") for i in range(3)]
    assert len({core.match_order(m, k, i, KEYS).index(k) for k in KEYS for m, i in trials}) == 4
    for key in KEYS:
        assert len({core.match_order(m, key, i, KEYS).index(key) for m, i in trials}) > 1


def _matches(correct: int, total: int = 12) -> dict[str, dict]:
    """Trial records for author `KEYS[t // 3]`'s excerpt `t % 3`: the first `correct` pick the true note."""
    out = {}
    for t in range(total):
        key = KEYS[t // 3]
        order = [key, *(k for k in KEYS if k != key)]
        out[f"{key}_{t % 3}"] = {"order": order, "answer": "A" if t < correct else "B", "cost_usd": 0.01}
    return out


def _notes() -> dict[str, dict]:
    return {k: dict(NOTE) for k in KEYS}


def test_bar_is_nine_of_twelve():
    assert core.bar_for(12) == 9
    result = core.tally({"m": _notes(), "w": _notes()}, {"m": _matches(9), "w": _matches(8)}, AUTHORS, ["m", "w"])
    assert result["models"]["m"]["correct"] == 9 and result["models"]["m"]["passed"]
    assert result["models"]["w"]["correct"] == 8 and not result["models"]["w"]["passed"]


def test_a_leaking_author_fails_outright():
    notes = _notes()
    notes["crane"]["note_body"] = "Written like Crane."
    result = core.tally({"m": notes}, {"m": _matches(12)}, AUTHORS, ["m"])
    assert result["authors"]["m"]["crane"]["leaked"] == ["Crane"]
    assert result["authors"]["m"]["crane"]["correct"] == 0
    assert result["models"]["m"]["correct"] == 9 and result["models"]["m"]["passed"]
    notes["chopin"]["note_body"] = "Chopin."
    assert not core.tally({"m": notes}, {"m": _matches(12)}, AUTHORS, ["m"])["models"]["m"]["passed"]


def test_a_missing_note_puts_every_trial_out_of_reach():
    notes = _notes()
    notes["wharton"]["status"] = "out_of_reach"
    row = core.tally({"m": notes}, {"m": _matches(12)}, AUTHORS, ["m"])["models"]["m"]
    assert (row["total"], row["correct"], row["out_of_reach"], row["bar"], row["passed"]) == (12, 0, 12, 9, False)
    del notes["wharton"]
    assert core.tally({"m": notes}, {}, AUTHORS, ["m"])["models"]["m"]["out_of_reach"] == 12


def test_a_trial_not_run_counts_against_the_bar():
    row = core.tally({"m": _notes()}, {"m": _matches(12, total=9)}, AUTHORS, ["m"])["models"]["m"]
    assert (row["correct"], row["out_of_reach"], row["total"]) == (9, 3, 12) and row["passed"]
    assert not core.tally({"m": _notes()}, {"m": _matches(8, total=9)}, AUTHORS, ["m"])["models"]["m"]["passed"]


def test_an_unparsed_answer_counts_as_wrong():
    matches = _matches(12)
    matches["crane_0"] = {"order": matches["crane_0"]["order"], "answer": "unparsed"}
    row = core.tally({"m": _notes()}, {"m": matches}, AUTHORS, ["m"])["models"]["m"]
    assert (row["correct"], row["out_of_reach"]) == (11, 0)


def test_the_confusion_lists_which_notes_the_excerpts_matched():
    result = core.tally({"m": _notes()}, {"m": _matches(0)}, AUTHORS, ["m"])
    # Every answer was "B": the second slot of the order [key, *others].
    assert result["authors"]["m"]["crane"]["answers"] == {"crane": 0, "chopin": 3, "london": 0, "wharton": 0}


def test_a_run_of_one_author_is_partial_and_scales_the_bar():
    crane = [a for a in AUTHORS if a["key"] == "crane"]
    notes, matches = {"m": {"crane": dict(NOTE)}}, {"m": {f"crane_{i}": {"order": KEYS, "answer": "A"} for i in range(3)}}
    result = core.tally(notes, matches, crane, ["m"])
    assert result["partial"] and result["models"]["m"]["bar"] == 3 and result["models"]["m"]["passed"]
    assert "Partial run" in core.render_result(result)


def test_cost_sums_notes_and_matches():
    result = core.tally({"m": _notes()}, {"m": _matches(0, total=2)}, AUTHORS, ["m"])
    assert result["cost_usd"] == 0.42


def test_result_is_markdown():
    text = core.render_result(core.tally({"m": _notes()}, {"m": _matches(9)}, AUTHORS, ["m"]))
    assert "| m | 9 | 0 | 9 of 12 | pass |" in text and "Total cost" in text


def test_match_message_labels_the_notes_in_order():
    text = core.match_message("The passage.", ["one", "two", "three", "four"])
    assert text.index("Style note A:\none") < text.index("Style note D:\nfour") < text.index("Passage:\nThe passage.")


def test_authors_fixture():
    authors = core.load_authors()
    assert [a["key"] for a in authors] == KEYS
    for author in authors:
        assert len(author["pages"].split()) >= 1200
        assert len(author["excerpts"]) == core.EXCERPTS_PER_AUTHOR
        assert all(len(excerpt.split()) >= 250 for excerpt in author["excerpts"])
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
