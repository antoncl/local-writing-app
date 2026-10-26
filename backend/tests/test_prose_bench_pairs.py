"""Blind pairs of the prose harness (#2617): the draw, the excerpt, the page and the tally.

Nothing here touches a backend or a model. The harness modules load by path.
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


sys.path.insert(0, str(_DIR))
pairs = _load("pairs")

BOOK = pairs.load_book()
BRIEFS = [s["key"] for s in BOOK["scenes"]][:4]
MODEL = "zorbax-primary"


def _text(tag: str, sentences: int = 80) -> str:
    return "\n\n".join(" ".join(f"The {tag}{i}{j} lamp burned. Then {tag}{i}{j} ledger lay open on the desk." for j in range(4)) for i in range(sentences // 4))


def _write_run(root: Path, tag: str, skip: tuple[str, str] | None = None, model: str = MODEL) -> Path:
    root.mkdir(parents=True)
    models = [{"name": model, "primary": True}, {"name": "other-model", "primary": False}]
    (root / "run.json").write_text(json.dumps({"models": models}), encoding="utf-8")
    for case in pairs.CASES:
        for brief in BRIEFS:
            if skip == (case, brief):
                continue
            folder = root / case / model / "draft_scene" / brief
            folder.mkdir(parents=True)
            for n in (1, 2):
                (folder / f"draft_{n}.md").write_text(_text(f"{tag}{case}{brief}{n}"), encoding="utf-8")
                (folder / f"meta_{n}.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    return root


@pytest.fixture
def runs(tmp_path):
    return _write_run(tmp_path / "runalpha", "base"), _write_run(tmp_path / "runomega", "fresh")


def _make(runs, out: Path, seed: int = 2617, cases: tuple[str, ...] | None = None) -> dict:
    pairs.make(runs[0], runs[1], out, 60, seed, None, *((cases,) if cases else ()))
    return json.loads((out / "key.json").read_text(encoding="utf-8"))


def test_cases_narrow_the_draw(runs, tmp_path):
    # #2621: 12 pairs (three styles x four briefs) instead of 20, for a shorter reading.
    key = _make(runs, tmp_path / "out", cases=("frank", "none", "lush"))
    assert len(key["pairs"]) == 12
    assert {p["case"] for p in key["pairs"].values()} == {"frank", "none", "lush"}
    html = (tmp_path / "out" / "send" / "pairs.html").read_text(encoding="utf-8")
    assert "the one that needs less of your work to become yours" in html


# --- sentences and excerpts ------------------------------------------------------


def test_sentences_split_with_quotes_and_keep_closers():
    para = 'He said, "Go home." She did not. "Why?" she asked. It rained… Then it stopped! ‘Fine.’ Done.'
    out = pairs.sentences(para)
    assert out == ['He said, "Go home."', "She did not.", '"Why?" she asked.', "It rained…", "Then it stopped!", "‘Fine.’", "Done."]
    assert " ".join(out) == para


def test_sentences_do_not_split_on_abbreviations():
    para = "Mr. Vey met Dr. Hale at St. Anne's. They talked."
    assert pairs.sentences(para) == ["Mr. Vey met Dr. Hale at St. Anne's.", "They talked."]


def test_sentences_rejoin_reproduces_paragraph():
    para = "One.   Two?  \"Three.\" Four"
    assert " ".join(pairs.sentences(para)) == " ".join(para.split())


def test_excerpt_stops_at_a_sentence_end_within_the_limit():
    text = "One two three. Four five six. Seven eight nine."
    assert pairs.excerpt(text, 6) == "One two three. Four five six."
    assert pairs.excerpt(text, 5) == "One two three."
    assert pairs.excerpt(text, 100) == text


def test_excerpt_takes_a_long_first_sentence_whole():
    text = "One two three four five six seven. Eight."
    assert pairs.excerpt(text, 3) == "One two three four five six seven."


def test_excerpt_keeps_paragraph_breaks():
    text = "One two. Three four.\n\nFive six. Seven eight."
    assert pairs.excerpt(text, 6) == "One two. Three four.\n\nFive six."
    assert pairs.excerpt(text, 4) == "One two. Three four."


# --- the draw ------------------------------------------------------------------


def test_draw_is_one_pair_per_cell_present_on_both_sides(runs):
    base, new = pairs.cells(runs[0], MODEL), pairs.cells(runs[1], MODEL)
    drawn, skipped = pairs.draw(base, new, 7)
    assert skipped == []
    assert len(drawn) == len(pairs.CASES) * len(BRIEFS) == 20
    assert {(p["case"], p["brief"]) for p in drawn} == {(c, b) for c in pairs.CASES for b in BRIEFS}
    assert all(p["baseline"]["text"].startswith("The base") and p["new"]["text"].startswith("The fresh") for p in drawn)
    assert {p["new_side"] for p in drawn} == {"A", "B"}


def test_draw_skips_and_reports_a_cell_missing_on_one_side(tmp_path, capsys):
    gap = ("wry", BRIEFS[1])
    base = _write_run(tmp_path / "ra", "base")
    new = _write_run(tmp_path / "rb", "fresh", skip=gap)
    out = tmp_path / "out"
    key = _make((base, new), out)
    assert len(key["pairs"]) == 19
    assert "skipped wry/" + BRIEFS[1] in capsys.readouterr().out


def test_draw_is_deterministic_for_a_seed(runs, tmp_path):
    a = _make(runs, tmp_path / "a")
    b = _make(runs, tmp_path / "b")
    assert a == b
    assert (tmp_path / "a" / "send" / "pairs.html").read_text(encoding="utf-8") == (
        tmp_path / "b" / "send" / "pairs.html"
    ).read_text(encoding="utf-8")
    other = _make(runs, tmp_path / "c", seed=1)
    assert other["page_id"] != a["page_id"]


def test_primary_models_must_match(tmp_path):
    base = _write_run(tmp_path / "ra", "base")
    new = _write_run(tmp_path / "rb", "fresh", model="different")
    with pytest.raises(SystemExit, match="primary models differ"):
        pairs.choose_model(base, new, None)
    assert pairs.choose_model(base, new, "x") == "x"


# --- the page does not leak the key -----------------------------------------------


def test_page_carries_nothing_of_the_key(runs, tmp_path):
    out = tmp_path / "out"
    _make(runs, out)
    # The page sits alone in the folder a reader is sent; the key stays one level up.
    assert sorted(p.name for p in (out / "send").iterdir()) == ["pairs.html"]
    html = (out / "send" / "pairs.html").read_text(encoding="utf-8")
    for token in ("runalpha", "runomega", MODEL, "other-model", '"new"', '"old"', '"baseline"', "draft_", "new_side", "key.json"):
        assert token not in html, token
    data = json.loads(html.split('id="pairs-data">', 1)[1].split("</script>", 1)[0])
    assert set(data) == {"page_id", "pairs"}
    assert set(data["pairs"][0]) == {"id", "pov", "summary", "A", "B"}
    assert [p["id"] for p in data["pairs"]][:2] == ["p01", "p02"]


def test_script_json_cannot_close_the_script_tag():
    blob = pairs.script_json({"t": "a </script><script>alert(1)</script> <!-- b"})
    assert "</script" not in blob and "<!--" not in blob
    assert json.loads(blob)["t"] == "a </script><script>alert(1)</script> <!-- b"


# --- the tally ---------------------------------------------------------------------


def test_sign_test():
    assert pairs.sign_test(15, 5) == pytest.approx(0.0414, abs=1e-4)
    assert pairs.sign_test(10, 10) == 1.0
    assert pairs.sign_test(0, 0) == 1.0
    assert pairs.sign_test(0, 5) == pytest.approx(0.0625)
    assert pairs.sign_test(5, 0) == pairs.sign_test(0, 5)


def _picks(key: dict, path: Path, reader: str = "ann", prefer: str = "new", cuts: dict | None = None, **over) -> Path:
    chosen = {}
    for pid, record in key["pairs"].items():
        other = "B" if record["new_side"] == "A" else "A"
        chosen[pid] = record["new_side"] if prefer == "new" else other
    doc = {"page_id": key["page_id"], "reader": reader, "picks": chosen, "cuts": cuts or {}, "saved_at": "x", **over}
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_tally_maps_picks_through_new_side(runs, tmp_path):
    key = _make(runs, tmp_path / "out")
    kp = tmp_path / "out" / "key.json"
    result = pairs.tally(kp, [_picks(key, tmp_path / "p1.json", "ann", "new")])
    assert "new 20, baseline 0, unanswered 0 (p = 0.000)" in result
    result = pairs.tally(kp, [_picks(key, tmp_path / "p2.json", "bob", "baseline")])
    assert "new 0, baseline 20, unanswered 0" in result
    pid = next(iter(key["pairs"]))
    partial = _picks(key, tmp_path / "p3.json", "cy")
    doc = json.loads(partial.read_text(encoding="utf-8"))
    del doc["picks"][pid]
    partial.write_text(json.dumps(doc), encoding="utf-8")
    both = pairs.tally(kp, [partial, tmp_path / "p2.json"])
    # One vote per pair: 19 pairs split 1-1 (tied, dropped); the pair cy skipped goes to bob.
    assert "new 0, baseline 1, tied 19, unanswered 0" in both
    assert "| cy | 19 | 0 | 1 |" in both and "| bob | 0 | 20 | 0 |" in both
    assert "| frank |" in both and "ann" not in both


def test_tally_refuses_a_different_page_unknown_pair_and_bad_pick(runs, tmp_path):
    key = _make(runs, tmp_path / "out")
    kp = tmp_path / "out" / "key.json"
    with pytest.raises(SystemExit, match="different page"):
        pairs.tally(kp, [_picks(key, tmp_path / "a.json", page_id="0" * 16)])
    bad = _picks(key, tmp_path / "b.json")
    doc = json.loads(bad.read_text(encoding="utf-8"))
    doc["picks"]["p99"] = "A"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(SystemExit, match="unknown pair p99"):
        pairs.tally(kp, [bad])
    doc["picks"].pop("p99")
    doc["picks"]["p01"] = "C"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(SystemExit, match="not A or B"):
        pairs.tally(kp, [bad])


def _cut_on(key: dict, pid: str, side: str) -> dict:
    return {pid: {"A": [[0, 1]] if side == "A" else [], "B": [[0, 1]] if side == "B" else []}}


def test_cut_sentences_map_to_the_right_side(runs, tmp_path):
    key = _make(runs, tmp_path / "out")
    kp = tmp_path / "out" / "key.json"
    new_pid = "p01"
    new_side = key["pairs"][new_pid]["new_side"]
    base_side = "B" if new_side == "A" else "A"
    cuts = {**_cut_on(key, new_pid, new_side), **_cut_on(key, "p02", "A" if key["pairs"]["p02"]["new_side"] == "B" else "B")}
    result = pairs.tally(kp, [_picks(key, tmp_path / "c.json", cuts=cuts)])
    assert "new side 1, baseline side 1" in result
    new_section = result.split("Cut on the new side", 1)[1].split("</details>", 1)[0]
    base_section = result.split("Cut on the baseline side", 1)[1].split("</details>", 1)[0]
    assert "fresh" in new_section and "base" not in new_section
    assert "base" in base_section and "fresh" not in base_section
    assert base_side != new_side


def test_cuts_come_from_the_key_not_the_sources(runs, tmp_path):
    key = _make(runs, tmp_path / "out")
    kp = tmp_path / "out" / "key.json"
    record = key["pairs"]["p01"]
    shown = record[record["new_side"]][0][1]
    # A source edited (or a splitter changed) after the page was made can't move a cut.
    (Path(key["new_run"]) / record["new"]).write_text("Rewritten entirely.", encoding="utf-8")
    result = pairs.tally(kp, [_picks(key, tmp_path / "c.json", cuts=_cut_on(key, "p01", record["new_side"]))])
    assert shown in result.split("Cut on the new side", 1)[1]


def test_majority_vote_per_pair(runs, tmp_path):
    key = _make(runs, tmp_path / "out")
    kp = tmp_path / "out" / "key.json"
    files = [
        _picks(key, tmp_path / "1.json", "ann", "new"),
        _picks(key, tmp_path / "2.json", "bob", "new"),
        _picks(key, tmp_path / "3.json", "cy", "baseline"),
    ]
    result = pairs.tally(kp, files)
    assert "new 20, baseline 0, unanswered 0" in result
    assert "side most readers kept" in result


def test_two_files_from_one_reader_are_refused(runs, tmp_path):
    key = _make(runs, tmp_path / "out")
    kp = tmp_path / "out" / "key.json"
    first = _picks(key, tmp_path / "early.json", "Anton")
    later = _picks(key, tmp_path / "late.json", "anton ")
    with pytest.raises(SystemExit, match="same reader"):
        pairs.tally(kp, [first, later])
    unnamed = [_picks(key, tmp_path / f"u{i}.json", "") for i in (1, 2)]
    with pytest.raises(SystemExit, match="same reader"):
        pairs.tally(kp, unnamed)
