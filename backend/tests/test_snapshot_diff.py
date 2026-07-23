"""The snapshot diff: the scan, the three rules, and the route (#409, ADR-0044).



The render half lives in `frontend/src/lib/utils/diffRuns.test.ts`, which puts

these runs through the app's real `sceneMarkdownToHtml`. That split is

deliberate: only the renderer can say whether a run survives rendering, and only

Python can say whether the diff is the diff. Neither half is sufficient alone.

"""



from __future__ import annotations

import re
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from diff_fuzz import fuzz_cases
from fastapi.testclient import TestClient

from app.main import app
from app.models import SaveSceneRequest
from app.runtime import service as svc
from app.services.markdown_scan import (
    escapes_container,
    is_structured,
    protected_intervals,
)
from app.services.project.snapshot_diff import (
    MAX_WORD_DIFF_TOKENS,
    _is_a_rewrite_of,
    _same_value,
    diff_runs,
)

# Any blank line, CRLF included — what rule 1 actually forbids inside an

# inline run.

BLANK_LINE = re.compile(r"\r?\n[ \t]*\r?\n")



MUTATE = "<!-- mutate:entity=char-maren;field=mood;value=stricken;id=m1 -->"





def covers(text: str, fragment: str) -> bool:

    """Whether some protected interval encloses `fragment` whole."""

    at = text.index(fragment)

    intervals = protected_intervals(text)

    assert intervals is not None, f"unscannable: {text!r}"

    return any(start <= at and at + len(fragment) <= end for start, end in intervals)





# ----- the scan -------------------------------------------------------------





@pytest.mark.parametrize(

    ("text", "fragment"),

    [

        ("she was **very tired** by the end.", "**very tired**"),

        ("she was *tired* by the end.", "*tired*"),

        ("she was ~~tired~~ by the end.", "~~tired~~"),

        ("moored at [the harbour](lore://loc-corrant) all week.", "[the harbour](lore://loc-corrant)"),

        ("and **that was the *part* she knew** after.", "**that was the *part* she knew**"),

        (f"Maren did not run. {MUTATE} She stood.", MUTATE),

    ],

)

def test_a_construct_is_protected_whole(text: str, fragment: str) -> None:

    """A boundary inside any of these is what damaged 8 of the spike's 18."""

    assert covers(text, fragment)





def test_a_link_target_is_protected_with_its_text() -> None:

    """The target is not prose. A boundary inside it leaks `](lore://…)` to the

    reader as literal text — one of the spike's four failure classes."""

    text = "moored at [the harbour](lore://loc-corrant) all week."

    assert covers(text, "(lore://loc-corrant)")





def test_a_code_span_hides_its_asterisks() -> None:

    """Where a list of independent regexes goes wrong: the `**` inside a code

    span is literal, and treating it as a delimiter mispairs everything after."""

    text = "she typed `a ** b` and then **really meant it** aloud."

    assert covers(text, "`a ** b`")

    assert covers(text, "**really meant it**")





def test_an_escaped_delimiter_is_not_emphasis() -> None:

    text = r"a \*not emphasis\* and then **real** after."

    assert covers(text, "**real**")





def test_nested_parentheses_in_a_link_target() -> None:

    text = "see [the note](lore://loc-a(b)c) for more."

    assert covers(text, "[the note](lore://loc-a(b)c)")





@pytest.mark.parametrize(

    "text",

    [

        "an **unbalanced emphasis that never closes\n",

        "an unterminated `code span\n",

        "an unterminated <!-- comment\n",

    ],

)

def test_markup_we_cannot_account_for_refuses_to_guess(text: str) -> None:

    """`None` means "stack this block" — the safe degrade. Guessing where an

    unterminated construct ends is how a scanner under-protects, and

    under-protection is the failure the author actually sees."""

    assert protected_intervals(text) is None





def test_structure_detection_and_container_escape() -> None:

    quote = "> the water was cold\n> and it kept going"

    assert is_structured(quote)

    assert not is_structured("just a plain paragraph of prose")

    # A run spanning the newline would cross into the next quoted line.

    assert escapes_container(quote, 2, len(quote) - 2)

    assert not escapes_container(quote, 2, 10)





# ----- the three rules ------------------------------------------------------





def reassembles(runs: list, was: str, now: str) -> bool:

    return (

        "".join(r.text for r in runs if r.kind != "now") == was

        and "".join(r.text for r in runs if r.kind != "was") == now

    )





def test_runs_reassemble_to_both_documents() -> None:

    """The invariant the whole feature rests on: no words are lost."""

    was = "She counted the hulls twice and was **very tired** by the end of it."

    now = "She counted the hulls twice and was quite **tired** by the end of it."

    assert reassembles(diff_runs(was, now), was, now)





def test_a_construct_on_one_side_only_still_reassembles() -> None:

    """The common edit — bolding a phrase already written — and the case that

    broke the spike's algorithm: the two boundaries snap by different amounts,

    so the shared text between regions stops being the same string on each side.

    Found by the generated corpus, not by the eighteen fixtures."""

    was = "She counted the hulls twice and was very tired by the end of it."

    now = "She counted the hulls twice and was **very tired** by the end of it."

    assert reassembles(diff_runs(was, now), was, now)

    assert reassembles(diff_runs(now, was), now, was)





def test_rule_1_no_inline_changed_run_contains_a_blank_line() -> None:

    """An `equal` run may span whole blocks — it is the unchanged remainder, and

    is emitted as source rather than wrapped. The rule bites on CHANGED runs:

    one of those containing a blank line would put an inline wrapper around

    `</p><p>`."""

    was = "First block here.\n\nSecond block here."

    now = "First block, edited.\n\nSecond block, also edited."

    for run in diff_runs(was, now):

        if run.kind != "equal" and not run.stacked:

            assert "\n\n" not in run.text





def test_rule_3_a_block_boundary_change_stacks() -> None:

    """§F: a change spanning block boundaries stacks — regardless of how many

    words either side contains, which is why it is structural and not a

    threshold."""

    was = "She counted the hulls twice. The eleventh was the Corrant."

    now = "She counted the hulls twice.\n\nThe eleventh was the Corrant."

    runs = diff_runs(was, now)

    assert any(run.stacked for run in runs)

    assert reassembles(runs, was, now)





def test_a_change_within_one_block_stays_inline_however_long() -> None:

    """The other half of the same rule: length never decides the layout."""

    was = "The tide went out. " + "It kept going and going and going. " * 12

    now = "The tide rushed out. " + "It kept going and going and going. " * 12

    runs = diff_runs(was, now)

    assert not any(run.stacked for run in runs)





def test_a_change_escaping_a_table_cell_stacks() -> None:

    """A wrapper spanning `|` is torn apart by the table parser —

    `<td><span class="r-was">stone</td>` with a span that never closes. Found by

    the generated corpus."""

    # The change has to actually SPAN the `|` — here the author merges two cells

    # into one. Two separate edits, one per cell, stay inline and should: each

    # wrapper is confined to its own `<td>`, and stacking those would be a

    # needless loss of precision.

    was = "| boat | state |\n| --- | --- |\n| Corrant | at sea |\n"

    now = "| boat | state |\n| --- | --- |\n| Corrant lost at sea |\n"

    runs = diff_runs(was, now)

    assert any(run.stacked for run in runs)

    assert reassembles(runs, was, now)





def test_changes_confined_to_table_cells_stay_inline() -> None:

    """The other side of the same rule — two edits, each inside its own cell,

    are two wrappers neither of which crosses a `|`."""

    was = "| boat | state |\n| --- | --- |\n| Corrant | at sea |\n"

    now = "| boat | state |\n| --- | --- |\n| Rowan | in port |\n"

    runs = diff_runs(was, now)

    assert not any(run.stacked for run in runs)

    assert reassembles(runs, was, now)





def test_a_change_reaching_the_start_of_a_structured_block_stacks() -> None:

    """There is no position before a `> ` marker to snap back to, so an inline

    wrapper would open ahead of it and the blockquote stops being one."""

    was = "> the water was cold here,\n> and it kept going.\n"

    now = "> the sea was cold here,\n> and it kept going.\n"

    runs = diff_runs(was, now)

    assert reassembles(runs, was, now)





def test_an_unchanged_body_produces_one_equal_run() -> None:

    body = "Nothing changed here at all."

    assert [(r.kind, r.text) for r in diff_runs(body, body)] == [("equal", body)]





# ----- the sweep ------------------------------------------------------------





def test_generated_documents_hold_every_invariant() -> None:

    """A few hundred generated scene bodies, every build, no artifact in the tree.



    This checks what Python can check alone. Whether a run survives *rendering*

    is a question only the renderer can answer, and the eighteen fixtures ask it

    — see `frontend/src/lib/utils/diffRuns.test.ts`. The two halves are not

    redundant: this one is broad and shallow, that one is narrow and real.



    Raise the count for a deeper sweep:

    `FUZZ_CASES=5000 python scripts/gen_diff_fixtures.py` writes a corpus the

    frontend test picks up, which is how the table-cell escape was found.

    """

    for case in fuzz_cases():

        was, now = case["was"], case["now"]

        runs = diff_runs(was, now)

        name = case["name"]



        # No words lost, on either side. Everything else is presentation.

        assert reassembles(runs, was, now), name



        # A run's offset is a running total, one cursor per side — NOT

        # `source.index(run.text)`, which finds the first occurrence anywhere in

        # the document. With prose that repeats its vocabulary that is almost

        # never where the run actually is, so the container check would be

        # asserting about the wrong region and passing for the wrong reason.

        was_at = 0

        now_at = 0

        for run in runs:

            source, start = (was, was_at) if run.kind != "now" else (now, now_at)

            if run.kind != "now":

                was_at += len(run.text)

            if run.kind != "was":

                now_at += len(run.text)

            if run.kind == "equal" or run.stacked:

                continue

            # Rule 1: an inline run wrapping a blank line would wrap `</p><p>`.

            assert "\n\n" not in run.text, name

            # A changed inline run must sit inside one structural container, or

            # the parser tears its wrapper apart.

            assert source[start : start + len(run.text)] == run.text, f"{name}: bad offset"

            assert not escapes_container(source, start, start + len(run.text)), name





@pytest.mark.parametrize(
    ("was", "now", "same"),
    [
        # An absent key and an empty one are the same absence to a reader.
        (None, "", True),
        (None, [], True),
        ("", None, True),
        # ...but zero and false are VALUES. Leaning on truthiness here would
        # hide a real change behind a plausible-looking rule.
        (0, None, False),
        (False, "", False),
        (0, 0, True),
        (False, False, True),
        ("Maren", "Maren", True),
        ("Maren", "Corrant", False),
        ([], ["char-a"], False),
    ],
)
def test_blank_and_absent_read_as_the_same_value(was: object, now: object, same: bool) -> None:
    """The rail renders a missing field and an empty one identically, so a flip
    between them shows two identical-looking values with nothing to reconcile."""
    assert _same_value(was, now) is same


# ----- the route ------------------------------------------------------------





class DiffRouteTests(unittest.TestCase):

    """Same shape as `test_scene_snapshots.SnapshotTestCase` — a real project on

    disk, driven through the HTTP surface, because the route's job is reaching

    the store and the store is the filesystem."""



    def setUp(self) -> None:

        self.temp_dir = TemporaryDirectory()

        # `.resolve()` because Windows hands back the 8.3 short form and the

        # layer walk canonicalises (#356).

        self.root = Path(self.temp_dir.name).resolve() / "book"

        svc.__init__()

        svc.create_project(self.root, "Diff Tests")

        self.client = TestClient(app)

        self.scene_id = self.client.post("/api/scenes", json={"title": "The Tide"}).json()["id"]



    def tearDown(self) -> None:

        self.temp_dir.cleanup()



    def _save(self, body: str, metadata: dict | None = None) -> None:

        svc.save_scene(

            self.scene_id,

            SaveSceneRequest(

                title="The Tide",

                body=body,

                status="draft",

                entry_type="scene:scene",

                metadata=metadata or {},

            ),

        )



    def _capture(self) -> str:

        return self.client.post(f"/api/scenes/{self.scene_id}/snapshots").json()["id"]



    def _diff(self, **live) -> dict:

        snapshot_id = live.pop("snapshot_id")

        response = self.client.post(

            f"/api/scenes/{self.scene_id}/snapshots/{snapshot_id}/diff", json=live

        )

        self.assertEqual(response.status_code, 200, response.text)

        return response.json()



    def test_runs_and_fields_come_back_in_one_call(self) -> None:

        self._save("The tide went out further than she had ever seen it.", {"summary": "Low water."})

        snapshot_id = self._capture()

        # The LIVE state travels in the request rather than being read from

        # disk: autosave lags the buffer by up to six seconds, and parking on a

        # notch is a reading gesture that must not write.

        payload = self._diff(

            snapshot_id=snapshot_id,

            body="The tide went out much further than she had ever seen it.",

            title="The Tide",

            metadata={"summary": "Lower still."},

        )

        self.assertEqual(payload["snapshot"]["id"], snapshot_id)

        self.assertEqual(

            "".join(run["text"] for run in payload["runs"] if run["kind"] != "was"),

            "The tide went out much further than she had ever seen it.",

        )

        # The `was` side must reassemble to the snapshot's STORED body, not to

        # the string that was saved: the writer normalises a trailing newline,

        # and the diff's job is to be faithful to the file rather than to the

        # author's keystrokes.

        stored = self.client.get(

            f"/api/scenes/{self.scene_id}/snapshots/{snapshot_id}"

        ).json()["body"]

        self.assertEqual(

            "".join(run["text"] for run in payload["runs"] if run["kind"] != "now"), stored

        )

        self.assertEqual(payload["fields"]["summary"], {"was": "Low water.", "now": "Lower still."})



    def test_only_fields_that_differ_are_reported(self) -> None:

        self._save("Body.", {"summary": "Low water."})

        snapshot_id = self._capture()

        payload = self._diff(

            snapshot_id=snapshot_id,

            body="Body.",

            title="The Tide",

            # `status` is stored top-level in front matter rather than in the

            # field map, and the rail renders it as a field row like any other —

            # so it flips like any other.

            status="revised",

            metadata={"summary": "Low water."},

        )

        self.assertEqual(set(payload["fields"]), {"status"})

        self.assertEqual(payload["fields"]["status"], {"was": "draft", "now": "revised"})



    def test_identity_keys_are_never_reported_as_field_changes(self) -> None:

        """`id` is identity and `schema_version` is bookkeeping — neither is a

        value the author flips between."""

        self._save("Body.", {"summary": "Low water."})

        snapshot_id = self._capture()

        payload = self._diff(

            snapshot_id=snapshot_id,

            body="Body.",

            title="A Different Title",

            status="draft",

            metadata={"summary": "Low water.", "id": "something-else", "schema_version": 999},

        )

        self.assertEqual(payload["fields"], {})

        # The title still travels, because the flip covers it — it just is not a

        # metadata field.

        self.assertEqual(payload["title_now"], "A Different Title")



    def test_an_omitted_status_is_not_reported_as_a_cleared_one(self) -> None:

        """Silence is not a claim. A caller that does not send `status` is not

        saying the author cleared it — and the compare view would have shown

        that as a real change, tinted, beside the genuine ones."""

        self._save("Body.", {"summary": "Low water."})

        snapshot_id = self._capture()

        payload = self._diff(

            snapshot_id=snapshot_id, body="Body.", title="The Tide", metadata={"summary": "Low water."}

        )

        self.assertEqual(payload["fields"], {})



    def test_a_genuinely_cleared_status_is_still_reported(self) -> None:

        """The other half: `""` is a value, and stays distinguishable from

        absence."""

        self._save("Body.", {"summary": "Low water."})

        snapshot_id = self._capture()

        payload = self._diff(

            snapshot_id=snapshot_id,

            body="Body.",

            title="The Tide",

            status="",

            metadata={"summary": "Low water."},

        )

        self.assertEqual(payload["fields"]["status"], {"was": "draft", "now": ""})



    def test_the_title_travels_on_both_sides_for_the_flip(self) -> None:

        """The title flips like any other field, so both sides must arrive."""

        self._save("Body.", {"summary": "Low water."})

        snapshot_id = self._capture()

        payload = self._diff(

            snapshot_id=snapshot_id, body="Body.", title="The Empty Harbour", status="draft", metadata={"summary": "Low water."}

        )

        self.assertEqual(payload["title_was"], "The Tide")

        self.assertEqual(payload["title_now"], "The Empty Harbour")




    def _drop_front_matter_key(self, key: str) -> None:
        """Remove a top-level front-matter key from the scene file.

        Older and hand-edited scenes simply do not carry every key, and the
        file format is the contract — so the interesting comparisons are the
        ones where a key is absent on one side.
        """
        path = svc._path_for_node_id(self.scene_id, "scene")
        kept = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.startswith(f"{key}:")
        ]
        path.write_text("\n".join(kept), encoding="utf-8")

    def test_a_scene_that_never_set_a_status_reports_no_status_change(self) -> None:
        """The live side comes through `read_scene`, which defaults an absent
        status to "draft". Reading the snapshot's front matter raw gave "" for
        the same file, so a scene that never set a status reported one changing
        on EVERY park — a flip the author cannot reconcile, because the two
        sides never differed."""
        self._save("Body.", {"summary": "Low water."})
        self._drop_front_matter_key("status")
        snapshot_id = self._capture()
        payload = self._diff(
            snapshot_id=snapshot_id,
            body="Body.",
            title="The Tide",
            status="draft",
            metadata={"summary": "Low water."},
        )
        self.assertEqual(payload["fields"], {})

    def test_a_scene_with_no_title_key_reports_no_title_change(self) -> None:
        """`read_scene` and `read_snapshot` both fall back to the node id; the
        diff fell back to "". The title then flipped on every park, and the
        read-only title input rendered empty in Snapshot view."""
        self._save("Body.", {})
        self._drop_front_matter_key("title")
        snapshot_id = self._capture()
        payload = self._diff(
            snapshot_id=snapshot_id,
            body="Body.",
            title=self.scene_id,
            status="draft",
            metadata={},
        )
        self.assertEqual(payload["title_was"], self.scene_id)
        self.assertEqual(payload["title_was"], payload["title_now"])

    def _inject_metadata_line(self, line: str) -> None:
        """Add a raw line under `metadata:` in the scene file.

        Deliberately behind the save path: the values that matter here are ones
        `save_scene` would reject or strip, which is exactly how they come to
        exist only inside a snapshot — the file was written when the schema, or
        the referenced node, still allowed them.
        """
        path = svc._path_for_node_id(self.scene_id, "scene")
        out = []
        for existing in path.read_text(encoding="utf-8").splitlines():
            out.append(existing)
            if existing.startswith("metadata:"):
                out.append(f"  {line}")
        path.write_text("\n".join(out), encoding="utf-8")

    def test_a_reference_to_a_deleted_node_is_not_a_field_change(self) -> None:
        """`read_scene` blanks a reference whose target is gone, so the live
        side never carries one. The snapshot is a byte copy and keeps it, so
        comparing raw produced a phantom flip on a scene nobody had touched —
        and one the author cannot resolve, because the value they see in the
        rail is not in the document."""
        self._save("Body.", {"summary": "Low water."})
        self._inject_metadata_line("pov: char-long-since-deleted")
        snapshot_id = self._capture()
        payload = self._diff(
            snapshot_id=snapshot_id,
            body="Body.",
            title="The Tide",
            status="draft",
            metadata={"summary": "Low water."},
        )
        self.assertEqual(payload["fields"], {})

    def test_a_field_the_schema_has_since_retired_is_not_a_field_change(self) -> None:
        """The other healing step, for the same reason: `read_scene` strips a
        field the schema no longer defines, so it cannot reach the live side."""
        self._save("Body.", {"summary": "Low water."})
        self._inject_metadata_line("retired_field: gone")
        snapshot_id = self._capture()
        payload = self._diff(
            snapshot_id=snapshot_id,
            body="Body.",
            title="The Tide",
            status="draft",
            metadata={"summary": "Low water."},
        )
        self.assertEqual(payload["fields"], {})

    def test_an_unknown_snapshot_is_a_404(self) -> None:

        response = self.client.post(

            f"/api/scenes/{self.scene_id}/snapshots/snap-nope/diff",

            json={"body": "", "title": "", "metadata": {}},

        )

        self.assertEqual(response.status_code, 404)



# ----- the shapes the max-effort review found ---------------------------------





def changed_inline_runs(runs: list) -> list:

    return [run for run in runs if run.kind != "equal" and not run.stacked]





@pytest.mark.parametrize(

    ("was", "now"),

    [

        ("a b", "a\r\n\r\nb"),

        ("a\r\n\r\nb", "a b"),

        ("a\n\n\nb", "a\n\nb"),

        ("a\n\nb", "a\n\n\nb"),

    ],

)

def test_a_blank_line_never_ends_up_inside_an_inline_run(was: str, now: str) -> None:

    """Rule 1, stated so it can actually fail.



    The original check looked for `\n\n` only, so it could not see a CRLF

    blank line — and this is a Windows-first app, where a CRLF scene file is

    ordinary. An inline run carrying one opens its wrapper in one paragraph and

    closes it in the next. The three-newline cases are the neighbouring bug:

    a separator that stopped at two left a stray newline heading the next chunk,

    which marked reads as a raw-HTML block and swallows the paragraph.

    """

    runs = diff_runs(was, now)

    assert reassembles(runs, was, now)

    for run in changed_inline_runs(runs):

        assert not BLANK_LINE.search(run.text), repr(run.text)





def test_two_unrelated_paragraphs_are_not_treated_as_a_rewrite() -> None:

    """`_align_blocks`'s own docstring example.



    Whitespace tokens match each other unconditionally, so scoring similarity

    over them floors `ratio()` near 0.5 for ANY two prose blocks — putting the

    threshold on the noise floor and letting two unrelated paragraphs be

    word-diffed into the interleaved mush the gate exists to prevent.

    """

    assert not _is_a_rewrite_of(

        "Maren did not run. She stood at the edge of the water and counted the boats.",

        "The eleventh was moored at the far pier, its lantern out, rope frayed to nothing.",

    )





def test_a_real_rewrite_is_still_recognised() -> None:

    """The other half — the gate must not simply refuse everything."""

    assert _is_a_rewrite_of(

        "The tide went out further than she had ever seen it, and kept going.",

        "The tide went out much further than she had ever seen it, and kept going.",

    )





def test_a_pathological_paragraph_is_bounded_rather_than_diffed() -> None:
    """The diff runs in a synchronous route on a *reading* gesture, so an
    unbounded cost is a hung pane with nothing on screen explaining why.

    **This asserts the TIME, not the stacking.** The first version of this test
    asserted only that the runs came back stacked — and passed with the guard
    removed, because `_is_a_rewrite_of` independently rejects a heavily edited
    block and stacks it anyway. It proved nothing. Unguarded this pair takes
    ~95 seconds; the threshold below is two orders of magnitude of headroom, so
    it fails on the defect and not on a slow machine.
    """
    words = MAX_WORD_DIFF_TOKENS * 2
    was = " ".join(f"w{i % 13}" for i in range(words))
    # Only every tenth word edited, so the two blocks stay similar enough that
    # the rewrite gate would say yes and attempt a word-level diff.
    now = " ".join(f"w{i % 13}!" if i % 10 == 0 else f"w{i % 13}" for i in range(words))
    started = time.perf_counter()
    runs = diff_runs(was, now)
    elapsed = time.perf_counter() - started
    assert reassembles(runs, was, now)
    assert all(run.stacked for run in runs if run.kind != "equal")
    assert elapsed < 5, f"took {elapsed:.1f}s — the size guard is not holding"
