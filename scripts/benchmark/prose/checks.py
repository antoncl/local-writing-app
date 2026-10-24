"""Script checks for the prose harness (#2613, measuring-prose-quality.md §4.1).

Exact, free counts of what can be counted: rule-following signals, never quality.
`analyze()` and its helpers are pure functions of the draft text. The only I/O in
this module is `iter_drafts()` and `main()`, which scan a run directory
(`run.py`'s `<case>/<model>/<prompt>/<brief>/draft_<n>.md` layout).

Dialogue is text inside straight or curly double quotes (one line each);
narration is the rest. Words are `\\b[\\w’']+\\b`.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

TARGET_WORDS = {"draft_scene": 1200, "continue": 300}

SPEECH_VERBS = (
    "said", "asked", "replied", "answered", "whispered", "murmured", "muttered", "shouted", "called",
    "added", "conceded", "snapped", "admitted", "insisted", "began", "continued", "sighed", "laughed",
    "lied", "agreed",
)
EMOTION_WORDS = (
    "felt", "feel", "feeling", "feelings", "realized", "realised", "realization", "couldn't help",
    "sense of", "wave of", "pang of", "surge of", "heart pounded", "heart raced", "heart sank",
    "breath she didn't know", "breath he didn't know",
)
LY_STOPLIST = frozenset((
    "only", "early", "family", "reply", "holy", "ugly", "likely", "lonely", "friendly", "daily", "belly",
    "jelly", "rally", "supply", "apply", "fly", "july", "sally", "tilly", "lily",
))
LONG_SENTENCE_WORDS = 25

WORD = re.compile(r"\b[\w’']+\b")
DIALOGUE = re.compile(r"\"[^\"\n]*\"|“[^”\n]*”")
SENTENCE_END = re.compile(r"(?<=[.!?…])[\"”’')\]]*\s+")
ITALIC = re.compile(r"(?<![*\w])\*(?!\*)([^*\n]+?)(?<!\*)\*(?![*\w])|(?<![\w_])_(?!_)([^_\n]+?)(?<!_)_(?![\w_])")
CONTRACTION = re.compile(r"\w['’](?:t|d|ll|re|ve|m)\b")
LY_WORD = re.compile(r"\b\w{3,}ly\b")
LY_TOKEN = re.compile(r"\w+ly\b")
DIGIT_BELOW_TEN = re.compile(r"\b\d\b")
NUMERAL = re.compile(r"\d+")
EMDASH_SPACED = re.compile(r" — | -- ")
EMDASH_CLOSED = re.compile(r"\w—\w")
PREAMBLE = re.compile(r"(?:here is|here's|sure|certainly)\b", re.IGNORECASE)
MARKDOWN_LINE = re.compile(r"^\s*(?:#|\*\*)", re.MULTILINE)

_SUBJECT = r"(?:he|she|they|I|[A-Z][a-z]+)"
_VERBS = "|".join(SPEECH_VERBS)
TAG_SUBJECT_FIRST = re.compile(rf"\b{_SUBJECT}\s+({_VERBS})\b")
TAG_VERB_FIRST = re.compile(rf"\b({_VERBS})\s+{_SUBJECT}\b")
TAG_WINDOW = 40


def normalize(text: str) -> str:
    """Straighten the curly apostrophe so contraction and phrase matching sees one form."""
    return text.replace("’", "'")


def per_1000(count: float, words: int) -> float:
    return round(count * 1000 / words, 3) if words else 0.0


def count_words(text: str) -> int:
    return len(WORD.findall(text))


def split_dialogue(text: str) -> tuple[str, str]:
    """`(dialogue, narration)`: quoted spans joined by newlines, and the rest with them blanked."""
    dialogue = "\n".join(m.group(0)[1:-1] for m in DIALOGUE.finditer(text))
    narration = DIALOGUE.sub(" ", text)
    return dialogue, narration


def speech_tags(text: str) -> list[tuple[str, str]]:
    """`(verb, following_text)` for each closing quote followed by a speech-verb tag.

    The tag must start within 40 characters of the closing quote and before the
    next quote mark; `following_text` is what comes after the tag verb, up to the
    end of that sentence.
    """
    tags: list[tuple[str, str]] = []
    for match in DIALOGUE.finditer(text):
        window = text[match.end(): match.end() + TAG_WINDOW]
        window = re.split(r"[\"“”]", window, maxsplit=1)[0]
        found = [m for m in (TAG_SUBJECT_FIRST.search(window), TAG_VERB_FIRST.search(window)) if m]
        if not found:
            continue
        first = min(found, key=lambda m: m.start())
        verb_end = first.end(1)
        rest = re.split(r"[.!?]", text[match.end() + verb_end:], maxsplit=1)[0]
        tags.append((first.group(1), rest))
    return tags


def has_tag_adverb(following: str) -> bool:
    """A `-ly` word within the two tokens after a tag verb."""
    tokens = WORD.findall(following)[:2]
    return any(LY_TOKEN.fullmatch(token) for token in tokens)


def count_phrases(text: str, phrases: tuple[str, ...] | list[str]) -> int:
    lowered = normalize(text).lower()
    return sum(lowered.count(normalize(p).lower()) for p in phrases if p)


def count_emotion_words(text: str) -> int:
    lowered = normalize(text).lower()
    return sum(len(re.findall(rf"\b{re.escape(p)}\b", lowered)) for p in EMOTION_WORDS)


def count_ly_adverbs(narration: str) -> int:
    return sum(1 for w in LY_WORD.findall(narration) if w.lower() not in LY_STOPLIST)


def count_italics(narration: str) -> int:
    return len(ITALIC.findall(narration))


def sentence_stats(text: str) -> dict[str, float]:
    lengths = [count_words(s) for s in SENTENCE_END.split(text.strip()) if count_words(s)]
    if not lengths:
        return {"long_sentence_share": 0.0, "sentence_mean": 0.0, "sentence_sd": 0.0}
    long_count = sum(1 for n in lengths if n > LONG_SENTENCE_WORDS)
    return {
        "long_sentence_share": round(long_count / len(lengths), 4),
        "sentence_mean": round(statistics.fmean(lengths), 3),
        "sentence_sd": round(statistics.pstdev(lengths), 3),
    }


def longest_shared_run(text: str, sample: str) -> int:
    """The longest run of consecutive words `text` shares with `sample`, case-insensitive.
    A draft that lifts a voice sample shows a long run; borrowing a word or two doesn't."""
    a = [w.lower() for w in WORD.findall(normalize(text))]
    b = [w.lower() for w in WORD.findall(normalize(sample))]
    best = 0
    previous = [0] * (len(b) + 1)
    for word in a:
        current = [0] * (len(b) + 1)
        for j, other in enumerate(b, start=1):
            if word == other:
                current[j] = previous[j - 1] + 1
                best = max(best, current[j])
        previous = current
    return best


def analyze(
    text: str, target_words: int, phrases: tuple[str, ...] | list[str] = (), samples: tuple[str, ...] | list[str] = ()
) -> dict[str, Any]:
    """Every script check for one draft. Counts are per 1000 words; see the module docstring.
    `sample_overlap` is the longest word run shared with any voice sample, in words."""
    words = count_words(text)
    _, narration = split_dialogue(text)
    narration = normalize(narration)
    tags = speech_tags(text)
    result: dict[str, Any] = {
        "words": words,
        "target_ratio": round(words / target_words, 4) if target_words else 0.0,
        "italic_spans": per_1000(count_italics(narration), words),
        "digits_below_ten": per_1000(len(DIGIT_BELOW_TEN.findall(text)), words),
        "numerals": per_1000(len(NUMERAL.findall(text)), words),
        "emdash_spaced": per_1000(len(EMDASH_SPACED.findall(text)), words),
        "emdash_closed": per_1000(len(EMDASH_CLOSED.findall(text)), words),
        "tag_adverbs": per_1000(sum(1 for _, rest in tags if has_tag_adverb(rest)), words),
        "emotion_words": per_1000(count_emotion_words(text), words),
        "contractions_narration": per_1000(len(CONTRACTION.findall(narration)), words),
        "ly_adverbs_narration": per_1000(count_ly_adverbs(narration), words),
        "phrase_hits": per_1000(count_phrases(text, phrases), words),
        "said_share": round(sum(1 for v, _ in tags if v == "said") / len(tags), 4) if tags else None,
        "has_markdown": bool(MARKDOWN_LINE.search(text)),
        "starts_with_preamble": bool(PREAMBLE.match(normalize(text).lstrip())),
        "sample_overlap": max((longest_shared_run(text, s) for s in samples), default=0),
    }
    result.update(sentence_stats(text))
    return result


def iter_drafts(run_dir: Path) -> Iterator[dict[str, Any]]:
    """Each draft in a run dir: its address, `meta` and draft `text` (the I/O layer)."""
    for draft in sorted(run_dir.glob("*/*/*/*/draft_*.md")):
        n = int(draft.stem.split("_")[1])
        brief_dir = draft.parent
        case, model, prompt, brief = draft.relative_to(run_dir).parts[:4]
        meta_path = brief_dir / f"meta_{n}.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
        yield {
            "case": case, "model": model, "prompt": prompt, "brief": brief, "n": n,
            "meta": meta, "text": draft.read_text(encoding="utf-8"),
        }


def load_phrases(path: Path) -> list[str]:
    import yaml

    if not path.is_file():
        return []
    return list((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("common") or [])


def load_samples(book_yaml: Path) -> list[str]:
    """Each character's voice sample from the book: the text after its `## Sample` heading."""
    import yaml

    book = yaml.safe_load(book_yaml.read_text(encoding="utf-8")) or {}
    samples = []
    for character in book.get("characters") or []:
        _, found, sample = (character.get("body") or "").partition("## Sample")
        if found and sample.strip():
            samples.append(sample.strip())
    return samples


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: checks.py RUN_DIR   (prints each ok draft's script checks as JSON lines)")
    phrases = load_phrases(Path(__file__).resolve().parent / "phrases.yaml")
    samples = load_samples(Path(__file__).resolve().parent / "fixture" / "book.yaml")
    for item in iter_drafts(Path(sys.argv[1])):
        if item["meta"].get("status", "ok") != "ok":
            continue
        metrics = analyze(item["text"], TARGET_WORDS.get(item["prompt"], 0), phrases, samples)
        address = {k: item[k] for k in ("case", "model", "prompt", "brief", "n")}
        print(json.dumps({**address, **metrics}))


if __name__ == "__main__":
    main()
