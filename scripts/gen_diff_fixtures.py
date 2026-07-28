"""Generate the snapshot-diff regression fixtures (#409, from spike #396).

The cases below are the regression surface for ADR-0044 Amendment 1 and the
client-side parity gate (#573): each one is a rendering the diff must **not**
produce, and a scanner/stacking branch the ported `diffRuns` must agree with. They are generated, never
hand-authored — regenerate rather than editing the JSON, or the fixtures stop
describing what the code does and start describing what someone hoped it did.

The runs come from the **production** module, not a copy of it. That is the whole
point of this script existing after the spike: `frontend/src/lib/utils/diffRuns.test.ts`
renders these through the app's real `sceneMarkdownToHtml` and asserts
well-formedness and no leaked syntax, so a scanner that drifts from the renderer
turns into a red build rather than a wrong colour in a browser.

Run:    python scripts/gen_diff_fixtures.py
Out:    frontend/src/lib/utils/diffRuns.fixtures.json
Check:  python scripts/gen_diff_fixtures.py --check

**`--check` is what makes the committed fixtures a gate rather than a souvenir**
(#435). Without it the file billed as the regression surface is a frozen output
of the code it grades: under a mutation to the diff the committed JSON stays
stale and the frontend suite stays green, so a backend change to `diff_runs`
cannot turn the frontend red until a person remembers to run this. CI runs
`--check`, which regenerates in memory and fails on any difference — the same
shape as a formatter check. A deliberate change to the diff then shows up as a
reviewable change to this file instead of as silent drift.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "backend" / "tests"))

from app.services.project.snapshot_diff import _field_diffs, diff_runs  # noqa: E402

MUTATE = "<!-- mutate:entity=char-maren;field=mood;value=stricken;id=m1 -->"
TODO_OPEN = "<!-- embedded-todo:id=t1;status=open;note=check%20the%20tide -->"
TODO_CLOSE = "<!-- /embedded-todo -->"

# Each case is a deliberate probe at one of the risks §G names.  The prose is
# real scene prose (the mockup's, extended), not lorem, because the failure is
# about markup meeting a word boundary and that needs real sentences around it.
CASES: list[dict[str, str]] = [
    {
        "name": "edit-inside-emphasis",
        "why": "the canonical case from the issue: **a bold phrase** -> **a bolder phrase**",
        "was": "The tide went out further than **she had ever seen it**, and kept going.",
        "now": "The tide went out further than **she had ever once seen it**, and kept going.",
    },
    {
        "name": "edit-straddles-emphasis-start",
        "why": "the edit consumes the opening delimiter and the word before it",
        "was": "She counted the hulls twice and was **very tired** by the end of it.",
        "now": "She counted the hulls twice and was quite **tired** by the end of it.",
    },
    {
        "name": "edit-straddles-emphasis-end",
        "why": "the edit consumes the closing delimiter and the word after it",
        "was": "She counted the hulls twice and was **very tired** by the end of it.",
        "now": "She counted the hulls twice and was **very** tired indeed by the end of it.",
    },
    {
        "name": "edit-inside-italic-inside-bold",
        "why": "nested inline markup — the boundary lands between two delimiter runs",
        "was": "The gulls had stopped, and **that was the *part* she remembered** afterwards.",
        "now": "The gulls had stopped, and **that was the *only part* she remembered** afterwards.",
    },
    {
        "name": "edit-inside-link-text",
        "why": "the run boundary falls inside [ ... ]",
        "was": "The eleventh was moored at [the harbour](lore://loc-corrant) all week.",
        "now": "The eleventh was moored at [the old harbour](lore://loc-corrant) all week.",
    },
    {
        "name": "edit-inside-link-target",
        "why": "the run boundary falls inside ( ... ) — the target is not prose",
        "was": "The eleventh was moored at [the harbour](lore://loc-corrant) all week.",
        "now": "The eleventh was moored at [the harbour](lore://loc-westquay) all week.",
    },
    {
        "name": "edit-adjacent-to-mutation-marker",
        "why": "the marker is an HTML comment in the body and must survive untouched",
        "was": f"Maren did not run. {MUTATE} She had never done the sensible thing quickly.",
        "now": f"Maren did not run. {MUTATE} She had never once done the sensible thing quickly.",
    },
    {
        "name": "edit-inside-mutation-marker",
        "why": "the author changed the marker's value — the diff cuts the comment itself",
        "was": f"Maren did not run. {MUTATE} She stood where she was.",
        "now": (
            "Maren did not run. "
            "<!-- mutate:entity=char-maren;field=mood;value=numb;id=m1 --> "
            "She stood where she was."
        ),
    },
    {
        "name": "edit-inside-embedded-todo",
        "why": "a todo anchor wraps prose across two comments; the edit lands between them",
        "was": f"The boats lay {TODO_OPEN}over on their sides{TODO_CLOSE} like something sleeping.",
        "now": f"The boats lay {TODO_OPEN}over on their black sides{TODO_CLOSE} like something sleeping.",
    },
    {
        "name": "paragraph-split",
        "why": "a block boundary appears where there was none",
        "was": "She counted the hulls twice. The eleventh was the Corrant. Her father was aboard.",
        "now": "She counted the hulls twice.\n\nThe eleventh was the Corrant. Her father was aboard.",
    },
    {
        "name": "paragraph-join",
        "why": "a block boundary disappears",
        "was": "She counted the hulls twice.\n\nThe eleventh was the Corrant, and her father was aboard.",
        "now": "She counted the hulls twice. The eleventh was the Corrant, and her father was aboard.",
    },
    {
        "name": "edit-inside-table-cell",
        "why": "the run boundary falls inside a table row, whose pipes are structural",
        "was": (
            "| boat | state |\n| --- | --- |\n| Corrant | at sea |\n| Maren's Luck | beached |\n"
        ),
        "now": (
            "| boat | state |\n| --- | --- |\n| Corrant | lost at sea |\n| Maren's Luck | beached |\n"
        ),
    },
    {
        "name": "edit-spanning-a-list-item-boundary",
        "why": "list markers are line-leading structure a word diff cannot see",
        "was": "- run for the high road\n- do not stop for anything you can carry\n",
        "now": "- run for the high road at once\n- do not stop for anything that can walk\n",
    },
    {
        "name": "emphasis-added-around-existing-words",
        "why": "a construct exists on one side only — the snap has nothing to snap to in the other",
        "was": "She counted the hulls twice and was very tired by the end of it.",
        "now": "She counted the hulls twice and was **very tired** by the end of it.",
    },
    {
        "name": "emphasis-removed-from-existing-words",
        "why": "the same asymmetry the other way round",
        "was": "She counted the hulls twice and was **very tired** by the end of it.",
        "now": "She counted the hulls twice and was very tired by the end of it.",
    },
    {
        "name": "edit-inside-a-heading",
        "why": "a block whose leading markup is line-structural, not inline",
        "was": "## The Harbour\n\nThe tide went out further than she had ever seen it.\n",
        "now": "## The Empty Harbour\n\nThe tide went out further than she had ever seen it.\n",
    },
    {
        "name": "edit-inside-a-blockquote",
        "why": "every line of the block carries a marker the word diff cannot see",
        "was": "> When the water leaves like that, it is not leaving.\n> It is drawing breath.\n",
        "now": "> When the water leaves like that, it is not leaving at all.\n> It is drawing breath.\n",
    },
    {
        "name": "split-shifts-every-later-block",
        "why": (
            "a split early in the scene shifts every later block by one, so difflib pairs "
            "unrelated paragraphs one-to-one; word-diffing those interleaves them into mush "
            "that still reassembles and still renders well-formed (#409)"
        ),
        "was": (
            "The tide went out further than she had ever seen it.\n\n"
            "She counted the hulls twice. The eleventh was moored at the harbour.\n\n"
            "Maren did not run. She had never done the sensible thing quickly.\n"
        ),
        "now": (
            "The tide went out further than she had ever seen it.\n\n"
            "She counted the hulls twice.\n\n"
            "The eleventh was moored at the harbour.\n\n"
            "Maren did not run. She had never done the sensible thing quickly.\n"
        ),
    },
    {
        "name": "clean-prose-control",
        "why": "the case the mockup already proves — must stay clean, or the harness is wrong",
        "was": "Somewhere behind her a shutter began to bang. Nobody came to close it.",
        "now": "Somewhere behind her, up in the town, a shutter began to bang. Nobody closed it.",
    },
    # --- scanner / stacking branches, added for the #573 client-parity gate ---
    {
        "name": "edit-inside-a-fenced-code-block",
        "why": "code is the one place a wrapper cannot go — is_code_block is true, so the block stacks whole",
        "was": "```\nlet tide = 1;\nreturn tide;\n```",
        "now": "```\nlet tide = 2;\nreturn tide;\n```",
    },
    {
        "name": "edit-beside-an-autolink",
        "why": "an autolink <...> is a protected span the word diff must not enter",
        "was": "She noted <https://harbour.example/log> and read it twice.",
        "now": "She noted <https://harbour.example/log> and read it once.",
    },
    {
        "name": "edit-in-a-block-with-an-unterminated-code-span",
        "why": "an unclosed backtick cannot be bounded — the scanner returns None and the block stacks",
        "was": "The reading was `off and nobody could say why.",
        "now": "The reading was `wrong and nobody could say why.",
    },
    {
        "name": "edit-in-a-block-with-unpaired-emphasis",
        "why": "an unpaired * cannot be safely bounded — pair_delimiters returns None and the block stacks",
        "was": "She was *very tired and cross by the end of it.",
        "now": "She was *very weary and cross by the end of it.",
    },
]


# The field flip (ADR-0044 §F, #583). Each case probes one rule of
# `_field_diffs` / `same_rendered_value`: the atomic scalar/list flip, the
# status row, the blank-equivalence (a missing key and an empty value read the
# same and must not flip), order-sensitivity of a list, and the non-field keys
# that are never flipped. The client `fieldDiffs` must reproduce these exactly.
FIELD_CASES: list[dict[str, object]] = [
    {
        "name": "scalar-field-changed",
        "why": "the ordinary case: one text field's value flips",
        "was_status": "draft",
        "was_metadata": {"rank": "Lieutenant"},
        "now_status": "draft",
        "now_metadata": {"rank": "Captain"},
    },
    {
        "name": "status-flipped",
        "why": "status rides beside the metadata and flips like any other row",
        "was_status": "draft",
        "was_metadata": {},
        "now_status": "revised",
        "now_metadata": {},
    },
    {
        "name": "field-added",
        "why": "a field absent on the snapshot side, present now",
        "was_status": "draft",
        "was_metadata": {},
        "now_status": "draft",
        "now_metadata": {"goal": "Reach the harbour"},
    },
    {
        "name": "blank-key-vs-missing-key-do-not-flip",
        "why": "an empty string and an absent key are the same absence — no row",
        "was_status": "draft",
        "was_metadata": {"note": ""},
        "now_status": "draft",
        "now_metadata": {},
    },
    {
        "name": "empty-list-vs-missing-do-not-flip",
        "why": "[] and an absent key both read (none) — no row",
        "was_status": "draft",
        "was_metadata": {"tags": []},
        "now_status": "draft",
        "now_metadata": {},
    },
    {
        "name": "blank-to-value-flips",
        "why": "an empty value becoming a real one is a genuine change",
        "was_status": "draft",
        "was_metadata": {"note": ""},
        "now_status": "draft",
        "now_metadata": {"note": "check the tide tables"},
    },
    {
        "name": "list-membership-changed",
        "why": "a multi-valued field: one item swapped",
        "was_status": "draft",
        "was_metadata": {"tags": ["storm", "night"]},
        "now_status": "draft",
        "now_metadata": {"tags": ["storm", "dawn"]},
    },
    {
        "name": "list-reordered-flips",
        "why": "Python == on lists is order-sensitive, so a reorder is a change",
        "was_status": "draft",
        "was_metadata": {"tags": ["storm", "night"]},
        "now_status": "draft",
        "now_metadata": {"tags": ["night", "storm"]},
    },
    {
        "name": "non-field-keys-never-flip",
        "why": "id/title/schema_version differ but are bookkeeping, not authored fields",
        "was_status": "draft",
        "was_metadata": {"id": "a", "title": "Old", "schema_version": 1, "goal": "hold"},
        "now_status": "draft",
        "now_metadata": {"id": "b", "title": "New", "schema_version": 2, "goal": "hold"},
    },
    {
        "name": "number-field-changed",
        "why": "a number field flips by ordinary inequality, not blank-equivalence",
        "was_status": "draft",
        "was_metadata": {"count": 3},
        "now_status": "draft",
        "now_metadata": {"count": 5},
    },
    {
        "name": "boolean-field-flipped",
        "why": "a boolean field flips false -> true",
        "was_status": "draft",
        "was_metadata": {"done": False},
        "now_status": "draft",
        "now_metadata": {"done": True},
    },
    {
        "name": "zero-is-a-value-not-a-blank",
        "why": "0 is a value, so 0 vs an absent key flips (falsy-zero trap)",
        "was_status": "draft",
        "was_metadata": {"count": 0},
        "now_status": "draft",
        "now_metadata": {},
    },
    {
        "name": "false-is-a-value-not-a-blank",
        "why": "False is a value, so False vs an absent key flips",
        "was_status": "draft",
        "was_metadata": {"done": False},
        "now_status": "draft",
        "now_metadata": {},
    },
    {
        "name": "nothing-changed",
        "why": "identical sides produce an empty flip",
        "was_status": "draft",
        "was_metadata": {"rank": "Captain", "tags": ["storm"]},
        "now_status": "draft",
        "now_metadata": {"rank": "Captain", "tags": ["storm"]},
    },
]


def _with_field_diffs(cases: list[dict[str, object]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for case in cases:
        fields = {
            key: diff.model_dump()
            for key, diff in _field_diffs(
                case["was_metadata"],  # type: ignore[arg-type]
                case["was_status"],  # type: ignore[arg-type]
                case["now_metadata"],  # type: ignore[arg-type]
                case["now_status"],  # type: ignore[arg-type]
            ).items()
        }
        out.append({**case, "fields": fields})
    return out


def _with_runs(cases: list[dict[str, str]]) -> list[dict[str, object]]:
    out = [
        {**case, "runs": [run.model_dump() for run in diff_runs(case["was"], case["now"])]}
        for case in cases
    ]
    # Runs that do not reassemble to their source are a bug in the generator,
    # not a finding — catch it here rather than letting it read as damage.
    for case in out:
        for side, kinds in (("was", {"equal", "was"}), ("now", {"equal", "now"})):
            joined = "".join(run["text"] for run in case["runs"] if run["kind"] in kinds)
            assert joined == case[side], f"{case['name']}/{side} does not reassemble"
    return out


TARGET_DIR = REPO / "frontend" / "src" / "lib" / "utils"

# The committed regression surface, and the only file `--check` gates. The fuzz
# corpus beside it is gitignored — a sweep, not a surface — so there is nothing
# for it to drift from, and generating four hundred cases to compare against
# nothing would just be wall clock.
FIXTURES = TARGET_DIR / "diffRuns.fixtures.json"
FIELD_FIXTURES = TARGET_DIR / "fieldDiffs.fixtures.json"
FUZZ = TARGET_DIR / "diffRuns.fuzz.json"


def _dump(rows: list[dict[str, object]]) -> str:
    return json.dumps(rows, indent=2, ensure_ascii=False) + chr(10)


def _payload(cases: list[dict[str, str]]) -> str:
    return _dump(_with_runs(cases))


def _field_payload(cases: list[dict[str, object]]) -> str:
    return _dump(_with_field_diffs(cases))


def _write(target: Path, payload: str, count: int) -> None:
    # `newline=""` because `.gitattributes` pins this repo to LF, and the default
    # translation writes CRLF on Windows — so a run on the dev machine would put
    # a file in the working tree that does not match what is checked out.
    # (`--check` would not catch it: `read_text` translates newlines back on the
    # way in, so it compares blind to them. This is the write side's job.)
    target.write_text(payload, encoding="utf-8", newline="")
    print(f"wrote {count} cases to {target}")


def _check_one(target: Path, expected: str, produces: str) -> bool:
    actual = target.read_text(encoding="utf-8") if target.exists() else ""
    if actual == expected:
        return True
    print(
        f"{target} is stale: it no longer matches what {produces} produces.\n"
        "Run `python scripts/gen_diff_fixtures.py` and commit the result. If the "
        "change is deliberate, the diff is the thing to review.",
        file=sys.stderr,
    )
    return False


def _check() -> int:
    runs_ok = _check_one(FIXTURES, _payload(CASES), "diff_runs")
    fields_ok = _check_one(FIELD_FIXTURES, _field_payload(FIELD_CASES), "_field_diffs")
    if runs_ok and fields_ok:
        print(f"fixtures up to date ({len(CASES)} run cases, {len(FIELD_CASES)} field cases)")
        return 0
    return 1


USAGE = "usage: gen_diff_fixtures.py [--check]"


def main(argv: list[str]) -> int:
    """No argument writes; `--check` compares; **anything else is an error.**

    Not `if "--check" in argv`, which was the first form and is the shape of a
    gate that reports green while doing nothing: a misspelled or renamed flag in
    `gates.yml` fell through to write mode, regenerated the fixtures inside the
    runner's own checkout, and exited 0. Every build would have stayed green
    with the gate dead — the exact silent drift #435 exists to close, moved up a
    level. A gate has to fail when it cannot do its job.
    """
    if argv == ["--check"]:
        return _check()
    if argv:
        print(f"{USAGE}\nunrecognised arguments: {' '.join(argv)}", file=sys.stderr)
        return 2
    _write(FIXTURES, _payload(CASES), len(CASES))
    _write(FIELD_FIXTURES, _field_payload(FIELD_CASES), len(FIELD_CASES))
    # Imported here rather than at module scope: `--check` never generates the
    # fuzz corpus, and a gate should not depend on a test module it does not use.
    from diff_fuzz import fuzz_cases

    fuzz = fuzz_cases()
    _write(FUZZ, _payload(fuzz), len(fuzz))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
