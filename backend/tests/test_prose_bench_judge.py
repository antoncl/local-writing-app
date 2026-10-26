"""Rules for the prose harness's model judge, calibration and judge-aware report (#2615).

Nothing here touches a backend or a model (`judge.ask` is replaced in the judge_item tests). The harness lives
under scripts/benchmark/prose/, so its modules load by path (as
test_prose_bench_checks.py does).
"""

from __future__ import annotations

import argparse
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


# The harness modules import each other by plain name from their own folder.
sys.path.insert(0, str(_DIR))
judge = _load("judge")
calibration = _load("calibration")
report = _load("report")

JUDGES = {"primary": {"name": "jp", "model": "g/flash"}, "second": {"name": "js", "model": "d/flash"}}


# --- parse_verdict -----------------------------------------------------------


def test_parse_verdict_clean_json():
    assert judge.parse_verdict('{"answer": "Yes", "quote": "she knew"}') == {"answer": "yes", "quote": "she knew"}


def test_parse_verdict_fenced_and_surrounded_by_prose():
    text = 'Sure, here you go:\n```json\n{"answer": " NO ", "quote": ""}\n```\nHope that helps.'
    assert judge.parse_verdict(text) == {"answer": "no", "quote": ""}


def test_parse_verdict_bad_answer_is_unparsed():
    verdict = judge.parse_verdict('{"answer": "maybe", "quote": "x"}')
    assert verdict["answer"] == "unparsed"
    assert "maybe" in verdict["raw"]


def test_parse_verdict_no_json_is_unparsed():
    assert judge.parse_verdict("I think so.")["answer"] == "unparsed"


def test_parse_verdict_reads_the_answer_from_broken_json():
    # #2623: a quote with an unescaped quotation mark broke the JSON; the answer still stands.
    broken = '```json\n{"answer": "C", "quote": "\\"Like dat, yeh are.""}\n```'
    assert judge.parse_verdict(broken, ("A", "B", "C", "D")) == {"answer": "C", "quote": ""}
    assert judge.parse_verdict('{"answer": "maybe", "quote": "x""}')["answer"] == "unparsed"


def test_parse_verdict_separation_choices():
    assert judge.parse_verdict('{"answer": "b", "quote": "q"}', ("A", "B"))["answer"] == "B"
    assert judge.parse_verdict('{"answer": "yes"}', ("A", "B"))["answer"] == "unparsed"


# --- routing -----------------------------------------------------------------


def test_pick_judge_primary_for_other_models():
    assert judge.pick_judge("anthropic/sonnet", JUDGES) == "primary"


def test_pick_judge_own_model_goes_to_second():
    assert judge.pick_judge("g/flash", JUDGES) == "second"


def test_pick_judge_exits_when_both_are_the_drafter():
    same = {"primary": {"model": "g/flash"}, "second": {"model": "g/flash"}}
    with pytest.raises(SystemExit):
        judge.pick_judge("g/flash", same)


def test_pick_judge_exits_without_a_second_when_needed():
    with pytest.raises(SystemExit):
        judge.pick_judge("g/flash", {"primary": {"model": "g/flash"}})


# --- separation --------------------------------------------------------------


def test_every_brief_meets_all_three_other_styles():
    for case in judge.STYLED:
        partners = [judge.separation_partner(case, n) for n in (1, 2, 3)]
        assert sorted(partners) == sorted(c for c in judge.STYLED if c != case)


def test_partner_is_the_ring_step_ahead():
    assert judge.separation_partner("frank", 1) == "lush"
    assert judge.separation_partner("wry", 1) == "frank"
    assert judge.separation_partner("lush", 3) == "frank"


def test_separation_order_is_deterministic_and_mixed():
    assert judge.separation_order("frank", "m", "short_column", 1) == judge.separation_order("frank", "m", "short_column", 1)
    seen = {judge.separation_order("frank", "m", "short_column", n) for n in range(1, 40)}
    assert seen == {True, False}


# --- calibration -------------------------------------------------------------


def _pairs(present_yes: int, present_n: int, absent_no: int, absent_n: int):
    return (
        [("yes", "yes")] * present_yes + [("yes", "no")] * (present_n - present_yes)
        + [("no", "no")] * absent_no + [("no", "yes")] * (absent_n - absent_no)
    )


def _owned(pairs):
    """Ownership with every pair counted as both pooled and seeded, and no natural cases."""
    stats = calibration.rule_agreement(pairs)
    return calibration.owns_rule(stats, stats, calibration.rule_agreement([]))


def test_rule_agreement_owned_at_exactly_the_thresholds():
    result = calibration.rule_agreement(_pairs(8, 10, 8, 10))
    assert (result["present_n"], result["absent_n"]) == (10, 10)
    assert result["present_agree"] == 0.8 and result["absent_agree"] == 0.8
    assert _owned(_pairs(8, 10, 8, 10)) is True


def test_rule_agreement_just_under_agreement_is_not_owned():
    assert _owned(_pairs(7, 9, 10, 10)) is False


def test_rule_agreement_seven_present_is_not_owned():
    assert _owned(_pairs(7, 7, 10, 10)) is False


def test_judge_that_always_says_no_fails_on_present():
    result = calibration.rule_agreement([("yes", "no")] * 8 + [("no", "no")] * 8)
    assert result["present_agree"] == 0.0 and result["absent_agree"] == 1.0
    assert _owned([("yes", "no")] * 8 + [("no", "no")] * 8) is False


def test_unparsed_error_and_missing_count_as_disagreement():
    result = calibration.rule_agreement([("yes", "unparsed"), ("yes", "error"), ("no", "missing"), ("no", "no")])
    assert result["present_agree"] == 0.0 and result["absent_agree"] == 0.5


def _write_run(tmp_path: Path, judge_model: str, rules: dict[str, str], seeded: bool = False) -> Path:
    run = tmp_path / "run"
    folder = run / "frank" / "m" / "draft_scene" / "short_column"
    folder.mkdir(parents=True)
    (folder / "draft_1.md").write_text("Ines added the column again.", encoding="utf-8")
    (folder / "meta_1.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    record = {
        "judge": "primary", "judge_model": judge_model,
        "rules": {r: {"answer": a, "quote": ""} for r, a in rules.items()},
        "separation": {"answer": "A", "correct": False},
    }
    (folder / "judge_1.json").write_text(json.dumps(record), encoding="utf-8")
    return run


def test_tally_splits_seeded_items(tmp_path):
    run = _write_run(tmp_path, "g/flash", {"time_skip": "yes"})
    items = [
        {"case": "frank", "model": "m", "prompt": "draft_scene", "brief": "short_column", "n": 1,
         "seeded": True, "answers": {"time_skip": "yes"}},
        {"case": "frank", "model": "m", "prompt": "draft_scene", "brief": "short_column", "n": 1,
         "seeded": False, "answers": {"time_skip": "no"}},
    ]
    answers = tmp_path / "answers.yaml"
    import yaml

    answers.write_text(yaml.safe_dump({"run": str(run), "items": items}), encoding="utf-8")
    stats = calibration.tally(answers)["judges"]["g/flash"]["time_skip"]
    assert stats["seeded_present_n"] == 1 and stats["seeded_present_agree"] == 1.0
    assert stats["present_n"] == 1 and stats["absent_n"] == 1
    assert stats["absent_agree"] == 0.0 and stats["owned"] is False


def _sha(rule: str) -> str:
    return judge.question_sha(judge.RULES[rule])


def test_owned_rules_void_on_a_different_model_id():
    cal = {"judges": {"g/flash": {
        "time_skip": {"owned": True, "question_sha": _sha("time_skip")},
        "viewpoint_slip": {"owned": False, "question_sha": _sha("viewpoint_slip")},
    }}}
    assert calibration.owned_rules(cal, "g/flash") == {"time_skip"}
    assert calibration.owned_rules(cal, "g/flash-2") == set()
    assert calibration.owned_rules(cal, "") == set()


def test_owned_rules_void_when_the_question_was_reworded():
    old = judge.question_sha(judge.LEGACY_QUESTIONS["summing_up_ending"])
    cal = {"judges": {"g/flash": {
        "time_skip": {"owned": True, "question_sha": _sha("time_skip")},
        "summing_up_ending": {"owned": True, "question_sha": old},
        "explained_after_shown": {"owned": True},
    }}}
    assert calibration.owned_rules(cal, "g/flash") == {"time_skip"}


def test_tally_records_the_question_each_rule_was_tallied_against(tmp_path):
    run = _write_run(tmp_path, "g/flash", {"time_skip": "yes"})
    item = {"case": "frank", "model": "m", "prompt": "draft_scene", "brief": "short_column", "n": 1,
            "seeded": False, "answers": {"time_skip": "yes"}}
    import yaml

    answers = tmp_path / "answers.yaml"
    answers.write_text(yaml.safe_dump({"run": str(run), "items": [item]}), encoding="utf-8")
    assert calibration.tally(answers)["judges"]["g/flash"]["time_skip"]["question_sha"] == _sha("time_skip")


def test_judge_answer_ignores_a_verdict_to_a_reworded_question(tmp_path):
    run = _write_run(tmp_path, "g/flash", {"summing_up_ending": "yes", "time_skip": "yes"})
    item = {"case": "frank", "model": "m", "prompt": "draft_scene", "brief": "short_column", "n": 1}
    assert calibration.judge_answer(run, item, "summing_up_ending") == ("g/flash", "missing")
    path = judge.judge_path(item, run)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["rules"]["summing_up_ending"]["question_sha"] = _sha("summing_up_ending")
    path.write_text(json.dumps(record), encoding="utf-8")
    assert calibration.judge_answer(run, item, "summing_up_ending") == ("g/flash", "yes")
    assert calibration.judge_answer(run, item, "time_skip") == ("g/flash", "yes")


# --- report ------------------------------------------------------------------


def test_judge_metrics_direction():
    flag = report.flag_for
    assert flag("judge_time_skip", 0.1, 0.5, 0.1) == "worse"
    assert flag("judge_time_skip", 0.5, 0.1, 0.1) == "better"
    assert flag("separation_correct", 0.9, 0.5, 0.1) == "worse"
    assert flag("separation_correct", 0.5, 0.9, 0.1) == "better"
    assert flag("separation_correct", 0.5, 0.55, 0.1) == ""
    assert flag("italic_spans", 1.0, 3.0, 0.5) == "changed"


def test_report_adds_only_owned_rules(tmp_path):
    run = _write_run(tmp_path, "g/flash", {"time_skip": "yes", "viewpoint_slip": "yes"})
    cal = {"judges": {"g/flash": {"time_skip": {"owned": True, "question_sha": _sha("time_skip")}}}}
    cell = report.summarize_run(run, cal)["cells"]["frank|m|draft_scene|short_column"]["metrics"]
    assert cell["judge_time_skip"] == 1.0
    assert cell["separation_correct"] == 0.0
    assert "judge_viewpoint_slip" not in cell
    plain = report.summarize_run(run)["cells"]["frank|m|draft_scene|short_column"]["metrics"]
    assert not [m for m in plain if m.startswith("judge_") or m == "separation_correct"]
    other = report.summarize_run(run, {"judges": {"x/other": {"time_skip": {"owned": True}}}})
    assert "judge_time_skip" not in other["cells"]["frank|m|draft_scene|short_column"]["metrics"]


# --- judge_item: resume, redo, a changed judge ---------------------------------


def _judge_ctx(tmp_path, judges=JUDGES):
    # The draft's own folder, as run.py leaves it; the judge file goes beside the draft.
    (tmp_path / "frank" / "m" / "draft_scene" / "short_column").mkdir(parents=True, exist_ok=True)
    root = str(tmp_path / "proj")
    fixture = {"root": root, "assistants": {"jp": "a_p", "js": "a_s"},
               "continue": {"root": root + "-c", "assistants": {"jp": "a_p", "js": "a_s"}}}
    book = {
        "characters": [{"key": "ines", "title": "Ines"}],
        "scenes": [{"key": "short_column", "pov": "ines", "summary": "s"}],
        "style_notes": {c: {"body": f"note {c}"} for c in judge.STYLED},
    }
    return {"judges": judges, "book": book, "fixtures": {"frank": fixture},
            "clients": {root: object(), root + "-c": object()}, "model_ids": {"m": "o/drafter"}}


def _item():
    return {"case": "frank", "model": "m", "prompt": "draft_scene", "brief": "short_column", "n": 1, "text": "x"}


def _args(**kw):
    return argparse.Namespace(**{"rules": True, "separation": True, "redo": False, **kw})


def _counting_ask(monkeypatch):
    calls = []

    def fake(client, assistant_id, system, message, choices):
        calls.append(system)
        return {"answer": choices[0], "quote": "q", "cost_usd": 0.001}

    monkeypatch.setattr(judge, "ask", fake)
    return calls


def test_judge_item_resumes_without_asking_again(tmp_path, monkeypatch):
    calls = _counting_ask(monkeypatch)
    ctx = _judge_ctx(tmp_path)
    judge.judge_item(_item(), tmp_path, ctx, _args())
    assert len(calls) == len(judge.RULES) + 1
    judge.judge_item(_item(), tmp_path, ctx, _args())
    assert len(calls) == len(judge.RULES) + 1


def test_redo_rules_keeps_the_separation_verdict(tmp_path, monkeypatch):
    calls = _counting_ask(monkeypatch)
    ctx = _judge_ctx(tmp_path)
    judge.judge_item(_item(), tmp_path, ctx, _args())
    calls.clear()
    _, record = judge.judge_item(_item(), tmp_path, ctx, _args(redo=True, separation=False))
    assert len(calls) == len(judge.RULES)
    assert record["separation"]["answer"] == "A"


def test_a_changed_judge_model_discards_the_old_record(tmp_path, monkeypatch):
    calls = _counting_ask(monkeypatch)
    judge.judge_item(_item(), tmp_path, _judge_ctx(tmp_path), _args())
    calls.clear()
    changed = {**JUDGES, "primary": {"name": "jp", "model": "other/judge"}}
    _, record = judge.judge_item(_item(), tmp_path, _judge_ctx(tmp_path, changed), _args())
    assert len(calls) == len(judge.RULES) + 1
    assert record["judge_model"] == "other/judge"


def test_run_totals_keeps_a_slot_no_longer_configured(tmp_path, monkeypatch):
    _counting_ask(monkeypatch)
    judge.judge_item(_item(), tmp_path, _judge_ctx(tmp_path), _args())
    totals = judge.run_totals(tmp_path, {"second": JUDGES["second"]})
    assert totals["primary"]["calls"] == len(judge.RULES) + 1


def test_judge_metrics_ignore_a_verdict_to_a_reworded_question(tmp_path):
    run = _write_run(tmp_path, "g/flash", {"time_skip": "yes", "summing_up_ending": "yes"})
    rules = ("time_skip", "summing_up_ending")
    cal = {"judges": {"g/flash": {r: {"owned": True, "question_sha": _sha(r)} for r in rules}}}
    cell = report.summarize_run(run, cal)["cells"]["frank|m|draft_scene|short_column"]["metrics"]
    assert cell["judge_time_skip"] == 1.0 and "judge_summing_up_ending" not in cell


def test_judge_item_records_the_question_and_re_asks_only_reworded_rules(tmp_path, monkeypatch):
    calls = _counting_ask(monkeypatch)
    ctx = _judge_ctx(tmp_path)
    _, record = judge.judge_item(_item(), tmp_path, ctx, _args(separation=False))
    assert all(v["question_sha"] == _sha(r) for r, v in record["rules"].items())
    calls.clear()
    monkeypatch.setitem(judge.RULES, "time_skip", "A reworded question?")
    _, record = judge.judge_item(_item(), tmp_path, ctx, _args(separation=False))
    assert len(calls) == 1
    assert record["rules"]["time_skip"]["question_sha"] == judge.question_sha("A reworded question?")


def test_a_verdict_without_question_sha_answered_the_legacy_wording(tmp_path, monkeypatch):
    calls = _counting_ask(monkeypatch)
    ctx = _judge_ctx(tmp_path)
    judge.judge_item(_item(), tmp_path, ctx, _args(separation=False))
    path = judge.judge_path(_item(), tmp_path)
    record = json.loads(path.read_text(encoding="utf-8"))
    for verdict in record["rules"].values():
        del verdict["question_sha"]
    path.write_text(json.dumps(record), encoding="utf-8")
    calls.clear()
    _, record = judge.judge_item(_item(), tmp_path, ctx, _args(separation=False))
    assert len(calls) == 2  # only the two reworded rules
    assert record["rules"]["summing_up_ending"]["question_sha"] == _sha("summing_up_ending")
    assert len(judge.question_sha("x")) == 12
    assert set(judge.LEGACY_QUESTIONS) == set(judge.RULES)
    changed = {r for r in judge.RULES if judge.LEGACY_QUESTIONS[r] != judge.RULES[r]}
    assert changed == {"explained_after_shown", "summing_up_ending"}


def test_band_refuses_runs_judged_by_different_models(tmp_path):
    for run, model in (("a", "g/flash"), ("b", "other/judge")):
        folder = tmp_path / run / "frank" / "m" / "draft_scene" / "short_column"
        folder.mkdir(parents=True)
        (folder / "judge_1.json").write_text(json.dumps({"judge": "primary", "judge_model": model}), encoding="utf-8")
    with pytest.raises(SystemExit):
        report.ensure_same_judges(tmp_path / "a", tmp_path / "b")


def test_tally_refuses_answers_for_an_unjudged_run(tmp_path):
    answers = {"run": str(tmp_path), "items": [
        {"id": "d01", "case": "frank", "model": "m", "prompt": "draft_scene", "brief": "short_column", "n": 1,
         "seeded": False, "answers": {"time_skip": "yes"}},
    ]}
    path = tmp_path / "answers.yaml"
    path.write_text(json.dumps(answers), encoding="utf-8")
    with pytest.raises(SystemExit):
        calibration.tally(path)
