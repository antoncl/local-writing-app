"""Reports, the noise band and the comparison for the prose harness (#2613).

Everything is per cell - (case, model, prompt, brief) - and per (case, model,
prompt) group, never one blended score (measuring-prose-quality.md §4, §8).

  report.py RUN_DIR
      Writes RUN_DIR/checks.json and RUN_DIR/report.md: the mean of each script
      check over a cell's drafts, the draft count and the out-of-reach count.
  report.py --band RUN_A RUN_B --out BAND.json
      The noise band (§2): per cell per metric, abs(mean_A - mean_B). Refused
      unless the two runs used the same prompt hashes, the same book.yaml and
      the same model list - an A/A must be the unchanged baseline.
  report.py --compare NEW --baseline RUN_A RUN_B
      NEW beside the baseline (the mean of the two A/A runs) and the band, one
      table per metric. A difference is flagged only when it exceeds the band.

A draft whose step failed (status out_of_reach or error) is counted, not scored.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from checks import TARGET_WORDS, analyze, iter_drafts, load_phrases, load_samples  # noqa: E402

PHRASES_PATH = Path(__file__).resolve().parent / "phrases.yaml"
BOOK_PATH = Path(__file__).resolve().parent / "fixture" / "book.yaml"

METRICS = (
    "words", "target_ratio", "italic_spans", "digits_below_ten", "numerals", "emdash_spaced",
    "emdash_closed", "tag_adverbs", "emotion_words", "contractions_narration", "ly_adverbs_narration",
    "phrase_hits", "said_share", "long_sentence_share", "sentence_mean", "sentence_sd",
    "has_markdown", "starts_with_preamble", "sample_overlap",
)
# Lower is better only for failures in any style: named emotions, common-list
# phrases, markdown, a preamble, a lifted voice sample. Italics, numerals, dashes,
# contractions, adverbs and sentence length are mechanics the style notes disagree
# on (the lush note wants italic thought, the hard-boiled one numerals), so a move
# in them is flagged "changed", never "better" or "worse": whether it is right
# depends on the note, which is the judge's call (H2), not the script's.
LOWER_IS_BETTER = frozenset({
    "emotion_words", "phrase_hits", "has_markdown", "starts_with_preamble", "sample_overlap",
})
NO_DIRECTION = frozenset({"words", "target_ratio", "said_share", "sentence_mean", "sentence_sd"})
REFUSED_BAND_KEYS = ("prompts", "book_yaml_sha256", "models")


def mean_or_none(values: list[Any]) -> float | None:
    present = [float(v) for v in values if v is not None]
    return round(statistics.fmean(present), 4) if present else None


def cell_key(item: dict[str, Any]) -> str:
    return "|".join(str(item[k]) for k in ("case", "model", "prompt", "brief"))


def group_key(item: dict[str, Any]) -> str:
    return "|".join(str(item[k]) for k in ("case", "model", "prompt"))


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts and per-metric means over one cell's (or group's) drafts."""
    scored = [i["metrics"] for i in items if i["status"] == "ok"]
    return {
        "drafts": len(items),
        "ok": len(scored),
        "out_of_reach": sum(1 for i in items if i["status"] == "out_of_reach"),
        "errors": sum(1 for i in items if i["status"] == "error"),
        "metrics": {m: mean_or_none([s.get(m) for s in scored]) for m in METRICS},
    }


def scored_drafts(run_dir: Path) -> list[dict[str, Any]]:
    phrases = load_phrases(PHRASES_PATH)
    samples = load_samples(BOOK_PATH)
    drafts = []
    for item in iter_drafts(run_dir):
        status = item["meta"].get("status", "ok")
        metrics = analyze(item["text"], TARGET_WORDS.get(item["prompt"], 0), phrases, samples) if status == "ok" else {}
        drafts.append({**{k: item[k] for k in ("case", "model", "prompt", "brief", "n")}, "status": status, "metrics": metrics})
    return drafts


def summarize_run(run_dir: Path) -> dict[str, Any]:
    drafts = scored_drafts(run_dir)
    cells: dict[str, list[dict[str, Any]]] = {}
    groups: dict[str, list[dict[str, Any]]] = {}
    for d in drafts:
        cells.setdefault(cell_key(d), []).append(d)
        groups.setdefault(group_key(d), []).append(d)
    return {
        "cells": {k: {**summarize(v), "brief": v[0]["brief"]} for k, v in sorted(cells.items())},
        "groups": {k: summarize(v) for k, v in sorted(groups.items())},
    }


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def render_report(summary: dict[str, Any]) -> str:
    lines = ["# Script checks", "", "Means over the drafts that completed; no blended score.", ""]
    groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for key, cell in summary["cells"].items():
        groups.setdefault("|".join(key.split("|")[:3]), []).append((key.split("|")[3], cell))
    for gkey, rows in groups.items():
        lines += [f"## {gkey.replace('|', ' / ')}", "", "| brief | ok/drafts | out of reach | " + " | ".join(METRICS) + " |"]
        lines.append("|" + "---|" * (len(METRICS) + 3))
        for brief, cell in rows:
            vals = " | ".join(_fmt(cell["metrics"][m]) for m in METRICS)
            lines.append(f"| {brief} | {cell['ok']}/{cell['drafts']} | {cell['out_of_reach']} | {vals} |")
        g = summary["groups"][gkey]
        vals = " | ".join(_fmt(g["metrics"][m]) for m in METRICS)
        lines += [f"| **all briefs** | {g['ok']}/{g['drafts']} | {g['out_of_reach']} | {vals} |", ""]
    return "\n".join(lines)


def write_report(run_dir: Path) -> None:
    summary = summarize_run(run_dir)
    (run_dir / "checks.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(f"wrote {run_dir / 'checks.json'} and {run_dir / 'report.md'}")


def load_run_json(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "run.json"
    if not path.is_file():
        raise SystemExit(f"{run_dir} has no run.json - not a run folder.")
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_comparable(run_a: Path, run_b: Path) -> None:
    """Refuse an A/A band across runs that are not the same unchanged baseline."""
    a, b = load_run_json(run_a), load_run_json(run_b)
    differing = [k for k in REFUSED_BAND_KEYS if a.get(k) != b.get(k)]
    if differing:
        raise SystemExit(
            f"Refusing the noise band: {run_a.name} and {run_b.name} differ in {', '.join(differing)}. "
            "An A/A is the unchanged baseline run twice."
        )


def band_between(summary_a: dict[str, Any], summary_b: dict[str, Any], level: str) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    for key in sorted(set(summary_a[level]) | set(summary_b[level])):
        ma = summary_a[level].get(key, {}).get("metrics", {})
        mb = summary_b[level].get(key, {}).get("metrics", {})
        out[key] = {
            m: (round(abs(ma[m] - mb[m]), 4) if ma.get(m) is not None and mb.get(m) is not None else None)
            for m in METRICS
        }
    return out


def make_band(run_a: Path, run_b: Path) -> dict[str, Any]:
    ensure_comparable(run_a, run_b)
    sa, sb = summarize_run(run_a), summarize_run(run_b)
    return {
        "runs": [run_a.name, run_b.name],
        "cells": band_between(sa, sb, "cells"),
        "groups": band_between(sa, sb, "groups"),
    }


def flag_for(metric: str, baseline: float | None, new: float | None, band: float | None) -> str:
    if baseline is None or new is None or band is None or metric in NO_DIRECTION:
        return ""
    if abs(new - baseline) <= band:
        return ""
    if metric not in LOWER_IS_BETTER:
        return "changed"
    return "worse" if new > baseline else "better"


def _count(summary: dict[str, Any], key: str, field: str) -> int:
    return summary["cells"].get(key, {}).get(field, 0)


def render_compare(new: dict[str, Any], sa: dict[str, Any], sb: dict[str, Any], band: dict[str, Any]) -> str:
    lines = ["# Comparison with the baseline", "",
             "Baseline is the mean of the two A/A runs; the band is their absolute difference. "
             "A flag appears only when the new mean is further from the baseline than the band.", ""]
    keys = sorted(set(new["cells"]) | set(sa["cells"]) | set(sb["cells"]))
    for metric in METRICS:
        lines += [f"## {metric}", "", "| cell | baseline | new | band | flag | out of reach (base A/B, new) |", "|---|---|---|---|---|---|"]
        for key in keys:
            base = mean_or_none([sa["cells"].get(key, {}).get("metrics", {}).get(metric),
                                 sb["cells"].get(key, {}).get("metrics", {}).get(metric)])
            cur = new["cells"].get(key, {}).get("metrics", {}).get(metric)
            width = band["cells"].get(key, {}).get(metric)
            oor = f"{_count(sa, key, 'out_of_reach')}/{_count(sb, key, 'out_of_reach')}, {_count(new, key, 'out_of_reach')}"
            lines.append(f"| {key.replace('|', ' / ')} | {_fmt(base)} | {_fmt(cur)} | {_fmt(width)} | {flag_for(metric, base, cur, width)} | {oor} |")
        lines.append("")
    return "\n".join(lines)


def compare(new_dir: Path, run_a: Path, run_b: Path) -> str:
    band = make_band(run_a, run_b)
    return render_compare(summarize_run(new_dir), summarize_run(run_a), summarize_run(run_b), band)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("run_dir", nargs="?", type=Path, help="write checks.json and report.md for this run")
    parser.add_argument("--band", nargs=2, type=Path, metavar=("RUN_A", "RUN_B"))
    parser.add_argument("--out", type=Path, help="where --band writes its JSON")
    parser.add_argument("--compare", type=Path, metavar="NEW")
    parser.add_argument("--baseline", nargs=2, type=Path, metavar=("RUN_A", "RUN_B"))
    args = parser.parse_args()
    if args.band:
        if not args.out:
            parser.error("--band needs --out")
        args.out.write_text(json.dumps(make_band(*args.band), indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    elif args.compare:
        if not args.baseline:
            parser.error("--compare needs --baseline RUN_A RUN_B")
        text = compare(args.compare, *args.baseline)
        (args.compare / "compare.md").write_text(text, encoding="utf-8")
        print(text)
    elif args.run_dir:
        write_report(args.run_dir)
    else:
        parser.error("give RUN_DIR, --band, or --compare")


if __name__ == "__main__":
    main()
