"""Blind pairs of the prose harness (#2617, measuring-prose-quality.md §4.4 and §6).

  pairs.py make BASELINE_RUN NEW_RUN --out DIR [--words 400] [--seed 2617] [--model NAME]
      Draws one pair per (style case, brief): the first ~WORDS words of a baseline and of a new
      Draft scene draft of the primary model. Writes DIR/send/pairs.html (the page for the reader,
      shuffled and unlabelled, nothing of the key in it) and DIR/key.json (which side is new,
      where each excerpt came from and the excerpts as shown: it stays in DIR, never sent).
  pairs.py tally DIR/key.json PICKS.json [PICKS2.json ...] [--out DIR/result.md]
      Reads one or more readers' downloaded picks files and reports new-preferred against
      baseline-preferred (overall, per reader and per style case, with a two-sided sign test)
      and the sentences the readers would cut, per side, as the PR's measurement section.

Nothing here touches a backend or a model; the page is one HTML file that works offline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from checks import count_words, iter_drafts  # noqa: E402
from fixture_gen import CASES, load_book  # noqa: E402
from judge import passage_context  # noqa: E402

PAGE_TEMPLATE = Path(__file__).resolve().parent / "pairs_page.html"
PROMPT = "draft_scene"
DEFAULT_SEED = 2617
DEFAULT_WORDS = 400
ABBREVIATIONS = frozenset(("Mr", "Mrs", "Ms", "Dr", "St", "Mt", "Jr", "Sr", "Prof"))
SENTENCE_BREAK = re.compile(r"[.!?…]+[”’\"')\]]*(\s+)")
PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
LAST_WORD = re.compile(r"(\w+)\.$")


# --- excerpts ------------------------------------------------------------------


def sentences(paragraph: str) -> list[str]:
    """A paragraph split into sentences, each keeping its closing quote marks. No split inside an
    abbreviation (Mr., Dr., ...) or before a lowercase letter (`"Why?" she said.`)."""
    text = " ".join(paragraph.split())
    out: list[str] = []
    start = 0
    for match in SENTENCE_BREAK.finditer(text):
        end = match.start(1)
        head = text[start:end]
        following = text[match.end(1): match.end(1) + 1]
        abbreviation = LAST_WORD.search(head)
        if (abbreviation and abbreviation.group(1) in ABBREVIATIONS) or following.islower():
            continue
        out.append(head)
        start = match.end(1)
    if text[start:]:
        out.append(text[start:])
    return out


def excerpt_paragraphs(text: str, words: int) -> list[list[str]]:
    """The leading whole sentences of `text`, as paragraphs of sentences, while the running word
    count stays within `words`. A first sentence longer than that is still taken whole."""
    taken: list[list[str]] = []
    total = 0
    for paragraph in PARAGRAPH_BREAK.split(text.strip()):
        mine: list[str] = []
        for sentence in sentences(paragraph):
            size = count_words(sentence)
            if (taken or mine) and total + size > words:
                return [*taken, mine] if mine else taken
            mine.append(sentence)
            total += size
        if mine:
            taken.append(mine)
    return taken


def join_excerpt(paragraphs: list[list[str]]) -> str:
    return "\n\n".join(" ".join(p) for p in paragraphs)


def excerpt(text: str, words: int) -> str:
    """The first whole sentences of `text` up to `words` words, paragraph breaks kept."""
    return join_excerpt(excerpt_paragraphs(text, words))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- the draw ------------------------------------------------------------------


def primary_model(run_dir: Path) -> str:
    """The run.json model flagged `primary`."""
    path = run_dir / "run.json"
    if not path.is_file():
        raise SystemExit(f"{path} is missing: not a run directory.")
    models = json.loads(path.read_text(encoding="utf-8")).get("models") or []
    names = [m["name"] for m in models if m.get("primary")]
    if not names:
        raise SystemExit(f"{path} has no model flagged primary: pass --model NAME.")
    return names[0]


def choose_model(baseline: Path, new: Path, override: str | None) -> str:
    if override:
        return override
    a, b = primary_model(baseline), primary_model(new)
    if a != b:
        raise SystemExit(f"The runs' primary models differ ({a} / {b}): pass --model NAME.")
    return a


def cells(run_dir: Path, model: str) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """The ok Draft scene drafts of `model`, by (case, brief)."""
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for d in iter_drafts(run_dir):
        if d["prompt"] == PROMPT and d["model"] == model and d["meta"].get("status", "ok") == "ok":
            out.setdefault((d["case"], d["brief"]), []).append(d)
    return out


def draft_path(d: dict[str, Any]) -> str:
    return f"{d['case']}/{d['model']}/{d['prompt']}/{d['brief']}/draft_{d['n']}.md"


def draw(
    baseline: dict[tuple[str, str], list[dict[str, Any]]],
    new: dict[tuple[str, str], list[dict[str, Any]]],
    seed: int,
    cases: tuple[str, ...] = CASES,
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """`(pairs, skipped)`: one `{case, brief, baseline, new, new_side}` per cell of `cases` present on
    both sides (in shuffled order), and the cells missing on one side. Fewer cases mean fewer pairs to
    read, and a higher bar: a sign test on 12 pairs needs 10 to rule out chance."""
    rng = random.Random(seed)
    keys = sorted({*baseline, *new}, key=lambda k: (CASES.index(k[0]) if k[0] in CASES else len(CASES), k))
    pairs: list[dict[str, Any]] = []
    skipped: list[tuple[str, str]] = []
    for key in keys:
        if key[0] not in cases:
            continue
        if not baseline.get(key) or not new.get(key):
            skipped.append(key)
            continue
        pairs.append({
            "case": key[0], "brief": key[1],
            "baseline": rng.choice(baseline[key]), "new": rng.choice(new[key]),
            "new_side": rng.choice("AB"),
        })
    rng.shuffle(pairs)
    return pairs, skipped


# --- the page ------------------------------------------------------------------


def page_id(pairs: list[dict[str, Any]]) -> str:
    canonical = json.dumps(pairs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha(canonical)[:16]


def script_json(data: dict[str, Any]) -> str:
    """JSON safe inside a script element: `<` is escaped so no text can close the tag."""
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def build_pairs(drawn: list[dict[str, Any]], words: int, book: dict[str, Any]) -> list[dict[str, Any]]:
    """Per drawn pair `{"page": ..., "key": ...}`: what the page shows (`id`, `pov`, `summary`, `A`,
    `B`) and what the key records (the sources, which side is new, the excerpts' hashes)."""
    out = []
    for i, p in enumerate(drawn, start=1):
        sides = {"new": excerpt_paragraphs(p["new"]["text"], words), "baseline": excerpt_paragraphs(p["baseline"]["text"], words)}
        a, b = (sides["new"], sides["baseline"]) if p["new_side"] == "A" else (sides["baseline"], sides["new"])
        context = passage_context(book, {"prompt": PROMPT, "brief": p["brief"]})
        pid = f"p{i:02d}"
        out.append({
            "page": {"id": pid, "pov": context["pov"], "summary": context["summary"], "A": a, "B": b},
            # The key keeps the sentences exactly as the page showed them, so the tally maps cuts
            # without re-deriving excerpts (a later change to the splitter can't move them).
            "key": {
                "case": p["case"], "brief": p["brief"], "new_side": p["new_side"],
                "baseline": draft_path(p["baseline"]), "new": draft_path(p["new"]),
                "A": a, "B": b,
            },
        })
    return out


def make(
    baseline_run: Path, new_run: Path, out: Path, words: int, seed: int, model: str | None,
    cases: tuple[str, ...] = CASES,
) -> None:
    name = choose_model(baseline_run, new_run, model)
    drawn, skipped = draw(cells(baseline_run, name), cells(new_run, name), seed, cases)
    for case, brief in skipped:
        print(f"skipped {case}/{brief}: no ok draft on one side")
    if not drawn:
        raise SystemExit(f"No (case, brief) cell has an ok {PROMPT} draft of {name} in both runs.")
    built = build_pairs(drawn, words, load_book())
    pages = [b["page"] for b in built]
    pid = page_id(pages)
    html = PAGE_TEMPLATE.read_text(encoding="utf-8").replace("__PAIRS_DATA__", script_json({"page_id": pid, "pairs": pages}))
    key = {
        "page_id": pid, "baseline_run": str(baseline_run.resolve()), "new_run": str(new_run.resolve()),
        "model": name, "words": words, "seed": seed,
        "pairs": {b["page"]["id"]: b["key"] for b in built},
    }
    # The page gets a folder of its own, so the folder a reader is sent never holds the key.
    send = out / "send"
    send.mkdir(parents=True, exist_ok=True)
    (send / "pairs.html").write_text(html, encoding="utf-8")
    (out / "key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    total = sum(count_words(join_excerpt(p[side])) for p in pages for side in ("A", "B"))
    print(f"wrote {send / 'pairs.html'} and {out / 'key.json'}: {len(pages)} pairs, {total} words to read")
    print(f"send only {send}: key.json says which side is new and stays where it is.")


# --- the tally -----------------------------------------------------------------


def sign_test(wins: int, losses: int) -> float:
    """Two-sided exact sign test p-value (binomial, p = 0.5) on `wins` against `losses`."""
    n = wins + losses
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, i) for i in range(min(wins, losses) + 1))
    return min(1.0, 2 * tail / 2**n)


def load_picks(path: Path, key: dict[str, Any]) -> dict[str, Any]:
    """One readers' picks file, refused unless made on this key's page and well formed."""
    picks = json.loads(path.read_text(encoding="utf-8"))
    if picks.get("page_id") != key["page_id"]:
        raise SystemExit(f"{path} was made on a different page ({picks.get('page_id')}, not {key['page_id']}).")
    for pid, value in (picks.get("picks") or {}).items():
        if pid not in key["pairs"]:
            raise SystemExit(f"{path}: unknown pair {pid}.")
        if value not in ("A", "B"):
            raise SystemExit(f"{path}: pair {pid} has pick {value!r}, not A or B.")
    for pid in picks.get("cuts") or {}:
        if pid not in key["pairs"]:
            raise SystemExit(f"{path}: cuts for unknown pair {pid}.")
    return picks


def cut_sentences(key: dict[str, Any], picks: dict[str, Any]) -> dict[str, list[str]]:
    """`{"new": [...], "baseline": [...]}`: the sentences one reader cut, read from the excerpts the
    key recorded and mapped to new or baseline through the key."""
    out: dict[str, list[str]] = {"new": [], "baseline": []}
    for pid, by_side in (picks.get("cuts") or {}).items():
        record = key["pairs"][pid]
        sides = {"A": record["A"], "B": record["B"]}
        new_side = record["new_side"]
        for side, addresses in by_side.items():
            for para, sent in sorted({tuple(a) for a in addresses}):
                try:
                    text = sides[side][para][sent]
                except (KeyError, IndexError, TypeError):
                    raise SystemExit(f"{pid}: cut [{para}, {sent}] on side {side} is outside the excerpt.") from None
                out["new" if side == new_side else "baseline"].append(text)
    return out


def count_picks(key: dict[str, Any], picks: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Per style case plus `"all"`: `{new, baseline, unanswered}` for one picks file."""
    totals: dict[str, dict[str, int]] = {"all": {"new": 0, "baseline": 0, "unanswered": 0}}
    for pid, record in key["pairs"].items():
        bucket = totals.setdefault(record["case"], {"new": 0, "baseline": 0, "unanswered": 0})
        pick = (picks.get("picks") or {}).get(pid)
        outcome = "unanswered" if pick is None else ("new" if pick == record["new_side"] else "baseline")
        bucket[outcome] += 1
        totals["all"][outcome] += 1
    return totals


def pair_votes(key: dict[str, Any], readers: list[tuple[str, dict[str, Any]]]) -> dict[str, dict[str, int]]:
    """Per style case plus `"all"`: one vote per pair, the side most readers kept (`new` or
    `baseline`), a tie, or `unanswered` when no reader picked it. Readers judge the same 20 pairs,
    so the pairs are the independent trials: pooling every reader's picks would overstate p."""
    totals: dict[str, dict[str, int]] = {"all": {"new": 0, "baseline": 0, "tie": 0, "unanswered": 0}}
    for pid, record in key["pairs"].items():
        bucket = totals.setdefault(record["case"], {"new": 0, "baseline": 0, "tie": 0, "unanswered": 0})
        picks = [(p.get("picks") or {}).get(pid) for _, p in readers]
        new = sum(1 for x in picks if x == record["new_side"])
        old = sum(1 for x in picks if x is not None and x != record["new_side"])
        outcome = "unanswered" if new == old == 0 else "tie" if new == old else "new" if new > old else "baseline"
        bucket[outcome] += 1
        totals["all"][outcome] += 1
    return totals


def split_line(counts: dict[str, int]) -> str:
    p = sign_test(counts["new"], counts["baseline"])
    tie = f", tied {counts['tie']}" if counts.get("tie") else ""
    return f"new {counts['new']}, baseline {counts['baseline']}{tie}, unanswered {counts['unanswered']} (p = {p:.3f})"


def render_result(key: dict[str, Any], readers: list[tuple[str, dict[str, Any]]]) -> str:
    """The measurement section as Markdown for a PR body."""
    votes = pair_votes(key, readers)
    cuts: dict[str, list[str]] = {"new": [], "baseline": []}
    for _, picks in readers:
        for side, found in cut_sentences(key, picks).items():
            cuts[side] += found
    unit = "per pair, the side most readers kept; ties dropped" if len(readers) > 1 else "answered pairs only"
    lines = [
        "### Blind pairs (H4)", "",
        f"Model `{key['model']}`, {len(key['pairs'])} pairs of about {key['words']} words, "
        f"{len(readers)} reader{'s' if len(readers) != 1 else ''}: {', '.join(r for r, _ in readers)}.", "",
        f"**Preference** (two-sided sign test, {unit}): {split_line(votes['all'])}.", "",
    ]
    if len(readers) > 1:
        lines += ["| reader | new | baseline | unanswered | p |", "|---|---|---|---|---|"]
        for label, picks in readers:
            c = count_picks(key, picks)["all"]
            lines.append(f"| {label} | {c['new']} | {c['baseline']} | {c['unanswered']} | {sign_test(c['new'], c['baseline']):.3f} |")
        lines.append("")
    lines += ["| style case | new | baseline | unanswered | p |", "|---|---|---|---|---|"]
    for case in [c for c in CASES if c in votes]:
        c = votes[case]
        lines.append(f"| {case} | {c['new']} | {c['baseline']} | {c['unanswered']} | {sign_test(c['new'], c['baseline']):.3f} |")
    lines += ["", f"**Sentences cut:** new side {len(cuts['new'])}, baseline side {len(cuts['baseline'])}.", ""]
    for side in ("new", "baseline"):
        lines += [f"<details><summary>Cut on the {side} side ({len(cuts[side])})</summary>", ""]
        lines += [f"- {s}" for s in cuts[side]] or ["- none"]
        lines += ["", "</details>", ""]
    return "\n".join(lines)


def tally(key_path: Path, picks_paths: list[Path]) -> str:
    key = json.loads(key_path.read_text(encoding="utf-8"))
    readers = []
    seen: dict[str, Path] = {}
    for i, path in enumerate(picks_paths, start=1):
        picks = load_picks(path, key)
        name = (picks.get("reader") or "").strip()
        # One file per reader: a second download of the same reading would count its picks twice.
        same = name.casefold() if name else json.dumps(picks.get("picks"), sort_keys=True)
        if same in seen:
            raise SystemExit(f"{path} and {seen[same]} look like the same reader: pass only the latest file per reader.")
        seen[same] = path
        readers.append((name or f"reader {i}", picks))
    return render_result(key, readers)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    mk = sub.add_parser("make", help="draw the pairs and write the page and the key")
    mk.add_argument("baseline_run", type=Path)
    mk.add_argument("new_run", type=Path)
    mk.add_argument("--out", type=Path, required=True)
    mk.add_argument("--words", type=int, default=DEFAULT_WORDS)
    mk.add_argument("--seed", type=int, default=DEFAULT_SEED)
    mk.add_argument("--model", help="the model name to draw from (default: both runs' primary)")
    mk.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES),
                    help="style cases to draw from (default: all; fewer cases, fewer pairs)")
    tl = sub.add_parser("tally", help="report the readers' picks against the key")
    tl.add_argument("key", type=Path)
    tl.add_argument("picks", type=Path, nargs="+")
    tl.add_argument("--out", type=Path, help="where to write the Markdown (default DIR/result.md)")
    args = parser.parse_args()
    if args.command == "make":
        make(args.baseline_run, args.new_run, args.out, args.words, args.seed, args.model, tuple(args.cases))
        return
    result = tally(args.key, args.picks)
    out = args.out or args.key.parent / "result.md"
    out.write_text(result, encoding="utf-8")
    print(result)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
