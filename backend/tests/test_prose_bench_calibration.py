"""Seeding, the interleaved sheet, ownership and the reading page of the prose harness (#2615).

Nothing here touches a backend or a model. The harness modules load by path (as
test_prose_bench_judge.py does); the page's server is driven on port 0 in a thread.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

_DIR = Path(__file__).resolve().parents[2] / "scripts" / "benchmark" / "prose"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"prose_bench_{name}", _DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(_DIR))
judge = _load("judge")
calibration = _load("calibration")
seed = _load("calibration_seed")
serve = _load("calibration_serve")
setup_backend = _load("setup_backend")

BOOK = serve.load_book()
BRIEF = BOOK["continue_cases"][0]["key"]


# --- the seeder ----------------------------------------------------------------


def test_every_rule_has_a_seed_instruction_and_no_other():
    assert set(seed.SEED_INSTRUCTIONS) == set(judge.RULES)


def test_clean_seed_strips_fences_and_wrapping_quotes():
    assert seed.clean_seed("```\nShe ran.\n```") == "She ran."
    assert seed.clean_seed("```text\nShe ran.\nHe fell.\n```") == "She ran.\nHe fell."
    assert seed.clean_seed('"She ran."') == "She ran."
    assert seed.clean_seed("“She ran.”") == "She ran."


def test_clean_seed_keeps_a_passage_that_is_dialogue():
    text = '"Go," she said. "Now."'
    assert seed.clean_seed(text) == text


def test_seed_problem():
    source = " ".join(["word"] * 100)
    assert seed.seed_problem(source, source + " extra") is None
    assert seed.seed_problem(source, "") == "empty reply"
    assert seed.seed_problem(source, source + "\n") == "identical to the source"
    assert "outside" in seed.seed_problem(source, " ".join(["w"] * 40))
    assert "outside" in seed.seed_problem(source, " ".join(["w"] * 201))
    assert seed.seed_problem(source, " ".join(["word"] * 80)) is None
    assert seed.seed_problem(source, " ".join(["word"] * 200)) is None


def test_seed_problem_flags_deleted_source_words():
    words = [f"w{i}" for i in range(100)]
    source = " ".join(words)
    assert seed.seed_problem(source, " ".join([*words[:75], "added", "words"])) is None  # 25 removed
    assert seed.seed_problem(source, " ".join([*words[:74], *["added"] * 20])) == "deleted 26 words of the source"
    closing_paragraph_gone = " ".join([*words[:60], *words[90:], *["more"] * 30])
    assert seed.seed_problem(source, closing_paragraph_gone) == "deleted 30 words of the source"


def test_seeder_conflict_with_a_judge_or_a_drafter():
    judges = {"primary": {"model": "g/flash"}, "second": {"model": "d/flash"}}
    drafters = [{"model": "o/drafter"}]
    assert seed.seeder_conflict("s/pro", judges, drafters) is None
    assert "judge" in seed.seeder_conflict("d/flash", judges, drafters)
    assert "drafter" in seed.seeder_conflict("o/drafter", judges, drafters)


def test_plan_seeds_is_distinct_deterministic_and_numbers_from_100():
    candidates = [{"case": "frank", "model": "m", "brief": BRIEF, "n": n, "text": "t"} for n in range(1, 13)]
    plan = seed.plan_seeds(candidates, 2, 7)
    assert plan == seed.plan_seeds(candidates, 2, 7)
    assert len({id(e["source"]) for e in plan}) == 12
    assert [e["rule"] for e in plan] == [r for r in judge.RULES for _ in range(2)]
    assert sorted(e["n"] for e in plan) == list(range(100, 112))


def test_plan_seeds_limits_rules_and_numbers_after_existing_drafts():
    candidates = [{"case": "frank", "model": "m", "brief": BRIEF, "n": n, "text": "t"} for n in range(1, 13)]
    rules = ["time_skip", "summing_up_ending"]
    taken = {("frank", "m", BRIEF): 105}
    plan = seed.plan_seeds(candidates, 2, 7, rules, taken)
    assert plan == seed.plan_seeds(candidates, 2, 7, rules, taken)
    assert [e["rule"] for e in plan] == ["time_skip"] * 2 + ["summing_up_ending"] * 2
    assert sorted(e["n"] for e in plan) == [106, 107, 108, 109]


def test_highest_drafts_reads_the_out_folder(tmp_path):
    source = {"case": "frank", "model": "m", "brief": BRIEF, "n": 1}
    seed.write_seed(tmp_path, {"rule": "time_skip", "n": 103, "source": source}, "x", {"status": "ok"}, tmp_path, "s/m")
    assert seed.highest_drafts(tmp_path) == {("frank", "m", BRIEF): 103}
    assert seed.highest_drafts(tmp_path / "none") == {}


def test_a_rerun_skips_seeds_already_written_ok(tmp_path):
    candidates = [{"case": "frank", "model": "m", "brief": BRIEF, "n": n, "text": "t"} for n in range(1, 13)]
    done, failed, *rest = seed.plan_seeds(candidates, 2, 7)
    seed.write_seed(tmp_path, done, "x", {"status": "ok"}, tmp_path, "s/model")
    seed.write_seed(tmp_path, failed, "", {"status": "error", "error": "empty reply"}, tmp_path, "s/model")
    assert seed.seeded_ok(tmp_path, done)
    assert not seed.seeded_ok(tmp_path, failed)
    assert not any(seed.seeded_ok(tmp_path, e) for e in rest)


def _candidates(count: int = 12) -> list[dict]:
    return [{"case": "frank", "model": "m", "brief": BRIEF, "n": n, "text": "t"} for n in range(1, count + 1)]


def _write_plan(out: Path, plan: list[dict]) -> None:
    for entry in plan:
        seed.write_seed(out, entry, "x", {"status": "ok"}, out, "s/model")


def test_seeded_sources_lists_every_meta_any_status_and_can_skip_rules(tmp_path):
    ok, failed, *_ = seed.plan_seeds(_candidates(), 1, 7, ["time_skip", "viewpoint_slip"])
    seed.write_seed(tmp_path, ok, "x", {"status": "ok"}, tmp_path, "s/model")
    seed.write_seed(tmp_path, failed, "", {"status": "error"}, tmp_path, "s/model")
    both = {seed.source_address(ok["source"]), seed.source_address(failed["source"])}
    assert seed.seeded_sources(tmp_path) == both
    assert seed.seeded_sources(tmp_path, [ok["rule"]]) == {seed.source_address(failed["source"])}
    assert seed.seeded_sources(tmp_path / "none") == set()


def test_a_second_run_with_other_rules_never_reuses_a_source_and_a_rerun_plans_nothing(tmp_path):
    first_rules, second_rules = ["time_skip", "summing_up_ending"], ["viewpoint_slip", "narration_euphemism"]
    first = seed.plan_run(_candidates(), tmp_path, 2, 7, first_rules)
    assert len(first) == 4
    _write_plan(tmp_path, first)
    used = seed.seeded_sources(tmp_path)
    second = seed.plan_run(_candidates(), tmp_path, 2, 7, second_rules)
    assert len(second) == 4 and not used & {seed.source_address(e["source"]) for e in second}
    _write_plan(tmp_path, second)
    assert seed.plan_run(_candidates(), tmp_path, 2, 7, second_rules) == []
    assert seed.plan_run(_candidates(), tmp_path, 2, 7, first_rules) == []


def test_run_json_merges_models_and_source_paths():
    run = {"models": [{"name": "a", "model": "x/a"}], "prompts": 1}
    first = seed.merge_run_json(None, run, Path("/src1"), "s/model")
    assert first["seeded_from"] == [str(Path("/src1"))] and first["models"] == run["models"]
    other = {"models": [{"name": "a", "model": "x/a"}, {"name": "b", "model": "x/b"}]}
    merged = seed.merge_run_json(first, other, Path("/src2"), "s/model")
    assert [m["name"] for m in merged["models"]] == ["a", "b"] and merged["prompts"] == 1
    assert merged["seeded_from"] == [str(Path("/src1")), str(Path("/src2"))]
    again = seed.merge_run_json(merged, other, Path("/src2"), "s/model")
    assert again["seeded_from"] == merged["seeded_from"] and again["models"] == merged["models"]
    old = seed.merge_run_json({**first, "seeded_from": "/old"}, run, Path("/src2"), "s/model")
    assert old["seeded_from"] == ["/old", str(Path("/src2"))]
    with pytest.raises(SystemExit):
        seed.merge_run_json(merged, {"models": [{"name": "a", "model": "x/other"}]}, Path("/src3"), "s/model")


def test_plan_seeds_exits_when_there_are_too_few():
    with pytest.raises(SystemExit):
        seed.plan_seeds([{"case": "frank", "model": "m", "brief": BRIEF, "n": 1}], 2, 7)


def test_seed_message_names_the_viewpoint_and_the_instruction():
    message = seed.seed_message("Ines", "Lead.", " Passage. ", "viewpoint_slip")
    assert "Viewpoint character: Ines" in message and "Passage to edit:\nPassage." in message
    assert "other than Ines" in message


def test_load_seeder(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text("models:\n  - {name: a}\n", encoding="utf-8")
    assert setup_backend.load_seeder(path) is None
    path.write_text("models:\n  - {name: a}\nseeder: {name: s, model: x/y}\n", encoding="utf-8")
    assert setup_backend.load_seeder(path) == {"name": "s", "model": "x/y"}


# --- the sheet -----------------------------------------------------------------


def _make_run(root: Path, name: str, count: int, first_n: int = 1, seeded: bool = False) -> Path:
    run = root / name
    folder = run / "frank" / "m" / "continue" / BRIEF
    folder.mkdir(parents=True, exist_ok=True)
    for n in range(first_n, first_n + count):
        (folder / f"draft_{n}.md").write_text(f"Passage {n}.\n\nSecond paragraph.", encoding="utf-8")
        meta = {"status": "ok", **({"seeded_rule": "time_skip", "source": "x"} if seeded else {})}
        (folder / f"meta_{n}.json").write_text(json.dumps(meta), encoding="utf-8")
    return run


def _sheet(tmp_path: Path, seed_value: int = 5) -> Path:
    natural = _make_run(tmp_path, "natural", 3)
    seeded = _make_run(tmp_path, "seeded", 3, first_n=100, seeded=True)
    out = tmp_path / f"sheet{seed_value}"
    calibration.make_sheet(natural, seeded, out, 0, None, seed_value)
    return out


def test_natural_continuations_default_to_the_seeded_count(tmp_path):
    natural = _make_run(tmp_path, "natural", 6)
    seeded = _make_run(tmp_path, "seeded", 2, first_n=100, seeded=True)
    calibration.make_sheet(natural, seeded, tmp_path / "out", 0, None, 5)
    items = yaml.safe_load((tmp_path / "out" / "answers.yaml").read_text(encoding="utf-8"))["items"]
    assert sum(not i["seeded"] for i in items) == 2


def test_a_sheet_with_answers_is_never_overwritten(tmp_path):
    out = _sheet(tmp_path)
    doc = yaml.safe_load((out / "answers.yaml").read_text(encoding="utf-8"))
    doc["items"][0]["answers"]["time_skip"] = "no"
    (out / "answers.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    with pytest.raises(SystemExit):
        calibration.make_sheet(tmp_path / "natural", tmp_path / "seeded", out, 0, None, 5)
    assert yaml.safe_load((out / "answers.yaml").read_text(encoding="utf-8")) == doc


def test_sheet_interleaves_seeded_and_natural_deterministically(tmp_path):
    first = yaml.safe_load((_sheet(tmp_path, 5) / "answers.yaml").read_text(encoding="utf-8"))
    again = yaml.safe_load((_sheet(tmp_path, 5) / "answers.yaml").read_text(encoding="utf-8"))
    assert first == again
    items = first["items"]
    assert [i["id"] for i in items] == [f"d0{k}" for k in range(1, 7)]
    flags = [i["seeded"] for i in items]
    assert sum(flags) == 3
    assert flags != sorted(flags) and flags != sorted(flags, reverse=True)
    other = yaml.safe_load((_sheet(tmp_path, 6) / "answers.yaml").read_text(encoding="utf-8"))["items"]
    assert [i["seeded"] for i in other] != flags or [i["n"] for i in other] != [i["n"] for i in items]


def test_sheet_records_each_items_own_run_and_a_blank_note(tmp_path):
    doc = yaml.safe_load((_sheet(tmp_path) / "answers.yaml").read_text(encoding="utf-8"))
    assert doc["run"] == str((tmp_path / "natural").resolve())
    for item in doc["items"]:
        assert item["run"] == str((tmp_path / ("seeded" if item["seeded"] else "natural")).resolve())
        assert item["note"] == ""
        assert item.get("seeded_rule") == ("time_skip" if item["seeded"] else None)


def test_sheet_markdown_does_not_reveal_seeding(tmp_path):
    text = (_sheet(tmp_path) / "sheet.md").read_text(encoding="utf-8").lower()
    assert "seeded" not in text and "time_skip" in text  # the rule questions are shown, the rule key only as a label
    assert "## d01" in text


def test_extend_appends_keeps_answers_and_continues_ids(tmp_path):
    out = _sheet(tmp_path)
    doc = yaml.safe_load((out / "answers.yaml").read_text(encoding="utf-8"))
    doc["items"][0]["answers"]["time_skip"] = "yes"
    doc["items"][0]["note"] = "mine"
    (out / "answers.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    natural = _make_run(tmp_path, "natural", 5)  # drafts 1-3 are on the sheet, 4-5 are new
    seeded = _make_run(tmp_path, "seeded", 2, first_n=200, seeded=True)  # 100-102 are on the sheet
    assert calibration.extend_sheet(out, natural, seeded, 2, 9) == (2, 2)
    after = yaml.safe_load((out / "answers.yaml").read_text(encoding="utf-8"))
    assert after["items"][:6] == doc["items"]
    new = after["items"][6:]
    assert [i["id"] for i in new] == ["d07", "d08", "d09", "d10"]
    assert sorted(i["n"] for i in new) == [4, 5, 200, 201]
    assert sum(i["seeded"] for i in new) == 2 and not any(any(i["answers"].values()) for i in new)
    addresses = [(i["run"], i["n"]) for i in after["items"]]
    assert len(set(addresses)) == len(addresses)
    text = (out / "sheet.md").read_text(encoding="utf-8")
    assert "## d10" in text and "## d01" in text and "seeded" not in text.lower()
    assert calibration.extend_sheet(out, natural, seeded, 0, 9) == (0, 0)  # nothing new is left to add
    assert len(yaml.safe_load((out / "answers.yaml").read_text(encoding="utf-8"))["items"]) == 10


def test_extend_refuses_while_the_reading_page_is_serving(tmp_path):
    out = _sheet(tmp_path)
    (out / serve.SERVING).write_text("{}", encoding="utf-8")
    before = (out / "answers.yaml").read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="stop it first"):
        calibration.extend_sheet(out, _make_run(tmp_path, "natural", 5), _make_run(tmp_path, "seeded", 2, 200, True), 2, 9)
    assert (out / "answers.yaml").read_text(encoding="utf-8") == before


def test_extend_refuses_more_natural_drafts_than_remain(tmp_path):
    out = _sheet(tmp_path)  # the natural run has 3 drafts, all on the sheet
    with pytest.raises(SystemExit):
        calibration.extend_sheet(out, tmp_path / "natural", tmp_path / "seeded", 1, 9)


def test_the_reading_page_picks_up_appended_items(tmp_path):
    out = _sheet(tmp_path)
    natural = _make_run(tmp_path, "natural", 4)
    calibration.extend_sheet(out, natural, tmp_path / "seeded", 1, 9)
    store = serve.Store(out)
    assert store.listing()["total"] == 7 and store.payload("d07")["id"] == "d07"


# --- ownership -----------------------------------------------------------------


def _stats(present_n: int, present_agree, absent_n: int = 0, absent_agree=None):
    return {"present_n": present_n, "present_agree": present_agree, "absent_n": absent_n, "absent_agree": absent_agree}


POOLED = _stats(10, 0.9, 10, 0.9)
SEEDED = _stats(8, 0.9)
NATURAL = _stats(2, 1.0)


def test_owns_rule_when_every_clause_holds():
    assert calibration.owns_rule(POOLED, SEEDED, NATURAL) is True


def test_owns_rule_without_natural_present_cases():
    assert calibration.owns_rule(POOLED, SEEDED, _stats(0, None)) is True


def test_owns_rule_fails_on_each_clause_alone():
    assert not calibration.owns_rule(_stats(10, 0.9, 10, 0.7), SEEDED, NATURAL)  # absent agreement
    assert not calibration.owns_rule(_stats(10, 0.7, 10, 0.9), SEEDED, NATURAL)  # pooled present agreement
    assert not calibration.owns_rule(_stats(7, 1.0, 10, 0.9), SEEDED, NATURAL)  # too few present
    assert not calibration.owns_rule(_stats(10, 0.9, 7, 1.0), SEEDED, NATURAL)  # too few absent
    assert not calibration.owns_rule(POOLED, _stats(8, 0.5), NATURAL)  # misses the planted failures
    assert not calibration.owns_rule(POOLED, _stats(0, None), NATURAL)  # nothing planted
    assert not calibration.owns_rule(POOLED, SEEDED, _stats(3, 0.5))  # misses a natural one the writer found


def _judged_run(root: Path, name: str, answer: str) -> Path:
    run = _make_run(root, name, 1)
    folder = run / "frank" / "m" / "continue" / BRIEF
    record = {"judge": "primary", "judge_model": "g/flash", "rules": {"time_skip": {"answer": answer}}}
    (folder / "judge_1.json").write_text(json.dumps(record), encoding="utf-8")
    return run


def test_tally_skips_answers_to_a_reworded_question_and_counts_unfingerprinted_ones(tmp_path):
    natural = _judged_run(tmp_path, "nat", "no")
    base = {"case": "frank", "model": "m", "prompt": "continue", "brief": BRIEF, "n": 1, "run": str(natural), "seeded": False}
    current = judge.question_sha(judge.RULES["time_skip"])
    items = [
        {**base, "answers": {"time_skip": "no"}, "question_sha": {"time_skip": current}},
        {**base, "answers": {"time_skip": "yes"}, "question_sha": {"time_skip": "000000000000"}},
        {**base, "answers": {"time_skip": "no"}},
    ]
    path = tmp_path / "answers.yaml"
    path.write_text(yaml.safe_dump({"run": str(natural), "items": items}), encoding="utf-8")
    result = calibration.tally(path)
    stats = result["judges"]["g/flash"]["time_skip"]
    assert (stats["absent_n"], stats["present_n"]) == (2, 0)  # the stale yes is not counted
    assert result["pre_fingerprint_answers"] == {"time_skip": 1}


def test_tally_reads_each_items_run_and_skips_unsure_and_blank(tmp_path):
    natural, seeded = _judged_run(tmp_path, "nat", "no"), _judged_run(tmp_path, "seed", "yes")
    base = {"case": "frank", "model": "m", "prompt": "continue", "brief": BRIEF, "n": 1}
    items = [
        {**base, "run": str(seeded), "seeded": True, "answers": {"time_skip": "yes", "viewpoint_slip": "unsure"}},
        {**base, "run": str(natural), "seeded": False, "answers": {"time_skip": "yes"}},
        {**base, "run": str(natural), "seeded": False, "answers": {"time_skip": "unsure"}},
        {**base, "run": str(natural), "seeded": False, "answers": {"time_skip": None}},
    ]
    path = tmp_path / "answers.yaml"
    path.write_text(yaml.safe_dump({"run": str(natural), "items": items}), encoding="utf-8")
    stats = calibration.tally(path)["judges"]["g/flash"]["time_skip"]
    assert (stats["seeded_present_n"], stats["seeded_present_agree"]) == (1, 1.0)
    assert (stats["natural_present_n"], stats["natural_present_agree"]) == (1, 0.0)
    assert stats["present_n"] == 2 and stats["absent_n"] == 0 and stats["owned"] is False
    assert "viewpoint_slip" not in calibration.tally(path)["judges"]["g/flash"]
    assert "seeded present" in calibration.render_table(calibration.tally(path))


# --- the reading page ----------------------------------------------------------

FORBIDDEN = {"seeded", "seeded_rule", "model", "case", "brief", "run", "judge", "rules", "n", "prompt"}


def _item(**extra):
    return {"id": "d01", "case": "frank", "model": "m", "prompt": "continue", "brief": BRIEF, "n": 100,
            "run": "/x", "seeded": True, "seeded_rule": "time_skip", "answers": dict.fromkeys(judge.RULES),
            "note": "", **extra}


def test_item_payload_never_carries_seeding_or_provenance():
    payload = serve.item_payload(_item(), BOOK, "Some text.\n")
    assert set(payload) == {"id", "kind", "pov", "context", "text", "questions", "answers", "note"}
    assert not FORBIDDEN & set(payload)
    assert payload["kind"] == "continuation" and payload["text"] == "Some text."
    assert [q["rule"] for q in payload["questions"]] == list(judge.RULES)
    assert "seeded" not in json.dumps(payload) and "time_skip" in json.dumps(payload["questions"])


def test_item_payload_for_a_scene_shows_the_brief_summary():
    scene = BOOK["scenes"][0]
    payload = serve.item_payload(_item(prompt="draft_scene", brief=scene["key"]), BOOK, "t")
    assert payload["kind"] == "scene" and payload["context"] == scene["summary"].strip()


def test_apply_answer_records_the_question_wording_and_clears_it_with_the_answer():
    doc = {"items": [_item()]}
    out = serve.apply_answer(doc, "d01", {"answers": {"time_skip": "yes", "viewpoint_slip": "unsure"}})
    sha = out["items"][0]["question_sha"]
    assert sha == {r: judge.question_sha(judge.RULES[r]) for r in ("time_skip", "viewpoint_slip")}
    cleared = serve.apply_answer(out, "d01", {"answers": {"time_skip": None}})
    assert list(cleared["items"][0]["question_sha"]) == ["viewpoint_slip"]
    assert "question_sha" not in doc["items"][0]


def test_request_allowed():
    ok = {"Host": "127.0.0.1:8123", "Origin": "http://localhost:8123", "Content-Type": "application/json; charset=utf-8"}
    assert serve.request_allowed("POST", ok, 8123)
    assert serve.request_allowed("POST", {k: v for k, v in ok.items() if k != "Origin"}, 8123)
    assert serve.request_allowed("GET", {"Host": "localhost:8123"}, 8123)
    assert not serve.request_allowed("GET", {"Host": "evil.example:8123"}, 8123)  # DNS rebinding
    assert not serve.request_allowed("GET", {}, 8123)
    assert not serve.request_allowed("GET", {"Host": "127.0.0.1:9"}, 8123)
    assert not serve.request_allowed("POST", {**ok, "Host": "evil.example"}, 8123)
    assert not serve.request_allowed("POST", {**ok, "Origin": "http://evil.example"}, 8123)
    assert not serve.request_allowed("POST", {**ok, "Content-Type": "text/plain"}, 8123)
    assert not serve.request_allowed("POST", {"Host": ok["Host"]}, 8123)


def test_a_missing_draft_file_is_a_500_with_the_path(tmp_path):
    out = _sheet(tmp_path)
    store = serve.Store(out)
    for run in ("natural", "seeded"):
        for draft in (tmp_path / run).rglob("draft_*.md"):
            draft.unlink()
    status, body = serve.route_get(store, "/api/items/d01")
    assert status == 500 and body["error"].startswith("draft file missing: ") and "draft_" in body["error"]


def test_item_status():
    answers = dict.fromkeys(judge.RULES)
    assert serve.item_status({"answers": answers}) == "untouched"
    assert serve.item_status({"answers": {**answers, "time_skip": "no"}}) == "partial"
    assert serve.item_status({"answers": dict.fromkeys(judge.RULES, "unsure")}) == "done"
    assert serve.item_status({"answers": {**dict.fromkeys(judge.RULES, "yes"), "time_skip": None}}) == "partial"


def test_apply_answer_accepts_valid_values_and_leaves_the_input_alone():
    doc = {"items": [_item()]}
    out = serve.apply_answer(doc, "d01", {"answers": {"time_skip": "yes", "viewpoint_slip": "unsure"}, "note": "hm"})
    assert out["items"][0]["answers"]["time_skip"] == "yes"
    assert out["items"][0]["answers"]["viewpoint_slip"] == "unsure" and out["items"][0]["note"] == "hm"
    assert doc["items"][0]["answers"]["time_skip"] is None
    cleared = serve.apply_answer(out, "d01", {"answers": {"time_skip": None}})
    assert cleared["items"][0]["answers"]["time_skip"] is None and cleared["items"][0]["note"] == "hm"
    assert serve.apply_answer(doc, "d01", {"answers": {"time_skip": "no"}})["items"][0]["answers"]["time_skip"] == "no"


@pytest.mark.parametrize("item_id,payload", [
    ("d99", {"answers": {}}),
    ("d01", {"answers": {"nope": "yes"}}),
    ("d01", {"answers": {"time_skip": "maybe"}}),
    ("d01", {"answers": {"time_skip": True}}),
    ("d01", {"answers": [], "note": ""}),
    ("d01", {"note": 3}),
])
def test_apply_answer_rejects_bad_input(item_id, payload):
    with pytest.raises(ValueError):
        serve.apply_answer({"items": [_item()]}, item_id, payload)


def _request(url: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.status, response.read()


def test_the_server_lists_saves_atomically_and_hides_seeding(tmp_path):
    sheet = _sheet(tmp_path)
    server = serve.make_server(sheet, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert server.server_address[0] == "127.0.0.1"
        base = f"http://127.0.0.1:{server.server_address[1]}"
        status, body = _request(base + "/api/items")
        listing = json.loads(body)
        assert status == 200 and listing["total"] == 6 and listing["done"] == 0
        assert {i["status"] for i in listing["items"]} == {"untouched"}
        assert b"<html" in _request(base + "/")[1]
        item = json.loads(_request(base + "/api/items/d01")[1])
        assert not FORBIDDEN & set(item)
        _, posted = _request(base + "/api/items/d01", {"answers": {"time_skip": "yes"}, "note": "n"})
        assert json.loads(posted) == {"status": "partial"}
        with pytest.raises(urllib.error.HTTPError) as bad:
            _request(base + "/api/items/d01", {"answers": {"time_skip": "maybe"}})
        assert bad.value.code == 400
        with pytest.raises(urllib.error.HTTPError) as missing:
            _request(base + "/api/items/d99")
        assert missing.value.code == 404
        foreign = urllib.request.Request(base + "/api/items", headers={"Host": "evil.example"})
        with pytest.raises(urllib.error.HTTPError) as rebound:
            urllib.request.urlopen(foreign, timeout=10)
        assert rebound.value.code == 403
        plain = urllib.request.Request(base + "/api/items/d01", data=b"{}", headers={"Content-Type": "text/plain"})
        with pytest.raises(urllib.error.HTTPError) as form:
            urllib.request.urlopen(plain, timeout=10)
        assert form.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
    doc = yaml.safe_load((sheet / "answers.yaml").read_text(encoding="utf-8"))
    assert doc["items"][0]["answers"]["time_skip"] == "yes" and doc["items"][0]["note"] == "n"
    assert [p.name for p in sheet.iterdir()] == ["answers.yaml", "sheet.md"]
