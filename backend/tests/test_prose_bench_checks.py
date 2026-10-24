"""Rules for the prose harness's script checks and noise band (#2613).

The harness lives under scripts/benchmark/prose/, outside the backend package, so
load its modules by path (as test_pr_body_lint.py does).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "benchmark" / "prose"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"prose_bench_{name}", _DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# report.py imports `checks` by name from its own folder; load that first.
sys.path.insert(0, str(_DIR))
checks = _load("checks")
report = _load("report")


def test_dialogue_and_narration_split_on_straight_quotes():
    dialogue, narration = checks.split_dialogue('He sat. "Go home," she said. "Now."')
    assert dialogue == "Go home,\nNow."
    assert narration == "He sat.   she said.  "


def test_dialogue_and_narration_split_on_curly_quotes():
    dialogue, narration = checks.split_dialogue("He sat. “Go home,” she said.")
    assert dialogue == "Go home,"
    assert narration == "He sat.   she said."


def test_said_share_with_mixed_tags():
    text = '"One," he said. "Two," she asked. "Three," Tomas said. "Four," replied Ines. "Five."'
    result = checks.analyze(text, 1200)
    # Four tagged lines (said, asked, said, replied); two of them "said".
    assert result["said_share"] == 0.5


def test_said_share_is_none_without_tags():
    assert checks.analyze('"Go." "No."', 1200)["said_share"] is None


def test_tag_adverbs_counts_ly_within_two_tokens_of_the_tag_verb():
    text = '"Hi," she said softly. "Bye," said Tomas quietly. "Fine," he said. She looked quickly away.'
    result = checks.analyze(text, 1200)
    words = result["words"]
    assert words == 15
    # "said softly" and "said Tomas quietly" count; "he said." and the later "quickly" do not.
    assert result["tag_adverbs"] == round(2 * 1000 / words, 3)


def test_contractions_in_narration_exclude_possessive_s_and_dialogue():
    text = "He didn't go; she'd see Tomas's boat and we'll never know. \"I can't,\" he said."
    result = checks.analyze(text, 1200)
    words = result["words"]
    # didn't, she'd, we'll are narration contractions; Tomas's is not; can't is dialogue.
    assert result["contractions_narration"] == round(3 * 1000 / words, 3)


def test_curly_apostrophe_contractions_count():
    result = checks.analyze("She didn’t stop.", 1200)
    assert result["contractions_narration"] == round(1 * 1000 / 3, 3)


def test_emdash_spaced_versus_closed():
    text = "One — two. Three--four. Five -- six. Seven—eight."
    result = checks.analyze(text, 1200)
    words = result["words"]
    assert result["emdash_spaced"] == round(2 * 1000 / words, 3)
    assert result["emdash_closed"] == round(1 * 1000 / words, 3)


def test_digits_below_ten_versus_numerals():
    result = checks.analyze("She had 4 casks, 11 crates and £12 4s owed, 7 days.", 1200)
    words = result["words"]
    assert words == 12
    # Standalone single digits: 4 and 7. Numeral runs: 4, 11, 12, 4, 7.
    assert result["digits_below_ten"] == round(2 * 1000 / words, 3)
    assert result["numerals"] == round(5 * 1000 / words, 3)


def test_long_sentence_share():
    long_sentence = " ".join(["word"] * 26) + "."
    text = f"Short one here. {long_sentence} Another short one."
    result = checks.analyze(text, 1200)
    assert result["long_sentence_share"] == round(1 / 3, 4)
    assert result["sentence_mean"] == round((3 + 26 + 3) / 3, 3)


def test_italic_spans_count_only_in_narration():
    text = 'She thought *not again* and _no_. "Do *not* go," he said. **Bold** is not italic.'
    result = checks.analyze(text, 1200)
    words = result["words"]
    # Two spans in narration; the one in dialogue and the bold are not counted.
    assert result["italic_spans"] == round(2 * 1000 / words, 3)


def test_has_markdown():
    assert checks.analyze("# Chapter\nText.", 1200)["has_markdown"] is True
    assert checks.analyze("Text.\n**Bold** start.", 1200)["has_markdown"] is True
    assert checks.analyze("Plain *text* only.", 1200)["has_markdown"] is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Here is the scene:\nShe sat.", True),
        ("Here's the scene.", True),
        ("Sure, here you go.", True),
        ("Certainly. She sat.", True),
        ("She sat. Here is a thing.", False),
        ("Surely not.", False),
    ],
)
def test_starts_with_preamble(text, expected):
    assert checks.analyze(text, 1200)["starts_with_preamble"] is expected


def test_target_ratio_and_emotion_words():
    result = checks.analyze("She felt cold and realized it. He couldn't help it.", 20)
    assert result["words"] == 10
    assert result["target_ratio"] == 0.5
    assert result["emotion_words"] == round(3 * 1000 / 10, 3)


# ---- report.py: the noise band --------------------------------------------------


def _write_run(root: Path, name: str, *, prompt_sha: str = "aaa", book_sha: str = "bbb", draft: str = "She sat.") -> Path:
    run = root / name
    folder = run / "frank" / "local" / "continue" / "quay_talk"
    folder.mkdir(parents=True)
    (folder / "draft_1.md").write_text(draft, encoding="utf-8")
    (folder / "meta_1.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    run_json = {
        "prompts": {"continue": {"id": "p1", "sha256": prompt_sha}},
        "book_yaml_sha256": book_sha,
        "models": [{"name": "local", "provider": "ollama"}],
    }
    (run / "run.json").write_text(json.dumps(run_json), encoding="utf-8")
    return run


def test_band_is_the_absolute_difference_between_the_two_runs(tmp_path):
    run_a = _write_run(tmp_path, "a", draft="She didn't stop. He didn't either.")
    run_b = _write_run(tmp_path, "b", draft="She stopped. He didn't either.")
    band = report.make_band(run_a, run_b)
    cell = band["cells"]["frank|local|continue|quay_talk"]
    # 2 contractions in 6 words vs 1 in 5 words, per 1000 words.
    assert cell["contractions_narration"] == 133.333


def test_band_refuses_when_prompt_sha256s_differ(tmp_path):
    run_a = _write_run(tmp_path, "a", prompt_sha="aaa")
    run_b = _write_run(tmp_path, "b", prompt_sha="zzz")
    with pytest.raises(SystemExit, match="prompts"):
        report.make_band(run_a, run_b)


def test_band_refuses_when_the_book_differs(tmp_path):
    run_a = _write_run(tmp_path, "a", book_sha="one")
    run_b = _write_run(tmp_path, "b", book_sha="two")
    with pytest.raises(SystemExit, match="book_yaml_sha256"):
        report.make_band(run_a, run_b)


def test_flag_only_when_the_difference_exceeds_the_band():
    assert report.flag_for("emotion_words", 1.0, 3.0, 0.5) == "worse"
    assert report.flag_for("emotion_words", 3.0, 1.0, 0.5) == "better"
    assert report.flag_for("emotion_words", 1.0, 1.4, 0.5) == ""
    assert report.flag_for("said_share", 0.2, 0.9, 0.1) == ""  # report-only: no direction


def test_style_dependent_mechanics_are_flagged_changed_never_better_or_worse():
    # The lush note wants italic thought, the hard-boiled one numerals: a move in a
    # mechanic is the judge's call against the note, not the script's.
    assert report.flag_for("italic_spans", 1.0, 5.0, 0.5) == "changed"
    assert report.flag_for("numerals", 5.0, 1.0, 0.5) == "changed"
    assert report.flag_for("italic_spans", 1.0, 1.2, 0.5) == ""


def test_sample_overlap_is_the_longest_shared_word_run():
    sample = "The column was short. She added it again from the bottom, the way her father had taught her."
    lifted = "Night. The column was short. She added it again from the bottom, and swore."
    assert checks.longest_shared_run(lifted, sample) == 11
    # Case and punctuation don't hide a copy; a couple of shared words is not one.
    assert checks.longest_shared_run("the COLUMN, was short", sample) == 4
    assert checks.analyze("She was short of money.", 1200, samples=[sample])["sample_overlap"] == 2  # "was short"
    assert checks.analyze(lifted, 1200, samples=[sample, "Unrelated words here."])["sample_overlap"] == 11
    assert checks.analyze(lifted, 1200)["sample_overlap"] == 0


def test_load_samples_reads_each_characters_sample_section(tmp_path):
    book = tmp_path / "book.yaml"
    book.write_text(
        "characters:\n"
        "  - key: a\n    body: |\n      Bio.\n\n      ## Sample\n      First sample.\n"
        "  - key: b\n    body: |\n      No sample here.\n",
        encoding="utf-8",
    )
    assert checks.load_samples(book) == ["First sample."]
