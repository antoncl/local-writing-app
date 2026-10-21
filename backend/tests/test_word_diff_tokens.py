"""The word diff's tokens (#2600): punctuation is its own token, and whitespace
is never an element between two words.

Both were reported from one beat review. "shows," -> "shows." deleted and
re-inserted the whole word, and in "…THEREFORE the dirty dressing" against
"He undresses for the water; the dirty dressing" the current "the" matched the
first "the" in the proposal, splitting one insertion around it.
"""

from __future__ import annotations

from app.services.project.snapshot_diff import TOKEN, _is_a_rewrite_of, diff_runs


def _changed(was: str, now: str) -> list[tuple[str, str]]:
    """The non-equal runs, as (kind, text)."""
    return [(run.kind, run.text) for run in diff_runs(was, now) if run.kind != "equal"]


def test_tokens_split_punctuation_from_words_and_reassemble() -> None:
    text = "She doesn't stop — not once, ever.\n"
    tokens = TOKEN.findall(text)
    assert "".join(tokens) == text
    assert tokens == ["She ", "doesn't ", "stop ", "— ", "not ", "once", ", ", "ever", ".\n"]


def test_a_punctuation_only_change_marks_only_the_mark() -> None:
    assert _changed("It shows, and she sees.", "It shows; and she sees.") == [("was", ","), ("now", ";")]


def test_a_mark_and_the_word_after_it_change_together() -> None:
    assert _changed("It shows, and she sees.", "It shows. And she sees.") == [("was", ", and"), ("now", ". And")]


def test_a_repeated_word_stays_with_the_run_it_belongs_to() -> None:
    was = "He undresses for the water; the dirty dressing on his thigh shows."
    now = "The bath takes his clothes next; THEREFORE the dirty dressing on his thigh shows."
    runs = diff_runs(was, now)
    assert [run.kind for run in runs] == ["was", "now", "equal"]
    assert runs[-1].text == " the dirty dressing on his thigh shows."


def test_unchanged_closing_punctuation_stays_equal() -> None:
    assert _changed("it is not leaving.", "it is not leaving at all.") == [("now", " at all")]


def test_a_whitespace_change_inside_equal_words_is_its_own_region() -> None:
    assert _changed("the  tide", "the tide") == [("was", " ")]


def test_an_insertion_before_a_list_line_break_does_not_stack_the_list() -> None:
    was = "- run for the high road\n- do not stop\n"
    now = "- run for the high road at once\n- do not stop\n"
    runs = diff_runs(was, now)
    assert not any(run.stacked for run in runs)
    assert _changed(was, now) == [("now", " at once")]


def test_every_line_of_a_list_edited_still_diffs_per_line() -> None:
    # The bullets anchor (STRUCTURAL_MARKS); junked, the two edits would merge
    # across the line break and the list would stack.
    was = "- run\n- hide\n"
    now = "- walk\n- fight\n"
    assert not any(run.stacked for run in diff_runs(was, now))
    assert _changed(was, now) == [("was", "run"), ("now", "walk"), ("was", "hide"), ("now", "fight")]


def test_shared_punctuation_does_not_make_two_unrelated_paragraphs_a_rewrite() -> None:
    assert not _is_a_rewrite_of(
        "Maren did not run, not yet. She stood, counted, and waited.",
        "The lantern was out, the rope frayed. Nobody came, and nobody would.",
    )
