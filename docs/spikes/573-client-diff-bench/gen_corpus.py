"""Emit the shared benchmark corpus for #573 and time the Python baseline.

Authors every (was, now) input once, computes the backend `diff_runs` for each
(so the TS port can be checked for byte-parity), and times Python per bucket.
Run with the primary venv's interpreter and PYTHONPATH pointed at the worktree
backend so it benchmarks the code being ported, not another checkout:

  PYTHONPATH=<worktree>/backend <primary-venv>/python.exe gen_corpus.py <out.json>
"""

from __future__ import annotations

import json
import random
import sys
from time import perf_counter

sys.path.insert(0, "backend/tests")
from diff_fuzz import WORDS, fuzz_cases  # noqa: E402

from app.services.project.snapshot_diff import diff_runs  # noqa: E402

VOCAB = WORDS + [
    "lantern", "cobbled", "distant", "whisper", "iron", "threshold", "narrow", "beneath",
    "shoulder", "window", "waiting", "answer", "returned", "silence", "gathered", "pale",
    "corner", "letter", "burning", "hollow", "remember", "forgotten", "certain", "beyond",
]
CONSTRUCTS = ("**{a}**", "*{a} {b}*", "[{a}](lore://loc-{b})", "`{a}`")


def _para(rng: random.Random, n: int) -> str:
    out: list[str] = []
    while len(out) < n:
        if rng.random() < 0.08:
            out.append(rng.choice(CONSTRUCTS).format(a=rng.choice(VOCAB), b=rng.choice(VOCAB)))
        else:
            out.append(rng.choice(VOCAB))
    return " ".join(out)


def _scene(rng: random.Random, words: int) -> str:
    paras: list[str] = []
    remaining = words
    while remaining > 0:
        n = min(remaining, rng.randint(45, 90))
        paras.append(_para(rng, n))
        remaining -= n
    return "\n\n".join(paras)


def _edit_scene(rng: random.Random, doc: str) -> str:
    paras = doc.split("\n\n")
    for _ in range(rng.randint(2, 3)):  # tweak a few words in a few paragraphs
        p = rng.randrange(len(paras))
        w = paras[p].split(" ")
        for _ in range(rng.randint(1, 4)):
            if len(w) > 3:
                w[rng.randrange(len(w))] = rng.choice(VOCAB)
        paras[p] = " ".join(w)
    paras.insert(rng.randrange(len(paras) + 1), _para(rng, rng.randint(45, 90)))  # insert a paragraph
    if rng.random() < 0.5:  # fully rewrite one
        p = rng.randrange(len(paras))
        paras[p] = _para(rng, len(paras[p].split(" ")))
    return "\n\n".join(paras)


def _worst_para(rng: random.Random, tokens: int) -> tuple[str, str]:
    """One big paragraph, every third word replaced — the superlinear stress case."""
    words = [rng.choice(VOCAB) for _ in range(tokens)]
    was = " ".join(words)
    now_words = list(words)
    for i in range(0, len(now_words), 3):
        now_words[i] = rng.choice(VOCAB)
    return was, " ".join(now_words)


def build_cases() -> list[dict]:
    cases: list[dict] = []
    for c in fuzz_cases(400):
        cases.append({"name": c["name"], "bucket": "fuzz", "was": c["was"], "now": c["now"]})

    rng = random.Random(573)
    for words, count, bucket in ((500, 8, "scene-500"), (1500, 8, "scene-1500"), (4000, 6, "scene-4000")):
        for k in range(count):
            was = _scene(rng, words)
            cases.append({"name": f"{bucket}-{k}", "bucket": bucket, "was": was, "now": _edit_scene(rng, was)})

    for k in range(4):
        was, now = _worst_para(rng, 1500)
        cases.append({"name": f"worst-para-{k}", "bucket": "worst-para", "was": was, "now": now})

    return cases


def runs_json(was: str, now: str) -> list[dict]:
    return [{"kind": r.kind, "text": r.text, "stacked": r.stacked} for r in diff_runs(was, now)]


def time_bucket(cases: list[dict], min_time: float = 1.5, min_iters: int = 3) -> dict:
    for c in cases:  # warmup
        diff_runs(c["was"], c["now"])
    iters = 0
    t0 = perf_counter()
    while True:
        for c in cases:
            diff_runs(c["was"], c["now"])
        iters += 1
        if perf_counter() - t0 >= min_time and iters >= min_iters:
            break
    elapsed = perf_counter() - t0
    calls = iters * len(cases)
    return {"cases": len(cases), "iters": iters, "calls": calls, "per_call_ms": elapsed / calls * 1000.0}


def main() -> None:
    out_path = sys.argv[1]
    cases = build_cases()
    for c in cases:
        c["runs"] = runs_json(c["was"], c["now"])

    buckets: dict[str, list[dict]] = {}
    for c in cases:
        buckets.setdefault(c["bucket"], []).append(c)

    py = {name: time_bucket(group) for name, group in buckets.items()}
    for name, stats in py.items():
        avg_words = sum(len(c["was"].split()) for c in buckets[name]) / len(buckets[name])
        print(f"  py  {name:12s} n={stats['cases']:3d} ~{avg_words:6.0f}w  {stats['per_call_ms']:.4f} ms/call")

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"cases": cases, "py": py}, fh, ensure_ascii=False)
    print(f"wrote {len(cases)} cases -> {out_path}")


if __name__ == "__main__":
    main()
