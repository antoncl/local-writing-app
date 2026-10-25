"""Calibration of the model judge against the writer (#2615, measuring-prose-quality.md §7 steps 3-4).

  calibration.py sheet RUN_DIR [--seeded SEEDED_RUN] --out DIR [--scenes 12] [--continuations N] [--seed 2615]
      A worksheet of drafts x rules for the writer: DIR/sheet.md to read and
      DIR/answers.yaml to fill (calibration_serve.py fills it from a page). Natural
      drafts are a stratified sample of RUN_DIR; seeded ones are every ok draft of
      SEEDED_RUN (calibration_seed.py). They are shuffled into one list, and nothing
      the writer sees tells them apart or shows the judge's verdicts.
  calibration.py extend DIR --run RUN --seeded SEEDED_RUN --natural N [--seed 2615]
      Appends to DIR/answers.yaml without touching its items or answers: N more natural
      Continue drafts of RUN not yet on the sheet, and every ok seeded draft of SEEDED_RUN
      not yet on it, shuffled together and numbered after the highest id.
  calibration.py tally DIR/answers.yaml --out calibration.json
      Scores the judge's recorded verdicts (judge_<n>.json) against the answers,
      per judge model and rule, and says which rules the judge owns (`owns_rule`).

The result is keyed to the judge's model id: a different model owns nothing until
it is calibrated, and a rule whose question was reworded since owns nothing until retallied. Every item records the run its judge files live in.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from calibration_serve import draft_text, write_atomic  # noqa: E402
from checks import iter_drafts  # noqa: E402
from fixture_gen import load_book  # noqa: E402
from judge import (  # noqa: E402
    RULES,
    judge_path,
    passage_context,
    passage_lines,
    question_sha,
    verdict_is_current,
)

MIN_CASES = 8
MIN_AGREEMENT = 0.8


def sample_drafts(drafts: list[dict[str, Any]], count: int, seed: int) -> list[dict[str, Any]]:
    """`count` drafts, round-robin over (case, model, prompt) strata, each shuffled with `seed`."""
    rng = random.Random(seed)
    strata: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for d in drafts:
        strata.setdefault((d["case"], d["model"], d["prompt"]), []).append(d)
    queues = [strata[k] for k in sorted(strata)]
    for queue in queues:
        rng.shuffle(queue)
    picked: list[dict[str, Any]] = []
    while len(picked) < count and any(queues):
        for queue in queues:
            if queue and len(picked) < count:
                picked.append(queue.pop())
    return picked


def render_sheet(items: list[dict[str, Any]], book: dict[str, Any]) -> str:
    lines = ["# Judge calibration sheet", "",
             "For each draft answer every question yes or no in answers.yaml: is the failure present?", ""]
    for item in items:
        # The same passage the judge is shown, so both answer the same question.
        lines += [f"## {item['id']}", "", *passage_lines(passage_context(book, item), item["text"]), "", "Questions:", ""]
        lines += [f"- `{rule}`: {question}" for rule, question in RULES.items()]
        lines.append("")
    return "\n".join(lines)


def interleave(
    natural: list[dict[str, Any]], seeded: list[dict[str, Any]], seed: int, first: int = 1
) -> list[dict[str, Any]]:
    """Natural and seeded items shuffled together with `seed`, numbered `d01`, `d02`, ... from `first`
    after the shuffle."""
    items = [*natural, *seeded]
    random.Random(seed).shuffle(items)
    return [{**it, "id": f"d{i:02d}"} for i, it in enumerate(items, start=first)]


def sheet_item(item: dict[str, Any]) -> dict[str, Any]:
    """The answers.yaml record for one drafted item; `run` is absolute so the tally and the page find
    the drafts and judge files from any working directory."""
    record = {k: item[k] for k in ("id", "case", "model", "prompt", "brief", "n", "run", "seeded")}
    if item["seeded"]:
        record["seeded_rule"] = item["seeded_rule"]
    return {**record, "answers": dict.fromkeys(RULES), "note": ""}


def sample_natural(drafts: list[dict[str, Any]], scenes: int, continuations: int, seed: int) -> list[dict[str, Any]]:
    """`scenes` Draft scene drafts and `continuations` Continue drafts, each stratified by `sample_drafts`."""
    by_prompt = {"draft_scene": scenes, "continue": continuations}
    return [
        d for prompt, count in by_prompt.items()
        for d in sample_drafts([x for x in drafts if x["prompt"] == prompt], count, seed)
    ]


def has_answers(path: Path) -> bool:
    """Whether an answers.yaml already holds any of the writer's answers or notes."""
    if not path.is_file():
        return False
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return any(
        any(v is not None for v in (i.get("answers") or {}).values()) or i.get("note")
        for i in doc.get("items") or []
    )


def seeded_items(seeded_dir: Path) -> list[dict[str, Any]]:
    """Every ok draft of a calibration_seed.py run as a sheet item."""
    return [
        {**d, "run": str(seeded_dir.resolve()), "seeded": True, "seeded_rule": d["meta"]["seeded_rule"]}
        for d in iter_drafts(seeded_dir)
        if d["meta"].get("status", "ok") == "ok"
    ]


def make_sheet(run_dir: Path, seeded_dir: Path | None, out: Path, scenes: int, continuations: int | None, seed: int) -> None:
    if has_answers(out / "answers.yaml"):
        raise SystemExit(f"{out / 'answers.yaml'} already holds answers: refusing to overwrite the writer's reading.")
    seeded = seeded_items(seeded_dir) if seeded_dir else []
    # Every seeded passage is a continuation, so by default as many natural continuations join them:
    # otherwise a continuation would itself hint that a failure was planted.
    continuations = len(seeded) if continuations is None else continuations
    drafts = [d for d in iter_drafts(run_dir) if d["meta"].get("status", "ok") == "ok"]
    natural = [
        {**d, "run": str(run_dir.resolve()), "seeded": False}
        for d in sample_natural(drafts, scenes, continuations, seed)
    ]
    items = interleave(natural, seeded, seed)
    answers = {"run": str(run_dir.resolve()), "items": [sheet_item(it) for it in items]}
    out.mkdir(parents=True, exist_ok=True)
    (out / "sheet.md").write_text(render_sheet(items, load_book()), encoding="utf-8")
    (out / "answers.yaml").write_text(yaml.safe_dump(answers, sort_keys=False), encoding="utf-8")
    print(f"wrote {out / 'sheet.md'} and {out / 'answers.yaml'} ({len(natural)} natural + {len(seeded)} seeded)")


def address(item: dict[str, Any], default_run: str) -> tuple[str, str, str, str, str, int]:
    """Where an item's draft lives: its run and the draft's own path parts."""
    run = str(Path(item.get("run") or default_run).resolve())
    return run, item["case"], item["model"], item["prompt"], item["brief"], item["n"]


def extend_sheet(out: Path, run_dir: Path, seeded_dir: Path, natural: int, seed: int) -> tuple[int, int]:
    """Append `natural` Continue drafts of `run_dir` and every ok seeded draft not yet on DIR/answers.yaml.
    Existing items and answers are untouched; returns `(natural added, seeded added)`."""
    path = out / "answers.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    on_sheet = {address(i, doc["run"]) for i in doc["items"]}
    drafts = [
        {**d, "run": str(run_dir.resolve()), "seeded": False} for d in iter_drafts(run_dir)
        if d["meta"].get("status", "ok") == "ok" and d["prompt"] == "continue"
    ]
    fresh = [d for d in drafts if address(d, "") not in on_sheet]
    if len(fresh) < natural:
        raise SystemExit(f"Only {len(fresh)} natural Continue drafts are not on the sheet yet; --natural {natural} is too many.")
    picked = sample_drafts(fresh, natural, seed)
    seeded = [s for s in seeded_items(seeded_dir) if address(s, "") not in on_sheet]
    first = max((int(i["id"][1:]) for i in doc["items"]), default=0) + 1
    new = interleave(picked, seeded, seed, first)
    new_addresses = [address(i, "") for i in new]
    if len(set(new_addresses)) != len(new) or on_sheet & set(new_addresses):
        raise SystemExit("A new item would duplicate an address already on the sheet.")
    doc["items"] = [*doc["items"], *(sheet_item(i) for i in new)]
    write_atomic(path, doc)
    shown = [{**i, "text": draft_text(doc, i)} for i in doc["items"]]
    (out / "sheet.md").write_text(render_sheet(shown, load_book()), encoding="utf-8")
    return len(picked), len(seeded)


def rule_agreement(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """Agreement over (writer, judge) answer pairs for one rule. The writer's answer is yes or no;
    anything but the same answer from the judge (including unparsed, error or missing) disagrees."""
    present = [j for w, j in pairs if w == "yes"]
    absent = [j for w, j in pairs if w == "no"]
    present_agree = round(present.count("yes") / len(present), 4) if present else None
    absent_agree = round(absent.count("no") / len(absent), 4) if absent else None
    return {
        "present_n": len(present), "absent_n": len(absent),
        "present_agree": present_agree, "absent_agree": absent_agree,
    }


def _agrees(stats: dict[str, Any], key: str) -> bool:
    return stats[key] is not None and stats[key] >= MIN_AGREEMENT


def owns_rule(pooled: dict[str, Any], seeded: dict[str, Any], natural: dict[str, Any]) -> bool:
    """Whether the judge owns a rule, from `rule_agreement` of all, seeded and natural items.

    - Pooled: at least MIN_CASES present and absent each, and MIN_AGREEMENT on each, so neither
      "always yes" nor "always no" passes and the sample is big enough to mean something.
    - Seeded present (at least one, agreeing): the judge must catch a failure planted on purpose.
    - Natural present (if the writer found any, agreeing): the judge must not miss real failures
      the writer found, even when it catches planted ones; then the rule stays with the writer.
    """
    return (
        pooled["present_n"] >= MIN_CASES and pooled["absent_n"] >= MIN_CASES
        and _agrees(pooled, "present_agree") and _agrees(pooled, "absent_agree")
        and seeded["present_n"] >= 1 and _agrees(seeded, "present_agree")
        and (natural["present_n"] == 0 or _agrees(natural, "present_agree"))
    )


def judge_answer(run_dir: Path, item: dict[str, Any], rule: str) -> tuple[str, str]:
    """`(judge_model, answer)` from the item's judge file; `("", "missing")` when there is none."""
    path = judge_path(item, run_dir)
    if not path.is_file():
        return "", "missing"
    record = json.loads(path.read_text(encoding="utf-8"))
    verdict = record.get("rules", {}).get(rule, {})
    # A verdict that answered a since-reworded question counts as missing.
    if not verdict_is_current(rule, verdict):
        return record["judge_model"], "missing"
    return record["judge_model"], verdict.get("answer", "missing")


def tally_pairs(default_run: Path, items: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, list[tuple[str, str]]]]]:
    """`{judge_model: {rule: {"all", "seeded", "natural": pairs}}}` over the answered items; each
    item's judge file is read from its own `run` (else `default_run`). Unsure or blank is skipped."""
    out: dict[str, dict[str, dict[str, list[tuple[str, str]]]]] = {}
    for item in items:
        run_dir = Path(item.get("run") or default_run)
        for rule, writer in (item.get("answers") or {}).items():
            if str(writer).lower() not in ("yes", "no"):
                continue
            model, answer = judge_answer(run_dir, item, rule)
            if not model:
                continue
            bucket = out.setdefault(model, {}).setdefault(rule, {"all": [], "seeded": [], "natural": []})
            pair = (str(writer).lower(), answer)
            bucket["all"].append(pair)
            bucket["seeded" if item.get("seeded") else "natural"].append(pair)
    return out


def tally(answers_path: Path) -> dict[str, Any]:
    raw = answers_path.read_bytes()
    answers = yaml.safe_load(raw)
    run_dir = Path(answers["run"])
    pairs_by_model = tally_pairs(run_dir, answers["items"])
    answered = [i for i in answers["items"] if any(str(a).lower() in ("yes", "no") for a in (i.get("answers") or {}).values())]
    if answered and not pairs_by_model:
        # Answers but no judge file at all: the run was never judged, or `run:` points elsewhere.
        raise SystemExit(f"No judge verdicts found under {run_dir} for the {len(answered)} answered items: run judge.py first.")
    judges: dict[str, dict[str, Any]] = {}
    for model, rules in pairs_by_model.items():
        for rule, pairs in rules.items():
            pooled, seeded, natural = (rule_agreement(pairs[k]) for k in ("all", "seeded", "natural"))
            judges.setdefault(model, {})[rule] = {
                **pooled,
                "seeded_present_n": seeded["present_n"], "seeded_present_agree": seeded["present_agree"],
                "natural_present_n": natural["present_n"], "natural_present_agree": natural["present_agree"],
                "owned": owns_rule(pooled, seeded, natural), "question_sha": question_sha(RULES[rule]),
            }
    return {"judges": judges, "answers_sha256": hashlib.sha256(raw).hexdigest()}


def owned_rules(calibration: dict[str, Any], judge_model: str) -> set[str]:
    """Rules owned for exactly this model id; any other model id owns none (a changed judge voids it),
    and a rule is owned only if tallied against its present question (a reworded one voids it)."""
    rules = calibration.get("judges", {}).get(judge_model, {})
    return {
        rule for rule, stats in rules.items()
        if stats.get("owned") and rule in RULES and stats.get("question_sha") == question_sha(RULES[rule])
    }


def render_table(calibration: dict[str, Any]) -> str:
    lines = []
    for model, rules in calibration["judges"].items():
        lines += [f"{model}", f"  {'rule':28} present  absent  seeded present  natural present  owned"]
        for rule, s in rules.items():
            lines.append(
                f"  {rule:28} {s['present_n']:>2} {s['present_agree']!s:>6}  {s['absent_n']:>2} {s['absent_agree']!s:>6}"
                f"  {s['seeded_present_n']:>2} {s['seeded_present_agree']!s:>6}"
                f"  {s['natural_present_n']:>2} {s['natural_present_agree']!s:>6}"
                f"  {'OWNED' if s['owned'] else '-'}"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sheet = sub.add_parser("sheet", help="write the worksheet for the writer")
    sheet.add_argument("run_dir", type=Path)
    sheet.add_argument("--seeded", type=Path, help="a calibration_seed.py run whose ok drafts join the sheet")
    sheet.add_argument("--out", type=Path, required=True)
    sheet.add_argument("--scenes", type=int, default=12, help="natural Draft scene drafts (default 12)")
    sheet.add_argument(
        "--continuations", type=int, help="natural Continue drafts (default: as many as the seeded passages)"
    )
    sheet.add_argument("--seed", type=int, default=2615)
    more = sub.add_parser("extend", help="append more drafts to an existing sheet, keeping its answers")
    more.add_argument("directory", type=Path, help="the folder holding sheet.md and answers.yaml")
    more.add_argument("--run", type=Path, required=True, help="the run the natural drafts come from")
    more.add_argument("--seeded", type=Path, required=True, help="the calibration_seed.py run to add")
    more.add_argument("--natural", type=int, required=True, help="natural Continue drafts to add")
    more.add_argument("--seed", type=int, default=2615)
    score = sub.add_parser("tally", help="score the judge against the filled answers.yaml")
    score.add_argument("answers", type=Path)
    score.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "sheet":
        make_sheet(args.run_dir, args.seeded, args.out, args.scenes, args.continuations, args.seed)
        return
    if args.command == "extend":
        natural, seeded = extend_sheet(args.directory, args.run, args.seeded, args.natural, args.seed)
        print(f"added {natural + seeded} items ({natural} natural + {seeded} seeded) to {args.directory / 'answers.yaml'}")
        return
    calibration = tally(args.answers)
    args.out.write_text(json.dumps(calibration, indent=2), encoding="utf-8")
    print(render_table(calibration))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
