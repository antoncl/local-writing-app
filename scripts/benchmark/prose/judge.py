"""The model judge for the prose harness (#2615, measuring-prose-quality.md §4.2).

  judge.py RUN_DIR [--rules] [--separation] [--redo] [--cases CASE ...]

Writes `judge_<n>.json` beside each draft, and `RUN_DIR/judge.json` (the judges'
model ids and what each cost). The calls go through the backend's
`/api/ai/chat/stream` with the judge's assistant and no chat id, so the key stays
in the backend and every call returns its cost.

- Rules: one yes/no call per rule per draft, asking whether a failure is present.
- Separation: for a Draft scene draft in a styled case, which of two unlabelled
  style notes was it written to follow (its own, or another style's).

The judge never says which draft is better. No model judges its own drafts: a
draft written by the primary judge's model goes to the second judge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from checks import iter_drafts  # noqa: E402
from fixture_gen import CASES, load_book, load_fixture  # noqa: E402
from lwa_client import ApiError, Client, discover_backend  # noqa: E402
from setup_backend import load_judges  # noqa: E402

STYLED = tuple(c for c in CASES if c != "none")
CALL_TIMEOUT_S = 300.0

# Each question asks whether the FAILURE is present.
RULES: dict[str, str] = {
    "viewpoint_slip": (
        "Does the narration ever report a thought, feeling or perception of a character other than "
        "the viewpoint character, as if from inside them?"
    ),
    "time_skip": (
        "Does the passage jump forward or back in time without the viewpoint character living the "
        "interval, for example by summarising hours or days in a sentence?"
    ),
    "explained_after_shown": (
        "Does the narration spell out what a moment, gesture or line of dialogue means for the reader's "
        "benefit, in a narrator's voice, rather than as the viewpoint character's own reading of it in "
        "their own terms? A viewpoint character interpreting what they see is not this failure."
    ),
    "summing_up_ending": (
        "Does the passage end with the narrator stepping back to state what the scene meant or will mean, "
        "rather than ending inside the moment? A viewpoint character's own conclusion, in the moment and "
        "in their terms, is not this failure."
    ),
    "narration_euphemism": (
        "Does the narration use a euphemism or a vague stand-in where it could name the thing "
        "plainly, in the viewpoint character's own terms?"
    ),
    "noticed_outside_viewpoint": (
        "Does the narration notice something the viewpoint character would not notice, such as how "
        "they look from outside or a fact about themselves they could not be aware of?"
    ),
}

# The wordings before the two were reworded: a verdict with no `question_sha` answered these.
LEGACY_QUESTIONS: dict[str, str] = {
    "viewpoint_slip": (
        "Does the narration ever report a thought, feeling or perception of a character other than "
        "the viewpoint character, as if from inside them?"
    ),
    "time_skip": (
        "Does the passage jump forward or back in time without the viewpoint character living the "
        "interval, for example by summarising hours or days in a sentence?"
    ),
    "explained_after_shown": (
        "Does the narration spell out the meaning of a moment, gesture or line of dialogue that the "
        "scene has already shown?"
    ),
    "summing_up_ending": (
        "Does the passage end with a sentence or paragraph that sums up, reflects on or states the "
        "meaning of what has just happened, rather than ending inside the moment?"
    ),
    "narration_euphemism": (
        "Does the narration use a euphemism or a vague stand-in where it could name the thing "
        "plainly, in the viewpoint character's own terms?"
    ),
    "noticed_outside_viewpoint": (
        "Does the narration notice something the viewpoint character would not notice, such as how "
        "they look from outside or a fact about themselves they could not be aware of?"
    ),
}

SYSTEM = (
    "You answer one question about one passage of fiction. Judge only what the question asks; do not "
    "judge quality or say whether the passage is good. Reply with ONLY a JSON object: "
    '{"answer": "yes" or "no", "quote": "<the shortest passage that decides it, verbatim; empty if no>"}'
)
SYSTEM_SEPARATION = (
    "You are shown a passage of fiction and two style notes, A and B. One of them was given to the writer "
    "of the passage. Say which. Do not judge quality. Reply with ONLY a JSON object: "
    '{"answer": "A" or "B", "quote": "<the shortest passage that decides it, verbatim>"}'
)


def parse_verdict(text: str, choices: tuple[str, ...] = ("yes", "no")) -> dict[str, Any]:
    """The first JSON object in `text` (fences and surrounding prose tolerated) as
    `{"answer", "quote"}`; an answer outside `choices` gives `{"answer": "unparsed", "raw"}`."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        answer = str(obj.get("answer", "")).strip().lower()
        for choice in choices:
            if answer == choice.lower():
                return {"answer": choice, "quote": str(obj.get("quote") or "")}
        break
    return {"answer": "unparsed", "raw": text[:500]}


def pick_judge(drafter_model_id: str, judges: dict[str, dict[str, Any]]) -> str:
    """`primary`, unless the drafter is the primary judge's own model; then `second`."""
    if "primary" not in judges:
        raise SystemExit("models.yaml has no judges: primary.")
    if drafter_model_id != judges["primary"]["model"]:
        return "primary"
    if "second" not in judges or judges["second"]["model"] == drafter_model_id:
        raise SystemExit(f"No judge that is not {drafter_model_id}: name a different model under judges: second.")
    return "second"


def separation_partner(case: str, n: int) -> str:
    """The styled case `n` steps ahead of `case` in the ring; draft n=1,2,3 meet the other three."""
    return STYLED[(STYLED.index(case) + (n - 1) % (len(STYLED) - 1) + 1) % len(STYLED)]


def separation_order(case: str, model: str, brief: str, n: int) -> bool:
    """True when the draft's own note is shown first (note A): an even first byte of the path's hash."""
    return hashlib.sha256(f"{case}/{model}/{brief}/{n}".encode()).digest()[0] % 2 == 0


def character_name(book: dict[str, Any], key: str) -> str:
    return next((c["title"] for c in book["characters"] if c["key"] == key), key)


def passage_context(book: dict[str, Any], item: dict[str, Any]) -> dict[str, str]:
    """Viewpoint name plus the brief's summary (Draft scene) or the lead-in (Continue)."""
    if item["prompt"] == "continue":
        case = next(c for c in book["continue_cases"] if c["key"] == item["brief"])
        scene = next(s for s in book["scenes"] if s["key"] == case["scene"])
        return {"pov": character_name(book, scene["pov"]), "lead_in": case["before"].strip()}
    scene = next(s for s in book["scenes"] if s["key"] == item["brief"])
    return {"pov": character_name(book, scene["pov"]), "summary": scene["summary"].strip()}


def passage_lines(context: dict[str, str], draft: str) -> list[str]:
    """What the judge sees before a question; the calibration sheet shows the writer the same."""
    parts = [f"Viewpoint character: {context['pov']}", ""]
    if "lead_in" in context:
        return parts + ["Lead-in (the scene so far; do not judge it):", context["lead_in"], "",
                        "Continuation (judge only this):", draft.strip()]
    return parts + ["Scene brief:", context["summary"], "", "Draft:", draft.strip()]


def rule_message(context: dict[str, str], draft: str, question: str) -> str:
    return "\n".join([*passage_lines(context, draft), "", f"Question: {question}"])


def separation_message(draft: str, note_a: str, note_b: str) -> str:
    return (
        f"Style note A:\n{note_a.strip()}\n\nStyle note B:\n{note_b.strip()}\n\nPassage:\n{draft.strip()}\n\n"
        "Question: which note was this scene written to follow?"
    )


def ask(client: Client, assistant_id: str, system: str, message: str, choices: tuple[str, ...]) -> dict[str, Any]:
    """One judge call as a verdict dict with its cost; a failed call is `{"answer": "error"}`."""
    try:
        text, done = client.stream_ndjson(
            "/api/ai/chat/stream",
            {"assistant_id": assistant_id, "system_prompt": system, "messages": [{"role": "user", "content": message}]},
        )
    except (ApiError, httpx.HTTPError) as exc:
        return {"answer": "error", "error": f"{type(exc).__name__}: {exc}"[:500]}
    # Output tokens and truncation explain an unparsed verdict (a judge that reasons at length).
    usage = done.get("usage") or {}
    return {
        **parse_verdict(text, choices), "cost_usd": done.get("cost_usd"),
        "output_tokens": usage.get("output_tokens"), "truncated": bool(done.get("truncated")),
    }


def question_sha(question: str) -> str:
    """A short fingerprint of a question's wording, recorded with the verdict that answered it."""
    return hashlib.sha256(question.encode("utf-8")).hexdigest()[:12]


def verdict_is_current(rule: str, verdict: dict[str, Any]) -> bool:
    """Whether a rule verdict answered the rule's present wording; one with no `question_sha`
    was written before verdicts recorded it and answered `LEGACY_QUESTIONS[rule]`."""
    recorded = verdict.get("question_sha") or question_sha(LEGACY_QUESTIONS.get(rule, ""))
    return recorded == question_sha(RULES[rule])


def is_done(verdict: dict[str, Any] | None, rule: str | None = None) -> bool:
    """A recorded verdict that need not be asked again (an error is retried on resume); for a rule
    verdict also one that answered the rule's present wording."""
    if verdict is None or verdict.get("answer") == "error":
        return False
    return rule is None or verdict_is_current(rule, verdict)


def judge_path(item: dict[str, Any], run_dir: Path) -> Path:
    return run_dir.joinpath(item["case"], item["model"], item["prompt"], item["brief"], f"judge_{item['n']}.json")


def run_separation(
    client: Client, assistant_id: str, book: dict[str, Any], item: dict[str, Any]
) -> dict[str, Any]:
    own, partner = item["case"], separation_partner(item["case"], item["n"])
    order = [own, partner] if separation_order(item["case"], item["model"], item["brief"], item["n"]) else [partner, own]
    notes = [book["style_notes"][c]["body"] for c in order]
    verdict = ask(client, assistant_id, SYSTEM_SEPARATION, separation_message(item["text"], *notes), ("A", "B"))
    correct = None if verdict["answer"] not in ("A", "B") else order["AB".index(verdict["answer"])] == own
    return {"own": own, "partner": partner, "order": order, **verdict, "correct": correct}


def judge_item(
    item: dict[str, Any], run_dir: Path, ctx: dict[str, Any], args: argparse.Namespace
) -> tuple[str, dict[str, Any]]:
    """Fill in (or extend) one draft's judge file; returns the judge used and the record."""
    judges, book = ctx["judges"], ctx["book"]
    which = pick_judge(ctx["model_ids"][item["model"]], judges)
    fixture = ctx["fixtures"][item["case"]]
    project = fixture["continue"] if item["prompt"] == "continue" else fixture
    client = ctx["clients"][project["root"]]
    assistant_id = project["assistants"][judges[which]["name"]]
    path = judge_path(item, run_dir)
    record = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    # A record from another slot or another model is never resumed: its verdicts are not this judge's.
    if record.get("judge") != which or record.get("judge_model") != judges[which]["model"]:
        record = {}
    if args.redo:
        # Clear only what this run asks again: --redo --rules keeps the separation verdict.
        if args.rules:
            record.pop("rules", None)
        if args.separation:
            record.pop("separation", None)
    record.update(judge=which, judge_model=judges[which]["model"])
    record.setdefault("rules", {})
    if args.rules:
        context = passage_context(book, item)
        for rule, question in RULES.items():
            if not is_done(record["rules"].get(rule), rule):
                message = rule_message(context, item["text"], question)
                verdict = ask(client, assistant_id, SYSTEM, message, ("yes", "no"))
                record["rules"][rule] = {**verdict, "question_sha": question_sha(question)}
    wants_separation = args.separation and item["prompt"] == "draft_scene" and item["case"] in STYLED
    if wants_separation and not is_done(record.get("separation")):
        record["separation"] = run_separation(client, assistant_id, book, item)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return which, record


def run_totals(run_dir: Path, judges: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Each judge's model id and the summed cost of every call recorded under the run."""
    totals = {w: {"model": j["model"], "cost_usd": 0.0, "calls": 0} for w, j in judges.items()}
    for path in run_dir.glob("*/*/*/*/judge_*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        calls = [*record.get("rules", {}).values(), *([record["separation"]] if "separation" in record else [])]
        # A slot no longer in models.yaml still has its recorded calls and cost counted.
        bucket = totals.setdefault(record["judge"], {"model": record.get("judge_model"), "cost_usd": 0.0, "calls": 0})
        bucket["calls"] += len(calls)
        bucket["cost_usd"] = round(bucket["cost_usd"] + sum(c.get("cost_usd") or 0 for c in calls), 6)
    return totals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--rules", action="store_true", help="only the six rule checks")
    parser.add_argument("--separation", action="store_true", help="only the separation test")
    parser.add_argument("--redo", action="store_true", help="ask again even where a verdict is recorded")
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--workers", type=int, default=4, help="drafts judged at once (default 4)")
    args = parser.parse_args()
    if not (args.rules or args.separation):
        args.rules = args.separation = True
    judges = load_judges()
    run = json.loads((args.run_dir / "run.json").read_text(encoding="utf-8"))
    base_url = discover_backend()
    fixtures = {c: load_fixture(c) for c in args.cases}
    # One client per project, made up front: httpx.Client is safe to share across the workers.
    roots = {p["root"] for f in fixtures.values() for p in (f, f["continue"])}
    ctx = {
        "judges": judges, "book": load_book(), "fixtures": fixtures,
        "clients": {r: Client(base_url, r, timeout=CALL_TIMEOUT_S) for r in roots},
        "model_ids": {m["name"]: m["model"] for m in run["models"]},
    }
    items = [
        i for i in iter_drafts(args.run_dir)
        if i["case"] in args.cases and i["meta"].get("status", "ok") == "ok"
    ]
    try:
        # Each draft writes only its own judge file, so drafts are independent.
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(judge_item, item, args.run_dir, ctx, args): item for item in items}
            for future in as_completed(futures):
                item = futures[future]
                which, record = future.result()
                answers = {r: v["answer"] for r, v in record["rules"].items()}
                print(f"{item['case']}/{item['model']}/{item['prompt']}/{item['brief']} #{item['n']} [{which}]: {answers}", flush=True)
    finally:
        for client in ctx["clients"].values():
            client.close()
    totals = run_totals(args.run_dir, judges)
    (args.run_dir / "judge.json").write_text(json.dumps({"judges": totals}, indent=2), encoding="utf-8")
    print(f"wrote {args.run_dir / 'judge.json'}")


if __name__ == "__main__":
    main()
