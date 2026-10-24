"""Plant one failure per passage for the judge's calibration (#2615).

  calibration_seed.py SOURCE_RUN --out SEEDED_RUN [--per-rule 8] [--seed 2615] [--workers 4]

Picks `per-rule` Continue drafts from SOURCE_RUN for each rule, distinct across rules, and has the
seeder model (`seeder:` in models.yaml; neither a judge nor a drafter) rewrite each to contain
exactly that one failure. SEEDED_RUN is laid out as a run, so `judge.py SEEDED_RUN` judges it and
`calibration.py sheet --seeded SEEDED_RUN` reads it. Seeded drafts are numbered from 100.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from checks import iter_drafts  # noqa: E402
from fixture_gen import load_book, load_fixture  # noqa: E402
from judge import CALL_TIMEOUT_S, RULES, passage_context  # noqa: E402
from lwa_client import ApiError, Client, discover_backend  # noqa: E402
from setup_backend import load_judges, load_seeder  # noqa: E402

FIRST_SEEDED_N = 100
MIN_WORD_RATIO, MAX_WORD_RATIO = 0.5, 2.0

# One concrete instruction per rule: introduce this flaw once and nothing else.
SEED_INSTRUCTIONS: dict[str, str] = {
    "viewpoint_slip": (
        "Add one or two sentences in which the narration reports from inside what a character other than "
        "{pov} thinks or feels, as if the narrator could see into them."
    ),
    "time_skip": (
        "Add one sentence that jumps forward or back in time by summarising an interval {pov} does not live "
        "through, for example hours or days passing, and carry on from there."
    ),
    "explained_after_shown": (
        "After a gesture, a look or a line of dialogue that the passage already shows, add one sentence in "
        "which the narration spells out what it meant."
    ),
    "summing_up_ending": (
        "Replace the last sentence or add a final one that sums up, reflects on or states the meaning of "
        "what has just happened, instead of ending inside the moment."
    ),
    "narration_euphemism": (
        "Change one plain naming of a thing in the narration into a euphemism or a vague stand-in, where "
        "{pov} would name it plainly in their own terms."
    ),
    "noticed_outside_viewpoint": (
        "Add one sentence in which the narration notices something {pov} could not notice, such as how "
        "{pov} looks from outside or a fact about themselves {pov} could not be aware of."
    ),
}

SEED_SYSTEM = (
    "You edit a passage of fiction to introduce exactly one specified flaw. Keep everything else word for word. "
    "Keep the length within about 10% of the original. Do not fix the passage or add any other flaw. "
    "Reply with only the revised passage, no commentary and no quotation marks around it."
)

FENCE = re.compile(r"\A```[\w-]*\n(.*?)\n?```\Z", re.DOTALL)
QUOTE_PAIRS = (('"', '"'), ("“", "”"))


def clean_seed(text: str) -> str:
    """The reply without a wrapping code fence or wrapping quotation marks."""
    text = text.strip()
    fenced = FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    for open_q, close_q in QUOTE_PAIRS:
        inner = text[1:-1]
        if len(text) > 1 and text[0] == open_q and text[-1] == close_q and open_q not in inner and close_q not in inner:
            return inner.strip()
    return text


def seed_problem(source: str, result: str) -> str | None:
    """Why a (cleaned) rewrite is unusable, or None: empty, unchanged, or far from the source's length."""
    if not result.strip():
        return "empty reply"
    if result.strip() == source.strip():
        return "identical to the source"
    ratio = len(result.split()) / max(1, len(source.split()))
    if not MIN_WORD_RATIO <= ratio <= MAX_WORD_RATIO:
        return f"length {ratio:.2f}x the source, outside {MIN_WORD_RATIO}x-{MAX_WORD_RATIO}x"
    return None


def seeder_conflict(seeder_model: str, judges: dict[str, dict[str, Any]], run_models: list[dict[str, Any]]) -> str | None:
    """Why the seeder's model id may not seed (it is a judge or a drafter of the source run), or None."""
    if any(j["model"] == seeder_model for j in judges.values()):
        return f"The seeder model {seeder_model} is also a judge: use a third model."
    if any(m["model"] == seeder_model for m in run_models):
        return f"The seeder model {seeder_model} is also a drafter in the source run: use a third model."
    return None


def seed_message(pov: str, lead_in: str, passage: str, rule: str) -> str:
    return "\n".join([
        f"Viewpoint character: {pov}", "",
        "Lead-in (context; do not edit it):", lead_in, "",
        "Passage to edit:", passage.strip(), "",
        f"Instruction: {SEED_INSTRUCTIONS[rule].format(pov=pov)}",
    ])


def plan_seeds(candidates: list[dict[str, Any]], per_rule: int, seed: int) -> list[dict[str, Any]]:
    """`per_rule` distinct candidates per rule, each `{rule, source, n}` with `n` counted per folder from 100."""
    need = per_rule * len(RULES)
    if len(candidates) < need:
        raise SystemExit(f"Only {len(candidates)} ok Continue drafts for {need} seeds ({per_rule} per rule): lower --per-rule.")
    picked = random.Random(seed).sample(candidates, need)
    counters: dict[tuple[str, str, str], int] = {}
    plan = []
    for i, source in enumerate(picked):
        folder = (source["case"], source["model"], source["brief"])
        counters[folder] = counters.get(folder, FIRST_SEEDED_N - 1) + 1
        plan.append({"rule": list(RULES)[i // per_rule], "source": source, "n": counters[folder]})
    return plan


def seed_one(
    client: Client, assistant_id: str, book: dict[str, Any], entry: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Ask the seeder for one rewrite; returns `(text, meta fields)` with status ok or error."""
    source = entry["source"]
    context = passage_context(book, source)
    message = seed_message(context["pov"], context["lead_in"], source["text"], entry["rule"])
    body = {"assistant_id": assistant_id, "system_prompt": SEED_SYSTEM, "messages": [{"role": "user", "content": message}]}
    try:
        text, done = client.stream_ndjson("/api/ai/chat/stream", body)
    except (ApiError, httpx.HTTPError) as exc:
        return "", {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:500]}
    cleaned = clean_seed(text)
    problem = seed_problem(source["text"], cleaned)
    cost = {"cost_usd": done.get("cost_usd")}
    return (cleaned, {"status": "ok", **cost}) if problem is None else ("", {"status": "error", "error": problem, **cost})


def write_seed(out: Path, entry: dict[str, Any], text: str, fields: dict[str, Any], source_run: Path, seeder_model: str) -> str:
    """Write draft_<n>.md and meta_<n>.json for one seed; returns the draft's address."""
    source = entry["source"]
    folder = out / source["case"] / source["model"] / "continue" / source["brief"]
    folder.mkdir(parents=True, exist_ok=True)
    meta = {
        **fields, "seeded_rule": entry["rule"], "seeder_model": seeder_model, "source_run": str(source_run),
        "source": f"{source['case']}/{source['model']}/continue/{source['brief']}/draft_{source['n']}.md",
    }
    (folder / f"draft_{entry['n']}.md").write_text(text, encoding="utf-8")
    (folder / f"meta_{entry['n']}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return f"{source['case']}/{source['model']}/continue/{source['brief']}/draft_{entry['n']}.md"


def seeded_ok(out: Path, entry: dict[str, Any]) -> bool:
    """Whether this planned seed was already written with status ok (so a rerun skips it)."""
    source = entry["source"]
    meta = out / source["case"] / source["model"] / "continue" / source["brief"] / f"meta_{entry['n']}.json"
    if not meta.is_file():
        return False
    record = json.loads(meta.read_text(encoding="utf-8"))
    return record.get("status") == "ok" and record.get("seeded_rule") == entry["rule"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source_run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--per-rule", type=int, default=8)
    parser.add_argument("--seed", type=int, default=2615)
    parser.add_argument("--workers", type=int, default=4, help="passages seeded at once (default 4)")
    args = parser.parse_args()
    seeder = load_seeder()
    if seeder is None:
        raise SystemExit("models.yaml has no seeder: entry.")
    source_run = args.source_run.resolve()
    run = json.loads((source_run / "run.json").read_text(encoding="utf-8"))
    conflict = seeder_conflict(seeder["model"], load_judges(), run["models"])
    if conflict:
        raise SystemExit(conflict)
    candidates = [
        d for d in iter_drafts(source_run) if d["prompt"] == "continue" and d["meta"].get("status", "ok") == "ok"
    ]
    # The plan is deterministic for a seed, so a rerun resumes: a passage already seeded ok is kept.
    plan = [e for e in plan_seeds(candidates, args.per_rule, args.seed) if not seeded_ok(args.out, e)]
    if not plan:
        print(f"every passage in {args.out} is already seeded")
        return
    book, base_url = load_book(), discover_backend()
    projects = {c: load_fixture(c)["continue"] for c in {e["source"]["case"] for e in plan}}
    clients = {c: Client(base_url, p["root"], timeout=CALL_TIMEOUT_S) for c, p in projects.items()}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "run.json").write_text(
        json.dumps({**run, "seeded_from": str(source_run), "seeder_model": seeder["model"]}, indent=2), encoding="utf-8"
    )
    total = 0.0
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {
                pool.submit(
                    seed_one, clients[e["source"]["case"]],
                    projects[e["source"]["case"]]["assistants"][seeder["name"]], book, e,
                ): e
                for e in plan
            }
            for future in as_completed(futures):
                entry = futures[future]
                text, fields = future.result()
                address = write_seed(args.out, entry, text, fields, source_run, seeder["model"])
                total += fields.get("cost_usd") or 0
                print(f"{address} [{entry['rule']}]: {fields['status']}{' - ' + fields['error'] if 'error' in fields else ''}", flush=True)
    finally:
        for client in clients.values():
            client.close()
    print(f"seeded {len(plan)} passages into {args.out}; cost ${total:.4f}")


if __name__ == "__main__":
    main()
