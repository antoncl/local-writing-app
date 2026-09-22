"""ADR-0090 §2 (#2115): the candidate set for a settled change to one lore
entry — four named routes (references, referenced-by, mutates, mentions),
each a reason a dependent node might need a look. Read-only: no candidate
call may write anything, so a hash sweep of the project files brackets every
assertion group.
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    MetadataFieldDefinition,
    SaveLoreEntryRequest,
    UpsertMetadataFieldRequest,
)
from app.services.project_service import ProjectService


def _define_field(service: ProjectService, field_id: str, field_type: str, name: str) -> None:
    layers = service.read_metadata_schema_layers()
    service.upsert_metadata_field(
        UpsertMetadataFieldRequest(
            layer_id=layers.layers[-1].id,
            field_id=field_id,
            field=MetadataFieldDefinition(name=name, type=field_type),
            entry_type="lore:character",
        )
    )


def _hash_tree(root: Path) -> dict[str, str]:
    """A content hash per file under `root`, excluding the rebuildable `.cache/`
    — the read-only invariant's oracle."""
    hashes: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if ".cache" in path.relative_to(root).parts:
            continue
        hashes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


class ChangeCandidatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Change Candidates Tests")
        self.client = TestClient(app)

        _define_field(self.service, "rank", "text", "Rank")
        _define_field(self.service, "whereabouts", "text", "Whereabouts")
        _define_field(self.service, "posting", "entity_ref", "Posting")
        _define_field(self.service, "captain", "entity_ref", "Captain")
        _define_field(self.service, "father", "entity_ref", "Father")

        self.barracks = self._make_lore("Watch Barracks", body="")
        self.marek = self._make_lore(
            "Marek Vell",
            body="",
            metadata={"rank": "Lieutenant", "aliases": ["the Captain"], "posting": self.barracks},
        )
        self.city_guard = self._make_lore(
            "City Guard", body="", metadata={"captain": self.marek}
        )
        self.ilse = self._make_lore(
            "Ilse",
            body="Her father the captain taught her to sail.",
            metadata={"father": self.marek},
        )
        self.weir_tavern = self._make_lore(
            "Weir Tavern", body="Marek Vell used to drink here before the posting."
        )
        self.rumour = self._make_lore(
            "The Deserter's Rumour", body="Nobody has traced it back to anyone."
        )
        # Marek's own body names the Rumour by title — a mention FROM the
        # source, which must not make Rumour a candidate (direction matters).
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="He has heard whispers of The Deserter's Rumour.",
                entry_type="lore:character",
                metadata={
                    "rank": "Lieutenant",
                    "aliases": ["the Captain"],
                    "posting": self.barracks,
                },
            ),
        )

        self.ch5 = self._new_scene(
            "Chapter Five",
            f"<!-- mutate:entity={self.marek};field=rank;value=Captain;id=m_rank -->",
        )
        self.ch11 = self._new_scene(
            "Chapter Eleven",
            f"<!-- mutate:entity={self.marek};field=whereabouts;value=Frontier%20Post;id=m_where -->",
        )
        self.ch9 = self._new_scene("Chapter Nine", "She saved the Captain's usual table.")
        self.ch2 = self._new_scene("Chapter Two", "A quiet morning, unrelated to anyone.")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _make_lore(self, title: str, *, body: str, metadata: dict | None = None) -> str:
        entry = self.service.create_lore_entry(
            CreateLoreEntryRequest(title=title, entry_type="lore:character")
        )
        self.service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title=title, body=body, entry_type="lore:character", metadata=metadata or {}
            ),
        )
        return entry.id

    def _new_scene(self, title: str, body: str) -> str:
        scene_id = self.client.post("/api/scenes", json={"title": title}).json()["id"]
        saved = self.client.put(f"/api/scenes/{scene_id}", json={"title": title, "body": body})
        self.assertEqual(saved.status_code, 200, saved.text)
        return scene_id

    def _ids(self, result) -> set[str]:
        return {item.id for item in result.items}

    # --- no baseline ---------------------------------------------------

    def test_no_baseline_candidate_membership_and_tiers(self) -> None:
        before = _hash_tree(self.root)
        result = self.service.change_candidates(self.marek)
        after = _hash_tree(self.root)
        self.assertEqual(before, after)

        present = self._ids(result)
        self.assertEqual(
            present,
            {self.city_guard, self.ilse, self.barracks, self.ch5, self.ch11, self.weir_tavern, self.ch9},
        )
        self.assertNotIn(self.marek, present)
        self.assertNotIn(self.rumour, present)
        self.assertNotIn(self.ch2, present)

        by_id = {item.id: item for item in result.items}
        for declared_id in (self.city_guard, self.ilse, self.barracks, self.ch5, self.ch11):
            self.assertEqual(by_id[declared_id].tier, "declared", declared_id)
        self.assertEqual(by_id[self.weir_tavern].tier, "mention")
        self.assertEqual(by_id[self.ch9].tier, "mention")
        self.assertTrue(result.whole_entry)
        self.assertEqual(result.changed_fields, [])
        self.assertTrue(result.body_changed)

    def test_ilse_has_reference_then_mention_in_order(self) -> None:
        result = self.service.change_candidates(self.marek)
        ilse_item = next(item for item in result.items if item.id == self.ilse)
        self.assertEqual(
            [(r.route, r.field_id) for r in ilse_item.reasons],
            [("references_source", "father"), ("mentions_source", "")],
        )

    def test_city_guard_echo_rule_suppresses_the_mention(self) -> None:
        """City Guard's `captain` field resolves to Marek's own title, which
        would otherwise self-match as a textual mention — the echo rule must
        suppress it, leaving exactly the one declared reason."""
        result = self.service.change_candidates(self.marek)
        city_guard_item = next(item for item in result.items if item.id == self.city_guard)
        self.assertEqual(
            [(r.route, r.field_id) for r in city_guard_item.reasons],
            [("references_source", "captain")],
        )

    def test_barracks_is_referenced_by_the_source(self) -> None:
        result = self.service.change_candidates(self.marek)
        barracks_item = next(item for item in result.items if item.id == self.barracks)
        self.assertEqual(
            [(r.route, r.field_id) for r in barracks_item.reasons],
            [("referenced_by_source", "posting")],
        )

    def test_ordering_tier_then_title_casefold(self) -> None:
        result = self.service.change_candidates(self.marek)
        tiers = [_TIER_RANK[item.tier] for item in result.items]
        self.assertEqual(tiers, sorted(tiers))
        # Within a tier, titles are casefold-sorted.
        by_tier: dict[str, list[str]] = {}
        for item in result.items:
            by_tier.setdefault(item.tier, []).append(item.title)
        for titles in by_tier.values():
            self.assertEqual(titles, sorted(titles, key=str.casefold))

    # --- with a baseline -------------------------------------------------

    def test_with_baseline_only_rank_is_changed(self) -> None:
        snapshot = self.service.capture_snapshot(
            self.marek, kind=self.service.node_snapshot_kind(self.marek)
        )
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="He has heard whispers of The Deserter's Rumour.",
                entry_type="lore:character",
                metadata={
                    "rank": "Captain",
                    "aliases": ["the Captain"],
                    "posting": self.barracks,
                },
            ),
        )

        before = _hash_tree(self.root)
        result = self.service.change_candidates(self.marek, baseline_snapshot_id=snapshot.id)
        after = _hash_tree(self.root)
        self.assertEqual(before, after)

        self.assertEqual(result.changed_fields, ["rank"])
        self.assertFalse(result.whole_entry)

        by_id = {item.id: item for item in result.items}
        ch5_item = by_id[self.ch5]
        self.assertEqual(ch5_item.tier, "declared")
        self.assertTrue(next(r for r in ch5_item.reasons if r.route == "mutates_source").field_changed)

        ch11_item = by_id[self.ch11]
        self.assertEqual(ch11_item.tier, "marker_untouched")
        self.assertFalse(next(r for r in ch11_item.reasons if r.route == "mutates_source").field_changed)

        # ch11 (marker_untouched) sorts after every declared item and before
        # the mentions.
        order = [item.id for item in result.items]
        self.assertLess(order.index(self.ch5), order.index(self.ch11))
        self.assertLess(order.index(self.ch11), order.index(self.weir_tavern))
        self.assertLess(order.index(self.ch11), order.index(self.ch9))

    def test_two_markers_on_one_field_in_one_scene_are_two_reasons(self) -> None:
        """The marker id is part of a reason's identity: a scene that mutates
        the same field twice lists both markers, in prose order."""
        scene = self._new_scene(
            "Chapter Twelve",
            f"<!-- mutate:entity={self.marek};field=rank;value=Captain;id=m_a --> "
            f"Later. <!-- mutate:entity={self.marek};field=rank;value=Sergeant;id=m_b -->",
        )
        result = self.service.change_candidates(self.marek)
        item = next(item for item in result.items if item.id == scene)
        self.assertEqual(
            [(r.route, r.field_id, r.marker_id) for r in item.reasons],
            [("mutates_source", "rank", "m_a"), ("mutates_source", "rank", "m_b")],
        )

    def test_unknown_baseline_propagates_404(self) -> None:
        with self.assertRaises(Exception) as ctx:
            self.service.change_candidates(self.marek, baseline_snapshot_id="nope")
        self.assertEqual(getattr(ctx.exception, "status_code", None), 404)

    # --- HTTP --------------------------------------------------------------

    def test_http_matches_service_order(self) -> None:
        service_result = self.service.change_candidates(self.marek)
        res = self.client.get(f"/api/lore/{self.marek}/change-candidates")
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual([item["id"] for item in body["items"]], [item.id for item in service_result.items])

    def test_http_with_baseline_query_param(self) -> None:
        snapshot = self.service.capture_snapshot(
            self.marek, kind=self.service.node_snapshot_kind(self.marek)
        )
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="He has heard whispers of The Deserter's Rumour.",
                entry_type="lore:character",
                metadata={
                    "rank": "Captain",
                    "aliases": ["the Captain"],
                    "posting": self.barracks,
                },
            ),
        )
        service_result = self.service.change_candidates(self.marek, baseline_snapshot_id=snapshot.id)
        res = self.client.get(
            f"/api/lore/{self.marek}/change-candidates", params={"baseline": snapshot.id}
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual([item["id"] for item in body["items"]], [item.id for item in service_result.items])
        self.assertEqual(body["changed_fields"], ["rank"])

    def test_http_unknown_lore_id_is_404(self) -> None:
        res = self.client.get("/api/lore/not-a-real-id/change-candidates")
        self.assertEqual(res.status_code, 404, res.text)

    def test_http_scene_id_as_source_is_404(self) -> None:
        res = self.client.get(f"/api/lore/{self.ch2}/change-candidates")
        self.assertEqual(res.status_code, 404, res.text)


_TIER_RANK = {"declared": 0, "marker_untouched": 1, "mention": 2}


if __name__ == "__main__":
    unittest.main()
