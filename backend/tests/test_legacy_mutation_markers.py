"""Tests for the ADR-0095 §12 legacy→sets-and-anchors converter
(`convert_legacy_mutations`, `app/services/project/legacy_mutation_markers.py`).
Pure unit tests: no filesystem, no ProjectService."""

from __future__ import annotations

import unittest

from app.services.project.legacy_mutation_markers import (
    convert_legacy_mutations,
    convert_restored_scene,
)
from app.services.project.mutation_anchors import (
    MUTATION_ANCHOR_CLOSE_PATTERN,
    MUTATION_ANCHOR_PATTERN,
    derive_anchor_id,
    derive_set_id,
)

ENTITY_TYPES = {"honor": "character", "mira": "character"}


def entity_type(entity_id: str) -> str | None:
    return ENTITY_TYPES.get(entity_id)


def anchors_in(body: str) -> list[tuple[str, str]]:
    """[(set_id, anchor_id), ...] in the order they appear in `body`."""
    return [(m.group("set_id"), m.group("id")) for m in MUTATION_ANCHOR_PATTERN.finditer(body)]


def closes_in(body: str) -> list[tuple[str, str, str]]:
    """[(ref, row, close_id), ...] in the order they appear in `body`."""
    return [
        (m.group("ref"), m.group("row") or "", m.group("id"))
        for m in MUTATION_ANCHOR_CLOSE_PATTERN.finditer(body)
    ]


class SingleLineMarkerTests(unittest.TestCase):
    def test_single_line_marker_becomes_anchor(self):
        body = "Before. <!-- mutate:entity=honor;field=rank;value=Captain;name=Promotion;id=m1 --> After."
        result = convert_legacy_mutations([("s1", body)], entity_type)

        self.assertIn("s1", result.bodies)
        new_body = result.bodies["s1"]
        self.assertNotIn("field=rank", new_body)
        self.assertTrue(new_body.startswith("Before. "))
        self.assertTrue(new_body.endswith(" After."))

        self.assertEqual(len(result.sets), 1)
        s = result.sets[0]
        self.assertEqual(s.anchor_id, "m1")
        self.assertEqual(s.set_id, derive_set_id("m1"))
        self.assertEqual(s.unit_id, "m1")
        self.assertEqual(s.entity_id, "honor")
        self.assertEqual(s.title, "Promotion")
        self.assertEqual(s.target_entry_type, "character")
        self.assertEqual(len(s.rows), 1)
        row = s.rows[0]
        self.assertEqual((row.id, row.field, row.op, row.value), ("m1", "rank", "replace", "Captain"))

        anchors = anchors_in(new_body)
        self.assertEqual(anchors, [(s.set_id, "m1")])

    def test_untitled_marker_gets_empty_title(self):
        body = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        result = convert_legacy_mutations([("s1", body)], entity_type)
        self.assertEqual(result.sets[0].title, "")


class CarrierTests(unittest.TestCase):
    CARRIER = (
        "<!-- mutate:entity=honor;name=Promotion;id=u1\n"
        "field=rank;value=Captain;id=r1\n"
        "field=posting;value=Bridge;id=r2\n"
        "-->"
    )

    def test_carrier_becomes_one_set_rows_keep_ids(self):
        body = f"Text before.\n{self.CARRIER}\nText after."
        result = convert_legacy_mutations([("s1", body)], entity_type)

        self.assertEqual(len(result.sets), 1)
        s = result.sets[0]
        self.assertEqual(s.title, "Promotion")
        self.assertEqual(s.unit_id, "u1")
        self.assertEqual(s.anchor_id, "u1")
        self.assertEqual([r.id for r in s.rows], ["r1", "r2"])
        self.assertEqual([r.field for r in s.rows], ["rank", "posting"])
        self.assertEqual([r.value for r in s.rows], ["Captain", "Bridge"])

        new_body = result.bodies["s1"]
        self.assertIn("Text before.\n", new_body)
        self.assertIn("\nText after.", new_body)
        self.assertEqual(anchors_in(new_body), [(s.set_id, "u1")])

    def test_malformed_carrier_left_untouched(self):
        malformed = (
            "<!-- mutate:entity=honor;id=u1\n"
            "field=rank;value=Captain;id=r1\n"
            "not-a-row-at-all\n"
            "-->"
        )
        body = f"Prose. {malformed} More prose."
        result = convert_legacy_mutations([("s1", body)], entity_type)
        self.assertNotIn("s1", result.bodies)
        self.assertEqual(result.sets, [])


class GroupMarkerTests(unittest.TestCase):
    def test_group_markers_become_separate_sets(self):
        body = (
            "<!-- mutate:entity=honor;field=rank;value=Captain;name=Storm;group=g1;id=m1 --> "
            "middle "
            "<!-- mutate:entity=honor;field=posting;value=Bridge;name=Storm;group=g1;id=m2 -->"
        )
        result = convert_legacy_mutations([("s1", body)], entity_type)

        self.assertEqual(len(result.sets), 2)
        self.assertEqual({s.anchor_id for s in result.sets}, {"m1", "m2"})
        self.assertNotEqual(result.sets[0].set_id, result.sets[1].set_id)
        for s in result.sets:
            self.assertEqual(s.title, "Storm")

        new_body = result.bodies["s1"]
        anchors = anchors_in(new_body)
        self.assertEqual([a for _, a in anchors], ["m1", "m2"])
        self.assertIn(" middle ", new_body)

    def test_group_close_expands_to_per_member_closes(self):
        body = (
            "<!-- mutate:entity=honor;field=rank;value=Captain;group=g1;id=m1 -->"
            "<!-- mutate:entity=honor;field=posting;value=Bridge;group=g1;id=m2 -->"
            "<!-- mutate:close;ref=g1;id=c1 -->"
        )
        result = convert_legacy_mutations([("s1", body)], entity_type)
        new_body = result.bodies["s1"]
        closes = closes_in(new_body)
        self.assertEqual(len(closes), 2)
        refs = {ref for ref, _row, _cid in closes}
        self.assertEqual(refs, {"m1", "m2"})
        ids = {cid for _ref, _row, cid in closes}
        self.assertEqual(ids, {"c1", "c1_2"})
        for _ref, row, _cid in closes:
            self.assertEqual(row, "")


class RepeatedUnitIdTests(unittest.TestCase):
    def test_repeated_unit_id_across_scenes_gets_derived_ids(self):
        body = "<!-- mutate:entity=honor;field=rank;value=Captain;id=dup -->"
        result = convert_legacy_mutations([("s1", body), ("s2", body)], entity_type)

        self.assertEqual(len(result.sets), 2)
        first, second = result.sets
        self.assertEqual(first.anchor_id, "dup")
        self.assertEqual(first.set_id, derive_set_id("dup"))
        self.assertEqual(second.anchor_id, derive_anchor_id("s2", "dup"))
        self.assertEqual(second.set_id, derive_set_id("s2:dup"))
        self.assertNotEqual(first.set_id, second.set_id)
        self.assertNotEqual(first.anchor_id, second.anchor_id)

        anchors_s1 = anchors_in(result.bodies["s1"])
        anchors_s2 = anchors_in(result.bodies["s2"])
        self.assertEqual(anchors_s1, [(first.set_id, "dup")])
        self.assertEqual(anchors_s2, [(second.set_id, second.anchor_id)])

    def test_repeated_unit_id_thrice_in_one_scene_plus_earlier_scene(self):
        marker = "<!-- mutate:entity=honor;field=rank;value=Captain;id=dup -->"
        close = "<!-- mutate:close;ref=dup;id=c1 -->"
        s1 = marker
        s2 = f"{marker} a {marker} b {marker} {close}"
        result = convert_legacy_mutations([("s1", s1), ("s2", s2)], entity_type)

        self.assertEqual(len(result.sets), 4)
        set_ids = {s.set_id for s in result.sets}
        anchor_ids = {s.anchor_id for s in result.sets}
        self.assertEqual(len(set_ids), 4, "all four set ids must be distinct")
        self.assertEqual(len(anchor_ids), 4, "all four anchor ids must be distinct")

        first, rep1, rep2, rep3 = result.sets
        self.assertEqual(first.anchor_id, "dup")
        self.assertEqual(first.set_id, derive_set_id("dup"))
        self.assertEqual(rep1.anchor_id, derive_anchor_id("s2", "dup"))
        self.assertEqual(rep1.set_id, derive_set_id("s2:dup"))
        self.assertEqual(rep2.anchor_id, derive_anchor_id("s2", "dup", 2))
        self.assertEqual(rep2.set_id, derive_set_id("s2:dup:2"))
        self.assertEqual(rep3.anchor_id, derive_anchor_id("s2", "dup", 3))
        self.assertEqual(rep3.set_id, derive_set_id("s2:dup:3"))

        new_s2 = result.bodies["s2"]
        anchors_s2 = anchors_in(new_s2)
        self.assertEqual([a for _, a in anchors_s2], [rep1.anchor_id, rep2.anchor_id, rep3.anchor_id])

        closes = closes_in(new_s2)
        self.assertEqual(len(closes), 4)
        refs = {ref for ref, _row, _cid in closes}
        self.assertEqual(refs, {"dup", rep1.anchor_id, rep2.anchor_id, rep3.anchor_id})
        ids = {cid for _ref, _row, cid in closes}
        self.assertEqual(ids, {"c1", "c1_2", "c1_3", "c1_4"})

    def test_repeated_unit_id_within_one_scene(self):
        marker = "<!-- mutate:entity=honor;field=rank;value=Captain;id=dup -->"
        body = f"{marker} between {marker}"
        result = convert_legacy_mutations([("s1", body)], entity_type)

        self.assertEqual(len(result.sets), 2)
        first, second = result.sets
        self.assertEqual(first.anchor_id, "dup")
        self.assertEqual(second.anchor_id, derive_anchor_id("s1", "dup"))
        self.assertNotEqual(first.anchor_id, second.anchor_id)
        anchors = anchors_in(result.bodies["s1"])
        self.assertEqual([a for _, a in anchors], ["dup", second.anchor_id])


class CloseTests(unittest.TestCase):
    def test_row_close_on_a_carrier(self):
        carrier = (
            "<!-- mutate:entity=honor;id=u1\n"
            "field=rank;value=Captain;id=r1\n"
            "field=posting;value=Bridge;id=r2\n"
            "-->"
        )
        body = f"{carrier}<!-- mutate:close;ref=r2;id=c1 -->"
        result = convert_legacy_mutations([("s1", body)], entity_type)
        new_body = result.bodies["s1"]
        closes = closes_in(new_body)
        self.assertEqual(len(closes), 1)
        ref, row, cid = closes[0]
        self.assertEqual(ref, "u1")
        self.assertEqual(row, "r2")
        self.assertEqual(cid, "c1")

    def test_unit_close(self):
        marker = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        body = f"{marker}<!-- mutate:close;ref=m1;id=c1 -->"
        result = convert_legacy_mutations([("s1", body)], entity_type)
        closes = closes_in(result.bodies["s1"])
        self.assertEqual(closes, [("m1", "", "c1")])

    def test_close_before_start_left_alone(self):
        marker = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        close = "<!-- mutate:close;ref=m1;id=c1 -->"
        body = f"{close} {marker}"
        result = convert_legacy_mutations([("s1", body)], entity_type)
        new_body = result.bodies["s1"]
        # The close text (still legacy-shaped) is unchanged; only the marker
        # became an anchor.
        self.assertIn(close, new_body)
        self.assertEqual(anchors_in(new_body), [(result.sets[0].set_id, "m1")])

    def test_unknown_ref_left_alone(self):
        marker = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        close = "<!-- mutate:close;ref=nope;id=c1 -->"
        body = f"{marker}{close}"
        result = convert_legacy_mutations([("s1", body)], entity_type)
        new_body = result.bodies["s1"]
        self.assertIn(close, new_body)


class DeadEntityTests(unittest.TestCase):
    def test_dead_entity_keeps_pin_empty_target_type(self):
        body = "<!-- mutate:entity=ghost;field=rank;value=Captain;id=m1 -->"
        result = convert_legacy_mutations([("s1", body)], entity_type)
        s = result.sets[0]
        self.assertEqual(s.entity_id, "ghost")
        self.assertEqual(s.target_entry_type, "")


class UrlDecodingTests(unittest.TestCase):
    def test_url_decoded_values_and_names(self):
        body = "<!-- mutate:entity=honor;field=rank;value=Captain%20Marvel;name=A%2CB;id=m1 -->"
        result = convert_legacy_mutations([("s1", body)], entity_type)
        s = result.sets[0]
        self.assertEqual(s.title, "A,B")
        self.assertEqual(s.rows[0].value, "Captain Marvel")


class DeterminismAndIdempotenceTests(unittest.TestCase):
    def _sample(self) -> list[tuple[str, str]]:
        carrier = (
            "<!-- mutate:entity=honor;name=Promotion;id=u1\n"
            "field=rank;value=Captain;id=r1\n"
            "field=posting;value=Bridge;id=r2\n"
            "-->"
        )
        marker = "<!-- mutate:entity=mira;field=mood;value=Grim;id=m1 -->"
        close = "<!-- mutate:close;ref=m1;id=c1 -->"
        s1 = f"Chapter one. {carrier} more prose."
        s2 = f"Chapter two. {marker} {close} and {marker}"
        return [("s1", s1), ("s2", s2)]

    def test_deterministic(self):
        scenes = self._sample()
        r1 = convert_legacy_mutations(scenes, entity_type)
        r2 = convert_legacy_mutations(scenes, entity_type)
        self.assertEqual(r1.bodies, r2.bodies)
        self.assertEqual(
            [(s.set_id, s.anchor_id, s.title) for s in r1.sets],
            [(s.set_id, s.anchor_id, s.title) for s in r2.sets],
        )

    def test_idempotent(self):
        scenes = self._sample()
        first = convert_legacy_mutations(scenes, entity_type)
        converted_scenes = [
            (sid, first.bodies.get(sid, body)) for sid, body in scenes
        ]
        second = convert_legacy_mutations(converted_scenes, entity_type)
        self.assertEqual(second.bodies, {})
        self.assertEqual(second.sets, [])

    def test_no_legacy_markers_body_unchanged_and_absent(self):
        body = "Just prose, nothing to see here."
        result = convert_legacy_mutations([("s1", body)], entity_type)
        self.assertEqual(result.bodies, {})
        self.assertEqual(result.sets, [])


class OffsetPreservationTests(unittest.TestCase):
    def test_prose_order_and_text_preserved(self):
        m1 = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        m2 = "<!-- mutate:entity=mira;field=mood;value=Grim;id=m2 -->"
        body = f"Alpha {m1} Beta {m2} Gamma."
        result = convert_legacy_mutations([("s1", body)], entity_type)
        new_body = result.bodies["s1"]
        self.assertTrue(new_body.startswith("Alpha "))
        self.assertIn(" Beta ", new_body)
        self.assertTrue(new_body.endswith(" Gamma."))
        anchors = anchors_in(new_body)
        self.assertEqual([a for _, a in anchors], ["m1", "m2"])
        # m1's anchor appears before m2's in the resulting text.
        self.assertLess(new_body.index("id=m1"), new_body.index("id=m2"))


class ConvertRestoredSceneTests(unittest.TestCase):
    """`convert_restored_scene` (ADR-0095 §11) — a single restored body, no
    manuscript order to lean on, so it must probe the ids `convert_legacy_mutations`
    could have derived rather than deriving them itself."""

    def test_no_existing_set_creates_one_at_the_first_occurrence_ids(self):
        body = "<!-- mutate:entity=honor;field=rank;value=Captain;name=Promotion;id=m1 -->"
        new_body, to_create = convert_restored_scene("s1", body, entity_type, lambda _sid: False)

        self.assertEqual(anchors_in(new_body), [(derive_set_id("m1"), "m1")])
        self.assertEqual(len(to_create), 1)
        created = to_create[0]
        self.assertEqual(created.set_id, derive_set_id("m1"))
        self.assertEqual(created.anchor_id, "m1")
        self.assertEqual(created.title, "Promotion")
        self.assertEqual(created.target_entry_type, "character")
        self.assertEqual((created.rows[0].field, created.rows[0].value), ("rank", "Captain"))

    def test_the_first_occurrence_set_already_existing_resolves_to_it_no_create(self):
        body = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        existing = {derive_set_id("m1")}
        new_body, to_create = convert_restored_scene("s1", body, entity_type, lambda sid: sid in existing)

        self.assertEqual(anchors_in(new_body), [(derive_set_id("m1"), "m1")])
        self.assertEqual(to_create, [])

    def test_the_per_scene_set_already_existing_is_preferred_over_the_first_occurrence_one(self):
        body = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        per_scene_id = derive_set_id("s1:m1")
        existing = {per_scene_id, derive_set_id("m1")}  # both exist; per-scene wins
        new_body, to_create = convert_restored_scene("s1", body, entity_type, lambda sid: sid in existing)

        self.assertEqual(anchors_in(new_body), [(per_scene_id, derive_anchor_id("s1", "m1"))])
        self.assertEqual(to_create, [])

    def test_neither_exists_falls_back_to_first_occurrence_and_creates_it(self):
        body = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        new_body, to_create = convert_restored_scene("s1", body, entity_type, lambda _sid: False)

        self.assertEqual(anchors_in(new_body), [(derive_set_id("m1"), "m1")])
        self.assertEqual([c.set_id for c in to_create], [derive_set_id("m1")])

    def test_a_unit_id_repeated_within_the_body_resolves_each_occurrence_against_its_own_per_scene_set(self):
        # The realistic case: this scene already went through the real
        # migration once (or an earlier restore), so both repeats' per-scene
        # sets already exist on disk — each occurrence's own candidate wins,
        # and the two resolve to distinct sets.
        marker = "<!-- mutate:entity=honor;field=rank;value=Captain;id=dup -->"
        body = f"{marker} between {marker}"
        first_repeat_set = derive_set_id("s1:dup")
        second_repeat_set = derive_set_id("s1:dup:2")
        existing = {first_repeat_set, second_repeat_set}
        new_body, to_create = convert_restored_scene("s1", body, entity_type, lambda sid: sid in existing)

        anchors = anchors_in(new_body)
        self.assertEqual(anchors[0], (first_repeat_set, derive_anchor_id("s1", "dup", 1)))
        self.assertEqual(anchors[1], (second_repeat_set, derive_anchor_id("s1", "dup", 2)))
        self.assertNotEqual(anchors[0][1], anchors[1][1])
        self.assertEqual(to_create, [])

    def test_a_unit_id_repeated_within_the_body_with_nothing_on_disk_falls_back_per_occurrence(self):
        # Neither candidate exists for any occurrence (this exact body never
        # reached a real migration): the first occurrence falls back to the
        # bare first-occurrence id; each later occurrence falls back to the
        # per-scene id for THIS scene's own (k - 1)-th repeat — never the
        # bare id again — so repeats in one restored body never collide.
        marker = "<!-- mutate:entity=honor;field=rank;value=Captain;id=dup -->"
        body = f"{marker} between {marker} and {marker}"
        new_body, to_create = convert_restored_scene("s1", body, entity_type, lambda _sid: False)

        anchors = anchors_in(new_body)
        self.assertEqual(anchors[0], (derive_set_id("dup"), "dup"))
        self.assertEqual(anchors[1], (derive_set_id("s1:dup"), derive_anchor_id("s1", "dup", 1)))
        self.assertEqual(anchors[2], (derive_set_id("s1:dup:2"), derive_anchor_id("s1", "dup", 2)))
        anchor_ids = [a for _set_id, a in anchors]
        set_ids = [s for s, _a in anchors]
        self.assertEqual(len(set(anchor_ids)), 3, "all three anchor ids must be distinct")
        self.assertEqual(len(set(set_ids)), 3, "all three set ids must be distinct")
        self.assertEqual([c.set_id for c in to_create], set_ids)

    def test_closes_are_rewritten_with_the_same_rules_as_the_converter(self):
        marker = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        close = "<!-- mutate:close;ref=m1;id=c1 -->"
        body = f"{marker}{close}"
        new_body, _to_create = convert_restored_scene("s1", body, entity_type, lambda _sid: False)

        closes = closes_in(new_body)
        self.assertEqual(closes, [("m1", "", "c1")])

    def test_a_carrier_row_close_becomes_ref_and_row(self):
        carrier = (
            "<!-- mutate:entity=honor;id=u1\n"
            "field=rank;value=Captain;id=r1\n"
            "field=posting;value=Bridge;id=r2\n"
            "-->"
        )
        body = f"{carrier}<!-- mutate:close;ref=r2;id=c1 -->"
        new_body, _to_create = convert_restored_scene("s1", body, entity_type, lambda _sid: False)

        closes = closes_in(new_body)
        self.assertEqual(closes, [("u1", "r2", "c1")])

    def test_dead_entity_keeps_the_pin_and_empty_target_type(self):
        body = "<!-- mutate:entity=ghost;field=rank;value=Captain;id=m1 -->"
        _new_body, to_create = convert_restored_scene("s1", body, entity_type, lambda _sid: False)

        self.assertEqual(to_create[0].entity_id, "ghost")
        self.assertEqual(to_create[0].target_entry_type, "")

    def test_pure_no_filesystem_deterministic(self):
        body = "<!-- mutate:entity=honor;field=rank;value=Captain;id=m1 -->"
        first = convert_restored_scene("s1", body, entity_type, lambda _sid: False)
        second = convert_restored_scene("s1", body, entity_type, lambda _sid: False)
        self.assertEqual(first[0], second[0])
        self.assertEqual([c.set_id for c in first[1]], [c.set_id for c in second[1]])


if __name__ == "__main__":
    unittest.main()
