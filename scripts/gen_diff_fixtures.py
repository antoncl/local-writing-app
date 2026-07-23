"""Generate the snapshot-diff regression fixtures (#409, from spike #396).

The eighteen cases are the regression surface for ADR-0044 Amendment 1: each one
is a rendering the diff must **not** produce. They are generated, never
hand-authored — regenerate rather than editing the JSON, or the fixtures stop
describing what the code does and start describing what someone hoped it did.

The runs come from the **production** module, not a copy of it. That is the whole
point of this script existing after the spike: `frontend/src/lib/utils/diffRuns.test.ts`
renders these through the app's real `sceneMarkdownToHtml` and asserts
well-formedness and no leaked syntax, so a scanner that drifts from the renderer
turns into a red build rather than a wrong colour in a browser.

Run:  python scripts/gen_diff_fixtures.py
Out:  frontend/src/lib/utils/diffRuns.fixtures.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "backend" / "tests"))

from app.services.project.snapshot_diff import diff_runs  # noqa: E402
from diff_fuzz import fuzz_cases  # noqa: E402

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
]


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


def main() -> None:
    target_dir = REPO / "frontend" / "src" / "lib" / "utils"
    for name, cases in (("diffRuns.fixtures.json", CASES), ("diffRuns.fuzz.json", fuzz_cases())):
        target = target_dir / name
        payload = json.dumps(_with_runs(cases), indent=2, ensure_ascii=False) + chr(10)
        target.write_text(payload, encoding="utf-8")
        print(f"wrote {len(cases)} cases to {target}")


if __name__ == "__main__":
    main()
