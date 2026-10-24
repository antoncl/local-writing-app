"""Calibration of the model judge against the writer (#2615, measuring-prose-quality.md §7 steps 3-4).

  calibration.py sheet RUN_DIR --out DIR [--drafts 24] [--seed 2615]
      A worksheet of drafts x rules for the writer: DIR/sheet.md to read and
      DIR/answers.yaml to fill with yes/no. It never shows the judge's verdicts.
  calibration.py tally DIR/answers.yaml --out calibration.json
      Scores the judge's recorded verdicts (judge_<n>.json) against the answers,
      per judge model and rule, and says which rules the judge owns.

A rule is the judge's only with at least 8 failure-present and 8 failure-absent
answers and 80% agreement on each. The result is keyed to the judge's model id: a
different model owns nothing until it is calibrated.

A seeded item is a draft rewritten to contain exactly one failure (a third model,
confirmed by the writer); the sheet marks it `seeded: true` and its address must
point at a draft with a judge file. Seeded answers count toward the thresholds and
are also reported on their own.
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
from checks import iter_drafts  # noqa: E402
from fixture_gen import load_book  # noqa: E402
from judge import RULES, judge_path, passage_context  # noqa: E402

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
        context = passage_context(book, item)
        lines += [f"## {item['id']}", "", f"Viewpoint character: {context['pov']}", ""]
        if "lead_in" in context:
            lines += ["Lead-in:", "", context["lead_in"], "", "Continuation:", ""]
        else:
            lines += ["Brief:", "", context["summary"], "", "Draft:", ""]
        lines += [item["text"].strip(), "", "Questions:", ""]
        lines += [f"- `{rule}`: {question}" for rule, question in RULES.items()]
        lines.append("")
    return "\n".join(lines)


def make_sheet(run_dir: Path, out: Path, count: int, seed: int) -> None:
    drafts = [d for d in iter_drafts(run_dir) if d["meta"].get("status", "ok") == "ok"]
    picked = sample_drafts(drafts, count, seed)
    items = [{**d, "id": f"d{i:02d}"} for i, d in enumerate(picked, start=1)]
    answers = {
        "run": str(run_dir),
        "items": [
            {**{k: it[k] for k in ("id", "case", "model", "prompt", "brief", "n")},
             "seeded": False, "answers": dict.fromkeys(RULES)}
            for it in items
        ],
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "sheet.md").write_text(render_sheet(items, load_book()), encoding="utf-8")
    (out / "answers.yaml").write_text(yaml.safe_dump(answers, sort_keys=False), encoding="utf-8")
    print(f"wrote {out / 'sheet.md'} and {out / 'answers.yaml'} ({len(items)} drafts)")


def rule_agreement(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """Agreement over (writer, judge) answer pairs for one rule. The writer's answer is yes or no;
    anything but the same answer from the judge (including unparsed, error or missing) disagrees."""
    present = [j for w, j in pairs if w == "yes"]
    absent = [j for w, j in pairs if w == "no"]
    present_agree = round(present.count("yes") / len(present), 4) if present else None
    absent_agree = round(absent.count("no") / len(absent), 4) if absent else None
    owned = (
        len(present) >= MIN_CASES and len(absent) >= MIN_CASES
        and present_agree is not None and present_agree >= MIN_AGREEMENT
        and absent_agree is not None and absent_agree >= MIN_AGREEMENT
    )
    return {
        "present_n": len(present), "absent_n": len(absent),
        "present_agree": present_agree, "absent_agree": absent_agree, "owned": owned,
    }


def judge_answer(run_dir: Path, item: dict[str, Any], rule: str) -> tuple[str, str]:
    """`(judge_model, answer)` from the item's judge file; `("", "missing")` when there is none."""
    path = judge_path(item, run_dir)
    if not path.is_file():
        return "", "missing"
    record = json.loads(path.read_text(encoding="utf-8"))
    return record["judge_model"], record.get("rules", {}).get(rule, {}).get("answer", "missing")


def tally_pairs(run_dir: Path, items: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, list[tuple[str, str]]]]]:
    """`{judge_model: {rule: {"all": pairs, "seeded": pairs}}}` over the answered items."""
    out: dict[str, dict[str, dict[str, list[tuple[str, str]]]]] = {}
    for item in items:
        for rule, writer in (item.get("answers") or {}).items():
            if str(writer).lower() not in ("yes", "no"):
                continue
            model, answer = judge_answer(run_dir, item, rule)
            if not model:
                continue
            bucket = out.setdefault(model, {}).setdefault(rule, {"all": [], "seeded": []})
            pair = (str(writer).lower(), answer)
            bucket["all"].append(pair)
            if item.get("seeded"):
                bucket["seeded"].append(pair)
    return out


def tally(answers_path: Path) -> dict[str, Any]:
    raw = answers_path.read_bytes()
    answers = yaml.safe_load(raw)
    run_dir = Path(answers["run"])
    judges: dict[str, dict[str, Any]] = {}
    for model, rules in tally_pairs(run_dir, answers["items"]).items():
        for rule, pairs in rules.items():
            seeded = rule_agreement(pairs["seeded"])
            judges.setdefault(model, {})[rule] = {
                **rule_agreement(pairs["all"]),
                "seeded_present_n": seeded["present_n"], "seeded_present_agree": seeded["present_agree"],
            }
    return {"judges": judges, "answers_sha256": hashlib.sha256(raw).hexdigest()}


def owned_rules(calibration: dict[str, Any], judge_model: str) -> set[str]:
    """Rules owned for exactly this model id; any other model id owns none (a changed judge voids it)."""
    rules = calibration.get("judges", {}).get(judge_model, {})
    return {rule for rule, stats in rules.items() if stats.get("owned")}


def render_table(calibration: dict[str, Any]) -> str:
    lines = []
    for model, rules in calibration["judges"].items():
        lines += [f"{model}", f"  {'rule':28} present  absent  owned"]
        for rule, s in rules.items():
            lines.append(
                f"  {rule:28} {s['present_n']:>2} {s['present_agree']!s:>6}  {s['absent_n']:>2} {s['absent_agree']!s:>6}"
                f"  {'OWNED' if s['owned'] else '-'}"
                + (f"  (seeded present {s['seeded_present_n']}: {s['seeded_present_agree']})" if s["seeded_present_n"] else "")
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sheet = sub.add_parser("sheet", help="write the worksheet for the writer")
    sheet.add_argument("run_dir", type=Path)
    sheet.add_argument("--out", type=Path, required=True)
    sheet.add_argument("--drafts", type=int, default=24)
    sheet.add_argument("--seed", type=int, default=2615)
    score = sub.add_parser("tally", help="score the judge against the filled answers.yaml")
    score.add_argument("answers", type=Path)
    score.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "sheet":
        make_sheet(args.run_dir, args.out, args.drafts, args.seed)
        return
    calibration = tally(args.answers)
    args.out.write_text(json.dumps(calibration, indent=2), encoding="utf-8")
    print(render_table(calibration))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
