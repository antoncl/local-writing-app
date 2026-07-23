"""Drift reporting between two witnesses (ADR-0043, #439 slice 3).

**The acceptance bar is a drift-blind oracle failing.** Slice 2 shipped with
three provenance-blind oracles: inverting every warm/cool class — which reverses
the feature's central claim — passed 22 of 22 tests, because every assertion
measured the report's *shape* rather than its *claim*. So the assertions here
name the entity, the field, the value-then and the value-now. Concretely, all of
these must turn this suite red:

- returning an empty report;
- returning every witnessed entity rather than the changed ones;
- swapping `was` with `now`;
- collapsing `unknown` into `no`;
- dropping either direction of membership.

The comparison is pure, so most of it is exercised on hand-built witnesses. The
route-level tests at the bottom prove the wiring: that a real capture records a
real witness and the diff endpoint carries the real report.
"""

from __future__ import annotations

import unittest

from test_snapshot_witness import WitnessTestCase

from app.models import (
    REVISION_KIND,
    WITNESS_VERSION,
    MetadataFieldDefinition,
    Witness,
    WitnessEntity,
    WitnessFieldType,
)
from app.services.project.snapshot_drift import compare_witnesses
from app.services.project.snapshot_witness import (
    SOURCE_DYNAMIC,
    SOURCE_ENTITY_REF,
    SOURCE_MUTATION,
)

ALL_SOURCES = [SOURCE_MUTATION, SOURCE_ENTITY_REF, SOURCE_DYNAMIC]


def entity(entity_id: str = "lore_tom", **changed: object) -> WitnessEntity:
    """One witnessed entity, with everything but the point under test held
    fixed — so a failure names the axis rather than the fixture.

    Keyword overrides rather than a parameter per field: this fixture would
    otherwise grow one argument per witness field, and a caller reading
    `entity(source_layer_id="layer-b")` should see the *one* thing that differs from the
    baseline, not the nine that do not.
    """
    fields: dict = {
        "id": entity_id,
        "title": "Tom",
        "sources": [SOURCE_ENTITY_REF],
        "revision": "rev-1",
        "revision_kind": REVISION_KIND,
        "source_layer_label": "Base Folder",
        "state": {"eye_colour": "green"},
        "overrides": [],
        **changed,
    }
    fields.setdefault(
        "field_types",
        {
            key: WitnessFieldType(label="Eye colour" if key == "eye_colour" else key, type="text")
            for key in fields["state"]
        },
    )
    return WitnessEntity(**fields)


def witness(*entities: WitnessEntity, version: int = WITNESS_VERSION, truncated: bool = False,
            sources: list[str] | None = None) -> Witness:
    return Witness(
        version=version,
        truncated=truncated,
        sources_recorded=sources if sources is not None else list(ALL_SOURCES),
        entities=list(entities),
    )


class ReportNamesTheChangeTests(unittest.TestCase):
    """ADR-0043: *if the report is the only protection, the report is the
    feature.* It must name the entity, the field, the value then and the value
    now — never "context has changed since this snapshot was taken"."""

    def test_a_changed_field_names_entity_field_and_both_values(self) -> None:
        report = compare_witnesses(
            witness(entity(state={"eye_colour": "green"})),
            witness(entity(state={"eye_colour": "blue"}, revision="rev-2")),
        )
        self.assertEqual(len(report.entities), 1)
        drifted = report.entities[0]
        self.assertEqual(drifted.title, "Tom")
        self.assertEqual(len(drifted.fields), 1)
        field = drifted.fields[0]
        # Ordered assertions, so swapping was/now turns this red. A shape-only
        # check ("one field drifted") would not.
        self.assertEqual(field.field_id, "eye_colour")
        self.assertEqual(field.label, "Eye colour")
        self.assertEqual(field.was, "green")
        self.assertEqual(field.now, "blue")

    def test_an_unchanged_world_reports_nothing(self) -> None:
        """The control that stops "report everything" from passing the suite."""
        report = compare_witnesses(witness(entity()), witness(entity()))
        self.assertTrue(report.available)
        self.assertTrue(report.comparable)
        self.assertEqual(report.entities, [])

    def test_a_change_from_a_marker_is_attributed_to_the_marker(self) -> None:
        """The author needs to know whether to look for a marker or for an edit
        — the two are fixed in different places."""
        report = compare_witnesses(
            witness(entity(state={"eye_colour": "green"})),
            witness(entity(state={"eye_colour": "blue"}, overrides=["eye_colour"])),
        )
        self.assertTrue(report.entities[0].fields[0].from_mutation)

    def test_a_direct_edit_is_not_attributed_to_a_marker(self) -> None:
        report = compare_witnesses(
            witness(entity(state={"eye_colour": "green"})),
            witness(entity(state={"eye_colour": "blue"})),
        )
        self.assertFalse(report.entities[0].fields[0].from_mutation)

    def test_blank_and_absent_do_not_flip(self) -> None:
        """Same rule as the compare rail (`same_rendered_value`): a missing key
        and an empty one read identically, so a flip between them shows the
        author two values they cannot tell apart."""
        report = compare_witnesses(
            witness(entity(state={"eye_colour": ""})),
            witness(entity(state={})),
        )
        self.assertEqual(report.entities, [])


class InheritanceAxisTests(unittest.TestCase):
    """Axis 2 — `revision` as an opaque token, and honest degradation."""

    def test_a_changed_revision_reports_the_entry_changed(self) -> None:
        report = compare_witnesses(
            witness(entity(revision="rev-1", state={})),
            witness(entity(revision="rev-2", state={})),
        )
        self.assertEqual(report.entities[0].entry_changed, "yes")

    def test_an_unreadable_token_reports_unknown_not_unchanged(self) -> None:
        """ADR-0043's degrade-coarsely rule. "Unchanged" is a claim, and this is
        not in a position to make it."""
        report = compare_witnesses(
            witness(entity(revision=None, state={})),
            witness(entity(revision="rev-2", state={})),
        )
        self.assertEqual(report.entities[0].entry_changed, "unknown")

    def test_a_redefined_token_reports_unknown(self) -> None:
        """Tokens captured before `revision` is redefined (#314 makes it a
        composite hash) do not compare meaningfully against tokens computed
        after."""
        report = compare_witnesses(
            witness(entity(revision="rev-1", revision_kind="sha256_file", state={})),
            witness(entity(revision="rev-1", revision_kind="composite_v2", state={})),
        )
        self.assertEqual(report.entities[0].entry_changed, "unknown")

    def test_an_identical_token_reports_no(self) -> None:
        """The control: without it, `unknown` hard-coded passes the two tests
        above."""
        report = compare_witnesses(witness(entity(state={})), witness(entity(state={})))
        self.assertEqual(report.entities, [])


class ReinterpretationAxisTests(unittest.TestCase):
    """Axis 3 — the meaning of a recorded value moved under it, scoped to the
    recorded fields alone."""

    def test_a_type_change_on_a_recorded_field_is_reported(self) -> None:
        report = compare_witnesses(
            witness(entity(field_types={"eye_colour": WitnessFieldType(label="Eye colour", type="text")})),
            witness(entity(field_types={"eye_colour": WitnessFieldType(label="Eye colour", type="select")})),
        )
        reinterpreted = report.entities[0].reinterpreted
        self.assertEqual(len(reinterpreted), 1)
        self.assertEqual(reinterpreted[0].field_id, "eye_colour")
        self.assertEqual(reinterpreted[0].type_was, "text")
        self.assertEqual(reinterpreted[0].type_now, "select")

    def test_a_constraint_change_on_a_recorded_field_is_reported(self) -> None:
        was_type = WitnessFieldType(label="Eye colour", type="select", options=["green", "blue"])
        now_type = WitnessFieldType(label="Eye colour", type="select", options=["green"])
        report = compare_witnesses(
            witness(entity(field_types={"eye_colour": was_type})),
            witness(entity(field_types={"eye_colour": now_type})),
        )
        self.assertEqual(report.entities[0].reinterpreted[0].options_now, ["green"])

    def test_a_field_only_one_witness_recorded_is_not_a_reinterpretation(self) -> None:
        """Not a whole-schema hash. That fires on every schema edit, including
        the additions the sparse storage model already absorbs, so most reports
        would announce a change with no consequence — and a detector that cries
        wolf trains the dismissal that makes the report worthless.

        The two witnesses are deliberately **asymmetric**: `rank` exists only on
        the now side. Widening `_reinterpretations` from the intersection to the
        union — the exact regression ADR-0043 pre-refutes — turns this red. The
        earlier version of this test passed two identical witnesses, so it could
        not fail and merely restated the unchanged-world control."""
        shared = WitnessFieldType(label="Eye colour", type="text")
        report = compare_witnesses(
            witness(entity(field_types={"eye_colour": shared})),
            witness(
                entity(
                    field_types={
                        "eye_colour": shared,
                        "rank": WitnessFieldType(label="Rank", type="select", options=["Captain"]),
                    }
                )
            ),
        )
        self.assertEqual(
            [e.reinterpreted for e in report.entities],
            [],
            "a field present on only one side is a field change, not a reinterpretation",
        )


class MembershipAxisTests(unittest.TestCase):
    """Axis 4 — both directions. #439's acceptance said an entity absent at
    capture or deleted since is not reported; that line was overruled (design doc
    §2). A character primary in one version and gone in the other is exactly what
    the report exists to say."""

    def test_an_entity_gone_from_the_current_version_is_reported_removed(self) -> None:
        report = compare_witnesses(
            witness(entity("lore_chicago", title="Chicago")),
            witness(),
        )
        self.assertEqual(len(report.entities), 1)
        self.assertEqual(report.entities[0].title, "Chicago")
        self.assertEqual(report.entities[0].membership, "removed")

    def test_an_entity_new_to_the_current_version_is_reported_added(self) -> None:
        report = compare_witnesses(
            witness(),
            witness(entity("lore_chicago", title="Chicago")),
        )
        self.assertEqual(report.entities[0].membership, "added")

    def test_an_entity_neither_side_counts_as_context_is_never_reported(self) -> None:
        """The invariant, pinned where it now lives.

        A witness may carry an entity with **no sources** — recorded so its
        values can be compared, but not a member of that version's context. If
        neither side counts it, there is nothing to say about the set and nothing
        to say about a version that never had it. The earlier version of this
        test put the same entity in both witnesses with full sources, so it was a
        third copy of the unchanged-world control and pinned nothing."""
        carried = entity("lore_chicago", title="Chicago", sources=[])
        report = compare_witnesses(witness(carried), witness(carried))
        self.assertEqual([e.entity_id for e in report.entities], [])

    def test_a_dropped_entity_still_has_its_values_compared(self) -> None:
        """ADR-0043's motivating case. An entity whose only source was a marker
        interval, and whose interval has since been deleted, is no longer a
        member *and* has values worth naming. Keying membership on presence
        returned a bare "no longer part of this scene" and discarded both."""
        report = compare_witnesses(
            witness(entity("lore_chicago", title="Chicago", sources=[SOURCE_MUTATION],
                           state={"weather": "storm"}, overrides=["weather"])),
            witness(entity("lore_chicago", title="Chicago", sources=[],
                           state={"weather": "clear"})),
        )
        self.assertEqual(len(report.entities), 1)
        drifted = report.entities[0]
        self.assertEqual(drifted.membership, "removed")
        self.assertEqual(
            [(f.field_id, f.was, f.now) for f in drifted.fields],
            [("weather", "storm", "clear")],
            "the report must name what the world became, not only that the set shrank",
        )

    def test_membership_is_only_claimed_over_sources_both_sides_observed(self) -> None:
        """A capture with no prose editor behind it records two sources. Naively
        differencing that against a three-source witness would report every
        implicitly-detected entity as removed — a wolf cried on a scene nobody
        touched."""
        detected = entity("lore_chicago", title="Chicago", sources=[SOURCE_DYNAMIC])
        report = compare_witnesses(
            witness(detected),
            witness(sources=[SOURCE_MUTATION, SOURCE_ENTITY_REF]),
        )
        self.assertEqual(report.entities, [])

    def test_an_explicitly_referenced_entity_is_still_reported_across_that_seam(self) -> None:
        """The control for the rule above: narrowing must not swallow the
        sources both sides *did* observe."""
        referenced = entity("lore_chicago", title="Chicago", sources=[SOURCE_ENTITY_REF])
        report = compare_witnesses(
            witness(referenced),
            witness(sources=[SOURCE_MUTATION, SOURCE_ENTITY_REF]),
        )
        self.assertEqual(report.entities[0].membership, "removed")


class VisibilityAxisTests(unittest.TestCase):
    """Axis 5 — the design doc's §3 gap. Which layer wins is a property of the
    resolved index, not of any file, so no hash over bytes can see it."""

    def test_a_moved_source_layer_is_reported_with_no_file_edit(self) -> None:
        report = compare_witnesses(
            witness(entity(source_layer_label="Series")),
            witness(entity(source_layer_label="Book")),
        )
        drifted = report.entities[0]
        self.assertEqual(drifted.layer_was, "Series")
        self.assertEqual(drifted.layer_now, "Book")
        self.assertEqual(
            drifted.entry_changed,
            "no",
            "the file is byte-identical — this axis exists because `revision` cannot see it",
        )


class DegradationTests(unittest.TestCase):
    """Three states, kept distinguishable: the surface cannot honour a
    distinction the payload has collapsed."""

    def test_a_snapshot_with_no_witness_is_not_a_snapshot_with_no_drift(self) -> None:
        report = compare_witnesses(None, witness(entity()))
        self.assertFalse(report.available)
        self.assertEqual(report.entities, [])

    def test_a_witness_of_an_unreadable_version_is_not_comparable(self) -> None:
        report = compare_witnesses(
            witness(entity(), version=WITNESS_VERSION + 1),
            witness(entity()),
        )
        self.assertTrue(report.available)
        self.assertFalse(report.comparable)

    def test_a_truncated_witness_says_so_in_the_report(self) -> None:
        report = compare_witnesses(witness(entity(), truncated=True), witness(entity()))
        self.assertTrue(report.truncated)

    def test_a_live_side_that_would_not_build_is_not_an_unchanged_world(self) -> None:
        """`build_witness` returns `None` when it could not build. Reporting an
        empty comparison for that was an affirmative all-clear drawn from having
        seen nothing — the claim ADR-0043's degrade-coarsely rule forbids."""
        report = compare_witnesses(witness(entity()), None)
        self.assertTrue(report.available)
        self.assertFalse(report.comparable)

    def test_truncation_suppresses_membership_but_keeps_field_drift(self) -> None:
        """The cap keeps the lowest-sorting ids and is applied independently on
        each side, so one new low-sorting entity shifts the retained window and
        drops a different tail — which the set difference then reported as an
        entity "no longer part of this scene" while it sat, present and
        unchanged, in both worlds. Field drift on the entities both sides *did*
        retain is unaffected and must still be reported."""
        report = compare_witnesses(
            witness(
                entity("lore_a", state={"eye_colour": "green"}),
                entity("lore_z", title="Zephyr"),
                truncated=True,
            ),
            witness(entity("lore_a", state={"eye_colour": "blue"}), truncated=True),
        )
        by_id = {e.entity_id: e for e in report.entities}
        self.assertNotIn(
            "lore_z", by_id, "a truncated comparison cannot claim an entity left the scene"
        )
        self.assertEqual(
            [(f.was, f.now) for f in by_id["lore_a"].fields],
            [("green", "blue")],
            "suppressing the membership axis must not suppress the others",
        )

    def test_membership_is_claimed_when_neither_side_truncated(self) -> None:
        """The control. Without it, suppressing membership unconditionally passes
        the test above."""
        report = compare_witnesses(witness(entity("lore_z", title="Zephyr")), witness())
        self.assertEqual([e.membership for e in report.entities], ["removed"])


class DriftOverTheDiffRouteTests(WitnessTestCase):
    """The wiring: a real capture records a real witness, and the diff endpoint
    carries the real report — on one synchronous request, which is what makes
    "restore reports drift" free (a restore is only reachable from a parked
    notch, and parking is what fetches this)."""

    def _capture(self) -> str:
        response = self.client.post(
            f"/api/scenes/{self.scene_id}/snapshots", json={"dynamic_context": []}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def _diff(self, snapshot_id: str, body: str = "") -> dict:
        response = self.client.post(
            f"/api/scenes/{self.scene_id}/snapshots/{snapshot_id}/diff",
            json={"body": body, "title": "The Tide", "dynamic_context": []},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_the_diff_reports_a_lore_edit_made_after_the_capture(self) -> None:
        self._save_scene(cast=[self.tom])
        snapshot_id = self._capture()
        self._set_lore_field(self.tom, "eye_colour", "blue")

        drift = self._diff(snapshot_id)["drift"]
        self.assertTrue(drift["available"])
        self.assertEqual(len(drift["entities"]), 1)
        drifted = drift["entities"][0]
        self.assertEqual(drifted["title"], "Tom")
        self.assertEqual(drifted["entry_changed"], "yes")
        self.assertEqual(
            [(f["label"], f["was"], f["now"]) for f in drifted["fields"]],
            [("Eye colour", "green", "blue")],
        )

    def test_a_scene_nobody_touched_reports_no_drift(self) -> None:
        """The park-on-a-notch control. Slice 2's largest defect class was a
        comparison whose two sides came off different pipelines and flipped
        fields on an untouched scene; the witness is built by one function,
        called on both sides."""
        self._save_scene(cast=[self.tom])
        snapshot_id = self._capture()
        drift = self._diff(snapshot_id)["drift"]
        self.assertTrue(drift["available"])
        self.assertEqual(drift["entities"], [])

    def test_an_unquoted_yaml_date_does_not_drift_against_itself(self) -> None:
        """Both sides must come off the same pipeline. The stored side goes
        through `model_dump(mode="json")` on its way to the sidecar, so a value
        the live side keeps as `datetime.date` compared unequal against its own
        ISO string — a row reading `Born: 1985-04-12 → 1985-04-12`, on every
        park, forever, on a scene nobody touched. `_normalise_metadata` is the
        coercion that makes the two sides comparable, and it is the same one
        `_snapshot_state` already applies to the scene's own fields."""
        self._define_lore_field("born", MetadataFieldDefinition(name="Born", type="text"))
        self._write_lore_front_matter(self.tom, "born: 1985-04-12")
        self._save_scene(cast=[self.tom])
        snapshot_id = self._capture()

        drift = self._diff(snapshot_id)["drift"]
        self.assertEqual(
            drift["entities"], [], "an untouched entry must not drift against itself"
        )

    def test_a_non_string_metadata_key_does_not_break_the_save(self) -> None:
        """A hand-authored `metadata: {2019: …}` used to reach a `str`-typed
        pydantic field and 500 the save. `_normalise_metadata` coerces the key,
        so the witness records it rather than merely surviving it."""
        self._write_lore_front_matter(self.tom, "2019: the year")
        self._save_scene(cast=[self.tom])
        response = self.client.post(
            f"/api/scenes/{self.scene_id}/snapshots", json={"dynamic_context": []}
        )
        self.assertEqual(response.status_code, 200, response.text)
        witness = self.service.build_witness(self.scene_id, [])
        recorded = next(e for e in witness.entities if e.id == self.tom)
        self.assertEqual(recorded.state["2019"], "the year")

    def test_a_malformed_schema_is_never_the_reason_a_capture_fails(self) -> None:
        """The stated contract: "a capture is never the reason a save fails".

        A `metadata.schema.yaml` that is valid YAML but the wrong *shape* raises
        a pydantic `ValidationError` out of `build_mutations_index` — a
        `ValueError`, which escaped an except tuple naming only
        `ProjectServiceError` and `OSError`. The capture must still write the
        prose, and must record **no** witness rather than an empty one: an empty
        witness is read as a real comparison that found nothing.
        """
        self._save_scene(cast=[self.tom])
        (self.root / "metadata.schema.yaml").write_text(
            "fields:\n  rank: not-a-mapping\n", encoding="utf-8"
        )
        response = self.client.post(
            f"/api/scenes/{self.scene_id}/snapshots", json={"dynamic_context": []}
        )
        self.assertEqual(response.status_code, 200, response.text)

        snapshot_id = response.json()["id"]
        root = self.service._require_project()
        self.assertIsNone(self.service.read_snapshot_witness(root, self.scene_id, snapshot_id))

    def test_a_corrupt_witness_is_not_reported_as_an_absent_one(self) -> None:
        """Absent means "this snapshot predates the witness — nothing to
        compare". A witness that is present but will not parse is one *recorded
        under a shape this build cannot read*, which is `comparable=False`. They
        used to produce byte-identical payloads, so the corrupt case rendered
        nothing at all."""
        self._save_scene(cast=[self.tom])
        snapshot_id = self._capture()
        sidecar = self.root / "snapshots" / self.scene_id / f"{snapshot_id}.yaml"
        record = self.service._read_yaml(sidecar)
        record["witness"] = {"version": 1, "entities": [{"nonsense": True}]}
        self.service._write_yaml(sidecar, record)

        drift = self._diff(snapshot_id)["drift"]
        self.assertTrue(drift["available"], "the witness is present; it just will not parse")
        self.assertFalse(drift["comparable"])

    def test_a_snapshot_taken_before_the_witness_existed_says_so(self) -> None:
        """`available=False` — a third state, distinct from both "unchanged" and
        "unknown"."""
        self._save_scene(cast=[self.tom])
        snapshot_id = self._capture()
        sidecar = self.root / "snapshots" / self.scene_id / f"{snapshot_id}.yaml"
        record = self.service._read_yaml(sidecar)
        record.pop("witness")
        self.service._write_yaml(sidecar, record)

        drift = self._diff(snapshot_id)["drift"]
        self.assertFalse(drift["available"])

    def test_the_witness_is_never_written_back_by_a_restore(self) -> None:
        """A witness is evidence about the graph, not a participant in it: never
        restored, never authoritative, never consulted by the resolver."""
        self._save_scene(cast=[self.tom])
        snapshot_id = self._capture()
        self._set_lore_field(self.tom, "eye_colour", "blue")

        response = self.client.post(
            f"/api/scenes/{self.scene_id}/snapshots/{snapshot_id}/restore"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            self.service.read_lore_entry(self.tom).metadata["eye_colour"],
            "blue",
            "restoring the prose must not put the witnessed world back",
        )

    def test_a_restore_is_never_refused_because_of_drift(self) -> None:
        """Advisory: no gate, no acknowledgement, no restore this declines to
        perform."""
        self._save_scene("Before.", cast=[self.tom])
        snapshot_id = self._capture()
        self._set_lore_field(self.tom, "eye_colour", "blue")
        self._save_scene("After.", cast=[self.tom])

        response = self.client.post(
            f"/api/scenes/{self.scene_id}/snapshots/{snapshot_id}/restore"
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Before.", response.json()["body"])


class DriftIsNotDescribedGenericallyTests(unittest.TestCase):
    """ADR-0043 forbids the wording outright, so it is asserted rather than
    trusted: nothing the backend puts on the wire may be a stand-in for the
    specific claim."""

    def test_the_report_carries_values_rather_than_a_sentence(self) -> None:
        report = compare_witnesses(
            witness(entity(state={"eye_colour": "green"})),
            witness(entity(state={"eye_colour": "blue"})),
        )
        payload = report.model_dump_json()
        self.assertNotIn("context has changed", payload.lower())
        self.assertIn("green", payload)
        self.assertIn("blue", payload)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
