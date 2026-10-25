"""Plant one failure per passage for the judge's calibration (#2615).

  calibration_seed.py SOURCE_RUN --out SEEDED_RUN [--rules RULE ...] [--per-rule 8] [--seed 2615] [--workers 4]

Picks `per-rule` Continue drafts from SOURCE_RUN for each rule (`--rules` limits which; default all),
distinct across rules, and has the
seeder model (`seeder:` in models.yaml; neither a judge nor a drafter) rewrite each to contain
exactly that one failure. SEEDED_RUN is laid out as a run, so `judge.py SEEDED_RUN` judges it and
`calibration.py sheet --seeded SEEDED_RUN` reads it. Seeded drafts are numbered from 100, or after the
highest draft already in the folder.
"""

from __future__ import annotations

import argparse
import difflib
import json
import random
import re
import sys
from collections import Counter
from collections.abc import Iterable
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
MAX_WORDS_REMOVED = 25

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
        "which an outside narrator, not {pov}, explains to the reader what it meant: in a voice {pov} would "
        "not use, stating it as fact rather than as {pov}'s guess."
    ),
    "summing_up_ending": (
        "Add a final sentence in which an outside narrator steps back from the moment to tell the reader "
        "what the scene meant or would come to mean, in a voice and with a knowledge {pov} does not have."
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


def words_removed(source: str, result: str) -> int:
    """How many of the source's words the rewrite drops (the old side of delete and replace edits)."""
    old, new = source.split(), result.split()
    ops = difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
    return sum(i2 - i1 for tag, i1, i2, _, _ in ops if tag in ("delete", "replace"))


def seed_problem(source: str, result: str) -> str | None:
    """Why a (cleaned) rewrite is unusable, or None: empty, unchanged, far from the source's length,
    or missing a stretch of the source (the seeder was seen deleting whole closing paragraphs)."""
    if not result.strip():
        return "empty reply"
    if result.strip() == source.strip():
        return "identical to the source"
    ratio = len(result.split()) / max(1, len(source.split()))
    if not MIN_WORD_RATIO <= ratio <= MAX_WORD_RATIO:
        return f"length {ratio:.2f}x the source, outside {MIN_WORD_RATIO}x-{MAX_WORD_RATIO}x"
    removed = words_removed(source, result)
    if removed > MAX_WORDS_REMOVED:
        return f"deleted {removed} words of the source"
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


def highest_drafts(out: Path) -> dict[tuple[str, str, str], int]:
    """The highest draft number already in each (case, model, brief) folder of `out`."""
    found: dict[tuple[str, str, str], int] = {}
    for path in out.glob("*/*/continue/*/draft_*.md"):
        folder = (path.parts[-5], path.parts[-4], path.parts[-2])
        found[folder] = max(found.get(folder, 0), int(path.stem.split("_")[1]))
    return found


def plan_seeds(
    candidates: list[dict[str, Any]], per_rule: int, seed: int,
    rules: list[str] | None = None, taken: dict[tuple[str, str, str], int] | None = None,
) -> list[dict[str, Any]]:
    """`per_rule` distinct candidates for each of `rules` (default all), each `{rule, source, n}` with `n`
    counted per folder from 100, or after the highest draft number `taken` holds for that folder."""
    chosen = list(rules or RULES)
    need = per_rule * len(chosen)
    if len(candidates) < need:
        raise SystemExit(f"Only {len(candidates)} ok Continue drafts for {need} seeds ({per_rule} per rule): lower --per-rule.")
    picked = random.Random(seed).sample(candidates, need)
    counters = {k: max(v, FIRST_SEEDED_N - 1) for k, v in (taken or {}).items()}
    plan = []
    for i, source in enumerate(picked):
        folder = (source["case"], source["model"], source["brief"])
        counters[folder] = counters.get(folder, FIRST_SEEDED_N - 1) + 1
        plan.append({"rule": chosen[i // per_rule], "source": source, "n": counters[folder]})
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
        "source": source_address(source),
    }
    (folder / f"draft_{entry['n']}.md").write_text(text, encoding="utf-8")
    (folder / f"meta_{entry['n']}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return f"{source['case']}/{source['model']}/continue/{source['brief']}/draft_{entry['n']}.md"


def seeded_ok(out: Path, entry: dict[str, Any]) -> bool:
    """Whether this planned seed (this source draft and rule) was already written with status ok, under
    whatever number, so a rerun skips it."""
    source = entry["source"]
    folder = out / source["case"] / source["model"] / "continue" / source["brief"]
    origin = source_address(source)
    for meta in folder.glob("meta_*.json"):
        record = json.loads(meta.read_text(encoding="utf-8"))
        if record.get("status") == "ok" and record.get("seeded_rule") == entry["rule"] and record.get("source") == origin:
            return True
    return False


def source_address(source: dict[str, Any]) -> str:
    """The address of a source draft, as a seed's meta records it in `source`."""
    return f"{source['case']}/{source['model']}/continue/{source['brief']}/draft_{source['n']}.md"


def seeded_sources(out: Path, excluding_rules: Iterable[str] = ()) -> set[str]:
    """The `source` of every meta_*.json in `out` (any status), except seeds of `excluding_rules`."""
    skip = set(excluding_rules)
    found: set[str] = set()
    for meta in out.glob("*/*/continue/*/meta_*.json"):
        record = json.loads(meta.read_text(encoding="utf-8"))
        if record.get("source") and record.get("seeded_rule") not in skip:
            found.add(record["source"])
    return found


def ok_counts(out: Path) -> Counter[str]:
    """How many seeds in `out` were written with status ok, per rule."""
    metas = (json.loads(m.read_text(encoding="utf-8")) for m in out.glob("*/*/continue/*/meta_*.json"))
    return Counter(r["seeded_rule"] for r in metas if r.get("status") == "ok" and r.get("seeded_rule"))


def plan_run(
    candidates: list[dict[str, Any]], out: Path, per_rule: int, seed: int, rules: list[str] | None = None
) -> list[dict[str, Any]]:
    """The seeds still to ask for. A source another rule's seed already used is never picked again; this
    run's own rules are not excluded, so a rerun of the same command plans the same passages and skips
    those already seeded ok; once every rule has `per_rule` ok seeds nothing is planned."""
    chosen = rules or list(RULES)
    ok = ok_counts(out)
    if all(ok[rule] >= per_rule for rule in chosen):
        return []  # done; other runs' sources since excluded would only shift the draw
    used = seeded_sources(out, excluding_rules=chosen)
    fresh = [c for c in candidates if source_address(c) not in used]
    plan = plan_seeds(fresh, per_rule, seed, rules, highest_drafts(out))
    return [e for e in plan if not seeded_ok(out, e)]


def merge_run_json(existing: dict[str, Any] | None, run: dict[str, Any], source_run: Path, seeder_model: str) -> dict[str, Any]:
    """`out/run.json` after this seeding run: existing fields kept, models united by name (one name with two
    model ids is a SystemExit), `seeded_from` the distinct absolute source paths seen so far."""
    existing = existing or {}
    models = {m["name"]: m for m in existing.get("models", [])}
    for model in run["models"]:
        known = models.setdefault(model["name"], model)
        if known["model"] != model["model"]:
            raise SystemExit(f"{model['name']} is {known['model']} in the run.json already in the output, {model['model']} in {source_run}.")
    earlier = existing.get("seeded_from") or []
    earlier = [earlier] if isinstance(earlier, str) else earlier
    seeded_from = list(dict.fromkeys([*earlier, str(source_run)]))
    return {**run, **existing, "models": list(models.values()), "seeded_from": seeded_from, "seeder_model": seeder_model}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source_run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rules", nargs="+", choices=list(RULES), help="seed only these rules (default all)")
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
    plan = plan_run(candidates, args.out, args.per_rule, args.seed, args.rules)
    if not plan:
        print(f"every passage in {args.out} is already seeded")
        return
    run_json = args.out / "run.json"
    existing = json.loads(run_json.read_text(encoding="utf-8")) if run_json.is_file() else None
    merged = merge_run_json(existing, run, source_run, seeder["model"])
    book, base_url = load_book(), discover_backend()
    projects = {c: load_fixture(c)["continue"] for c in {e["source"]["case"] for e in plan}}
    clients = {c: Client(base_url, p["root"], timeout=CALL_TIMEOUT_S) for c, p in projects.items()}
    args.out.mkdir(parents=True, exist_ok=True)
    run_json.write_text(json.dumps(merged, indent=2), encoding="utf-8")
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
