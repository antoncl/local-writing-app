"""ADR-0090 §2 / ADR-0091 §2 (#2115, #2131-#2135): the candidate set for a
settled change to one lore entry — five named routes (references,
referenced-by, mutates, mentions in, mentions out), each a reason a
dependent node might need a look. Read-only: no candidate call may write
anything, so a hash sweep of the project files brackets every assertion
group.
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from layer_fixtures import declare_full_chain
from project_fixtures import open_test_project

from app.main import app
from app.models import (
    CreateLoreEntryRequest,
    CreateSceneRequest,
    MetadataFieldDefinition,
    PropagateRequest,
    SaveLoreEntryRequest,
    SaveSceneRequest,
    UpsertMetadataFieldRequest,
)
from app.scope import WorkScope
from app.services.project.node_index_gate import node_index_gate
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
        # source — ADR-0091 §2 counts it as `mentioned_by_source`.
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
            {
                self.city_guard,
                self.ilse,
                self.barracks,
                self.ch5,
                self.ch11,
                self.weir_tavern,
                self.ch9,
                self.rumour,
            },
        )
        self.assertNotIn(self.marek, present)
        self.assertNotIn(self.ch2, present)

        by_id = {item.id: item for item in result.items}
        for declared_id in (self.city_guard, self.ilse, self.barracks, self.ch5, self.ch11):
            self.assertEqual(by_id[declared_id].tier, "declared", declared_id)
        self.assertEqual(by_id[self.weir_tavern].tier, "mention")
        self.assertEqual(by_id[self.ch9].tier, "mention")
        self.assertEqual(by_id[self.rumour].tier, "mention")
        self.assertEqual(
            [(r.route, r.field_id) for r in by_id[self.rumour].reasons],
            [("mentioned_by_source", "")],
        )
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

    def test_layers_is_one_entry_for_a_non_layered_project(self) -> None:
        """Amendment 3: a project with no ancestor chain has exactly one
        composing file — the owning file itself."""
        snapshot = self.service.capture_snapshot(
            self.marek, kind=self.service.node_snapshot_kind(self.marek)
        )
        result = self.service.change_candidates(self.marek, baseline_snapshot_id=snapshot.id)
        self.assertEqual(len(result.layers), 1)
        layer = result.layers[0]
        self.assertFalse(layer.is_override)
        self.assertEqual(layer.baseline_snapshot_id, snapshot.id)
        self.assertEqual(layer.changed_fields, result.changed_fields)
        self.assertFalse(layer.whole)

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

    def test_mention_inside_a_long_text_field_counts(self) -> None:
        """The corpus scan covers prose fields, not just the body: a character
        whose `backstory` names the source is a mention candidate, while a
        reference field's resolved title (City Guard's `captain`) is not."""
        _define_field(self.service, "backstory", "long_text", "Backstory")
        hollis = self._make_lore(
            "Hollis Brand", body="", metadata={"backstory": "He served under the Captain at the gate."}
        )
        result = self.service.change_candidates(self.marek)
        by_id = {item.id: item for item in result.items}
        self.assertEqual(by_id[hollis].tier, "mention")
        self.assertEqual([r.route for r in by_id[hollis].reasons], ["mentions_source"])
        self.assertEqual([r.route for r in by_id[self.city_guard].reasons], ["references_source"])

    def test_inbound_mention_in_underscore_italics_is_found(self) -> None:
        """#2142: a candidate's prose naming the source in markdown italics
        (`_Marek Vell_`) must still be found — the underscore delimiters
        would otherwise leave the matcher with no boundary either side of
        the name. A new lore entry, not the shared `weir_tavern` fixture, so
        the shared fixture's un-italicised assertions elsewhere stay intact."""
        tavern = self._make_lore("Quiet Tavern", body="_Marek Vell_ used to drink here.")
        result = self.service.change_candidates(self.marek)
        by_id = {item.id: item for item in result.items}
        self.assertEqual([r.route for r in by_id[tavern].reasons], ["mentions_source"])

    # --- outbound mentions (ADR-0091 §2, `mentioned_by_source`) ------------

    def test_outbound_mention_from_a_long_text_field_of_the_source(self) -> None:
        """The source's own `long_text` field, not just its body, is scanned
        for other entries' names in the outbound direction."""
        _define_field(self.service, "backstory", "long_text", "Backstory")
        hollis = self._make_lore("Hollis Brand", body="")
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
                    "backstory": "He trained under Hollis Brand at the academy.",
                },
            ),
        )
        result = self.service.change_candidates(self.marek)
        by_id = {item.id: item for item in result.items}
        self.assertEqual([r.route for r in by_id[hollis].reasons], ["mentioned_by_source"])

    def test_outbound_mention_in_underscore_italics_is_found(self) -> None:
        """#2142 outbound direction: the source's own prose naming a
        candidate in markdown italics (`_Hollis Brand_`)."""
        hollis = self._make_lore("Hollis Brand", body="")
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="He trained under _Hollis Brand_ at the academy.",
                entry_type="lore:character",
                metadata={"rank": "Lieutenant", "aliases": ["the Captain"], "posting": self.barracks},
            ),
        )
        result = self.service.change_candidates(self.marek)
        by_id = {item.id: item for item in result.items}
        self.assertEqual([r.route for r in by_id[hollis].reasons], ["mentioned_by_source"])

    def test_outbound_echo_rule_barracks_stays_declared_only(self) -> None:
        """The Barracks is found by `referenced_by_source` (`posting`)
        alone: the source's `posting` field resolves to "Watch Barracks" in
        the corpus, but that resolved title is never scanned as an OUTBOUND
        mention either — the echo rule is a property of what is scanned
        (prose only), shared by both directions (ADR-0091 §2)."""
        result = self.service.change_candidates(self.marek)
        barracks_item = next(item for item in result.items if item.id == self.barracks)
        self.assertEqual(
            [(r.route, r.field_id) for r in barracks_item.reasons],
            [("referenced_by_source", "posting")],
        )

    def test_outbound_matches_an_alias(self) -> None:
        """The outbound matcher is built from every candidate's aliases too,
        not just its title."""
        outpost = self._make_lore("Old Watchpost", body="", metadata={"aliases": ["the Ruins"]})
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="He grew up near the Ruins.",
                entry_type="lore:character",
                metadata={"rank": "Lieutenant", "aliases": ["the Captain"], "posting": self.barracks},
            ),
        )
        result = self.service.change_candidates(self.marek)
        by_id = {item.id: item for item in result.items}
        self.assertEqual([r.route for r in by_id[outpost].reasons], ["mentioned_by_source"])

    def test_outbound_shared_alias_finds_both_entries(self) -> None:
        """A name two entries share fans out to every id behind it — the
        matcher itself dedups a name to one id, so the outbound resolver
        must expand the synthetic hit back to every real entry."""
        first = self._make_lore("Entry A", body="", metadata={"aliases": ["the Wanderer"]})
        second = self._make_lore("Entry B", body="", metadata={"aliases": ["the Wanderer"]})
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="He once met the Wanderer on the road.",
                entry_type="lore:character",
                metadata={"rank": "Lieutenant", "aliases": ["the Captain"], "posting": self.barracks},
            ),
        )
        result = self.service.change_candidates(self.marek)
        by_id = {item.id: item for item in result.items}
        self.assertEqual([r.route for r in by_id[first].reasons], ["mentioned_by_source"])
        self.assertEqual([r.route for r in by_id[second].reasons], ["mentioned_by_source"])

    def test_both_directions_present_keep_shipped_route_order(self) -> None:
        """`references_source, mentions_source, mentioned_by_source` — the
        shipped within-candidate order (declared, marker, mention in, out),
        unchanged by S1's new route landing last. Ilse already references
        Marek (`father`) and mentions him (`the captain`); Marek's body is
        edited here to also name Ilse — the outbound direction."""
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="He has heard whispers of The Deserter's Rumour, and often thinks of Ilse.",
                entry_type="lore:character",
                metadata={"rank": "Lieutenant", "aliases": ["the Captain"], "posting": self.barracks},
            ),
        )
        result = self.service.change_candidates(self.marek)
        ilse_item = next(item for item in result.items if item.id == self.ilse)
        self.assertEqual(
            [r.route for r in ilse_item.reasons],
            ["references_source", "mentions_source", "mentioned_by_source"],
        )

    def test_scene_title_in_source_body_is_not_an_outbound_candidate(self) -> None:
        """The outbound matcher is built from lore entries only (ADR-0091
        §2) — a scene's title appearing in the source's prose adds no
        `mentioned_by_source` reason, even though the scene is already a
        candidate by another route."""
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="He has heard whispers of The Deserter's Rumour, set during Chapter Five.",
                entry_type="lore:character",
                metadata={"rank": "Lieutenant", "aliases": ["the Captain"], "posting": self.barracks},
            ),
        )
        result = self.service.change_candidates(self.marek)
        ch5_item = next(item for item in result.items if item.id == self.ch5)
        self.assertNotIn("mentioned_by_source", [r.route for r in ch5_item.reasons])

    def test_context_policy_never_entry_is_still_found_both_directions(self) -> None:
        """ADR-0091 §2: no `context_policy` filter applies in either mention
        direction — a `never` entry is still a dependent."""
        hidden = self._make_lore(
            "Hidden Contact",
            body="Marek Vell owes him a debt.",
            metadata={"context_policy": "never"},
        )
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body=(
                    "He has heard whispers of The Deserter's Rumour, and remembers "
                    "Hidden Contact fondly."
                ),
                entry_type="lore:character",
                metadata={"rank": "Lieutenant", "aliases": ["the Captain"], "posting": self.barracks},
            ),
        )
        result = self.service.change_candidates(self.marek)
        by_id = {item.id: item for item in result.items}
        self.assertEqual(
            sorted(r.route for r in by_id[hidden].reasons),
            sorted(["mentions_source", "mentioned_by_source"]),
        )

    def test_story_time_names_from_markers_widen_the_mention_scan(self) -> None:
        """ADR-0008: a marker on `title` or `aliases` gives the source a name
        the later prose uses; the scan must know it."""
        renamed = self._new_scene(
            "Chapter Twenty",
            f"<!-- mutate:entity={self.marek};field=title;value=The%20Wolf;id=m_title -->",
        )
        later = self._new_scene("Chapter Twenty-One", "Nobody spoke to the Wolf that night.")
        result = self.service.change_candidates(self.marek)
        by_id = {item.id: item for item in result.items}
        self.assertEqual([r.route for r in by_id[renamed].reasons], ["mutates_source"])
        self.assertEqual([r.route for r in by_id[later].reasons], ["mentions_source"])

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


class LayeredBaselineTests(unittest.TestCase):
    """A snapshot photographs ONE layer's file (ADR-0087), so the baseline diff
    must read that file back — never the folded composite, which would report
    a book override as a change the series file never made."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.series = self.base / "series"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)
        self.service._write_yaml(
            self.base / "metadata.schema.yaml",
            {
                "version": 1,
                "fields": {
                    "rank": {"name": "rank", "type": "text", "label": "Rank"},
                },
                "entry_types": {"lore:character": {"fields": ["rank"]}},
            },
        )
        series_writer = ProjectService(WorkScope(root=self.series))
        declare_full_chain(series_writer, self.series, self.base)
        self.marek = series_writer.create_lore_entry(
            CreateLoreEntryRequest(title="Marek Vell", entry_type="lore:character")
        ).id
        series_writer.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell", body="Keeper of the gate.", entry_type="lore:character", metadata={"rank": "Captain"}
            ),
        )
        layers = self.service.collect_layers(self.root)
        self.series_id = next(layer.id for layer in layers if layer.folder == self.series)
        self.book_id = next(layer.id for layer in layers if layer.folder == self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _new_scene(self, title: str, body: str) -> str:
        """A book-scoped scene, created directly through the book-level
        service — scenes are never inherited (ADR-0039/0040), so this always
        writes at `self.root`."""
        scene = self.service.create_scene(CreateSceneRequest(title=title))
        self.service.save_scene(scene.id, SaveSceneRequest(title=title, body=body))
        return scene.id

    def test_book_override_is_not_a_change_of_the_series_file(self) -> None:
        # The book overrides rank (an explicit write target below the owning
        # layer = a sparse override delta); the series file still says Captain.
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Sergeant"},
                authoring_layer_id=self.book_id,
            ),
        )
        kind = self.service.node_snapshot_kind(self.marek)
        # The book's own lane gets a baseline too — as a real Propagate
        # confirm would (Amendment 3 §3) — so its later diff measures the
        # override against ITS OWN prior state, not "no baseline yet".
        # Captured BEFORE the owning snapshot (ADR-0091 §1: a confirm
        # captures delta lanes first, the owner last), so the owning
        # snapshot's "since" still resolves this delta lane at-or-before it.
        self.service.capture_snapshot(
            self.marek, kind=kind, layer_id=self.book_id, origin="propagation"
        )
        snapshot = self.service.capture_snapshot(self.marek, kind=kind)
        # Change only the series body, at the series layer.
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate, eleven years.",
                entry_type="lore:character",
                metadata={"rank": "Captain"},
                authoring_layer_id=self.series_id,
            ),
        )
        result = self.service.change_candidates(self.marek, baseline_snapshot_id=snapshot.id)
        self.assertEqual(result.changed_fields, [])
        self.assertTrue(result.body_changed)

        # Amendment 3: the composing set is the series file plus the book's
        # override delta, each its own lane. The book's lane is unchanged
        # since its own baseline, so it reports nothing and `whole=False`.
        self.assertEqual(len(result.layers), 2)
        by_layer = {layer.layer_id: layer for layer in result.layers}
        self.assertEqual(set(by_layer), {self.series_id, self.book_id})
        self.assertFalse(by_layer[self.series_id].is_override)
        self.assertTrue(by_layer[self.book_id].is_override)
        self.assertFalse(by_layer[self.book_id].whole)
        self.assertEqual(by_layer[self.book_id].changed_fields, [])

    def test_book_override_ranks_declared_and_widens_changed_fields(self) -> None:
        """The #2121 case: a book-layer override on an inherited field IS a
        change, measured in its own lane — not a no-op read off the
        unaffected series file. A marker on the overridden field ranks
        `declared`, changed."""
        kind = self.service.node_snapshot_kind(self.marek)
        baseline = self.service.capture_snapshot(self.marek, kind=kind)
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Sergeant"},
                authoring_layer_id=self.book_id,
            ),
        )
        ch5 = self._new_scene(
            "Chapter Five",
            f"<!-- mutate:entity={self.marek};field=rank;value=Sergeant;id=m_rank -->",
        )

        result = self.service.change_candidates(self.marek, baseline_snapshot_id=baseline.id)
        self.assertEqual(result.changed_fields, ["rank"])
        self.assertFalse(result.whole_entry)

        by_layer = {layer.layer_id: layer for layer in result.layers}
        book_layer = by_layer[self.book_id]
        self.assertTrue(book_layer.is_override)
        self.assertTrue(book_layer.whole)
        self.assertEqual(book_layer.changed_fields, ["rank"])
        self.assertEqual(by_layer[self.series_id].changed_fields, [])

        ch5_item = next(item for item in result.items if item.id == ch5)
        self.assertEqual(ch5_item.tier, "declared")
        reason = next(r for r in ch5_item.reasons if r.route == "mutates_source")
        self.assertTrue(reason.field_changed)

    def test_delta_edit_measures_against_its_own_lane_baseline(self) -> None:
        """Once the book's lane has its own propagation baseline, a later
        override edit changes only that lane's field."""
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Sergeant"},
                authoring_layer_id=self.book_id,
            ),
        )
        kind = self.service.node_snapshot_kind(self.marek)
        # Delta lane captured BEFORE the owner (ADR-0091 §1's confirm order),
        # so the owning baseline's "since" resolves it at-or-before.
        self.service.capture_snapshot(
            self.marek, kind=kind, layer_id=self.book_id, origin="propagation"
        )
        owning_baseline = self.service.capture_snapshot(self.marek, kind=kind)
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Major"},
                authoring_layer_id=self.book_id,
            ),
        )
        result = self.service.change_candidates(self.marek, baseline_snapshot_id=owning_baseline.id)
        self.assertEqual(result.changed_fields, ["rank"])
        by_layer = {layer.layer_id: layer for layer in result.layers}
        self.assertFalse(by_layer[self.book_id].whole)
        self.assertEqual(by_layer[self.book_id].changed_fields, ["rank"])

    def test_a_delta_at_an_intermediate_layer_composes_the_source(self) -> None:
        """Owner at the base, delta at the series, opened from the book: the
        series delta lies strictly between owner and open layer and must be
        in the composing set (`owner < rank <= open`) — the filter the
        full-walk rank lookup exists for."""
        base_writer = ProjectService(WorkScope(root=self.base))
        declare_full_chain(base_writer, self.base, self.base)
        hollis = base_writer.create_lore_entry(
            CreateLoreEntryRequest(title="Hollis Brand", entry_type="lore:character")
        ).id
        base_writer.save_lore_entry(
            hollis,
            SaveLoreEntryRequest(
                title="Hollis Brand", body="Quartermaster.", entry_type="lore:character", metadata={"rank": "Corporal"}
            ),
        )
        kind = self.service.node_snapshot_kind(hollis)
        baseline = self.service.capture_snapshot(hollis, kind=kind)
        # A series-layer override, written from the open book with an explicit
        # authoring layer between the owner and the book.
        self.service.save_lore_entry(
            hollis,
            SaveLoreEntryRequest(
                title="Hollis Brand",
                body="Quartermaster.",
                entry_type="lore:character",
                metadata={"rank": "Sergeant"},
                authoring_layer_id=self.series_id,
            ),
        )

        result = self.service.change_candidates(hollis, baseline_snapshot_id=baseline.id)
        self.assertEqual(result.changed_fields, ["rank"])
        by_layer = {layer.layer_id: layer for layer in result.layers}
        self.assertNotIn(self.book_id, by_layer)  # the book holds no delta
        series_layer = by_layer[self.series_id]
        self.assertTrue(series_layer.is_override)
        self.assertTrue(series_layer.whole)
        self.assertEqual(series_layer.changed_fields, ["rank"])
        owner_layer = next(layer for layer in result.layers if not layer.is_override)
        self.assertEqual(owner_layer.changed_fields, [])

    def test_a_removed_delta_is_a_change_of_its_fields(self) -> None:
        """Amendment 3's mirror case: a delta that composed the source at the
        last propagation and has since been removed makes its fields fall
        back to the layer above — a change, read from the lane's baseline
        rows, although no delta file exists any more."""
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Sergeant"},
                authoring_layer_id=self.book_id,
            ),
        )
        kind = self.service.node_snapshot_kind(self.marek)
        # Delta lane captured BEFORE the owner (ADR-0091 §1's confirm order),
        # so the owning baseline's "since" resolves it at-or-before.
        self.service.capture_snapshot(
            self.marek, kind=kind, layer_id=self.book_id, origin="propagation"
        )
        owning_baseline = self.service.capture_snapshot(self.marek, kind=kind)
        self.service._drop_layer_overrides_for_target(self.root, self.marek)
        node_index_gate.invalidate()

        result = self.service.change_candidates(self.marek, baseline_snapshot_id=owning_baseline.id)
        self.assertEqual(result.changed_fields, ["rank"])
        by_layer = {layer.layer_id: layer for layer in result.layers}
        book_layer = by_layer[self.book_id]
        self.assertTrue(book_layer.is_override)
        self.assertFalse(book_layer.whole)
        self.assertEqual(book_layer.changed_fields, ["rank"])
        self.assertEqual(by_layer[self.series_id].changed_fields, [])

    def test_series_body_edit_after_layered_baselines_leaves_rank_untouched(self) -> None:
        """With both lanes freshly baselined, editing only the series body
        reports the body alone — the untouched override lane contributes
        nothing."""
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Sergeant"},
                authoring_layer_id=self.book_id,
            ),
        )
        kind = self.service.node_snapshot_kind(self.marek)
        # Delta lane captured BEFORE the owner (ADR-0091 §1's confirm order),
        # so the owning baseline's "since" resolves it at-or-before.
        self.service.capture_snapshot(
            self.marek, kind=kind, layer_id=self.book_id, origin="propagation"
        )
        owning_baseline = self.service.capture_snapshot(self.marek, kind=kind)
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate, eleven years.",
                entry_type="lore:character",
                metadata={"rank": "Captain"},
                authoring_layer_id=self.series_id,
            ),
        )
        result = self.service.change_candidates(self.marek, baseline_snapshot_id=owning_baseline.id)
        self.assertNotIn("rank", result.changed_fields)
        self.assertTrue(result.body_changed)
        by_layer = {layer.layer_id: layer for layer in result.layers}
        self.assertFalse(by_layer[self.book_id].whole)
        self.assertEqual(by_layer[self.book_id].changed_fields, [])

    # --- ADR-0091 §1's "since" rule (#2131) ---------------------------------

    def test_since_resolves_each_lane_at_or_before(self) -> None:
        """Each lane's own baseline follows the CHOSEN "since", not
        "whichever is newest overall": an older "since" resolves the book
        lane to its own earlier delta baseline and measures from it, a newer
        "since" to its later one."""
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Sergeant"},
                authoring_layer_id=self.book_id,
            ),
        )
        ch5 = self._new_scene(
            "Chapter Five",
            f"<!-- mutate:entity={self.marek};field=rank;value=Sergeant;id=m_rank -->",
        )
        first = self.service.propagate_change(self.marek, PropagateRequest(kept=[ch5]))
        b1, d1 = first.snapshot, first.layer_snapshots[0]

        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Major"},
                authoring_layer_id=self.book_id,
            ),
        )
        second = self.service.propagate_change(self.marek, PropagateRequest(kept=[ch5]))
        b2, d2 = second.snapshot, second.layer_snapshots[0]

        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Corporal"},
                authoring_layer_id=self.book_id,
            ),
        )

        at_b1 = self.service.change_candidates(self.marek, baseline_snapshot_id=b1.id)
        book_at_b1 = next(layer for layer in at_b1.layers if layer.layer_id == self.book_id)
        self.assertEqual(book_at_b1.baseline_snapshot_id, d1.id)
        self.assertEqual(book_at_b1.changed_fields, ["rank"])

        at_b2 = self.service.change_candidates(self.marek, baseline_snapshot_id=b2.id)
        book_at_b2 = next(layer for layer in at_b2.layers if layer.layer_id == self.book_id)
        self.assertEqual(book_at_b2.baseline_snapshot_id, d2.id)
        self.assertEqual(book_at_b2.changed_fields, ["rank"])

    def test_since_older_than_the_delta_counts_it_whole(self) -> None:
        """A "since" older than the delta's own baseline — an owning
        snapshot captured before the override, or the delta, existed —
        treats the lane as never-baselined: the delta counts whole, not
        measured against a baseline it postdates."""
        kind = self.service.node_snapshot_kind(self.marek)
        before_override = self.service.capture_snapshot(self.marek, kind=kind)
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Sergeant"},
                authoring_layer_id=self.book_id,
            ),
        )
        ch5 = self._new_scene(
            "Chapter Five",
            f"<!-- mutate:entity={self.marek};field=rank;value=Sergeant;id=m_rank -->",
        )
        # A confirm gives the book lane its own baseline — but it is CAPTURED
        # after `before_override`, so it must not be found from that "since".
        self.service.propagate_change(self.marek, PropagateRequest(kept=[ch5]))

        result = self.service.change_candidates(self.marek, baseline_snapshot_id=before_override.id)
        by_layer = {layer.layer_id: layer for layer in result.layers}
        book_layer = by_layer[self.book_id]
        self.assertTrue(book_layer.whole)
        self.assertEqual(book_layer.baseline_snapshot_id, "")
        self.assertEqual(book_layer.changed_fields, ["rank"])

    def test_a_plain_camera_capture_on_the_delta_lane_is_a_baseline(self) -> None:
        """`newest_snapshot_at_or_before` takes ANY origin — a writer's own
        plain camera press on the override delta counts as a baseline just
        the same as a propagation snapshot."""
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Sergeant"},
                authoring_layer_id=self.book_id,
            ),
        )
        kind = self.service.node_snapshot_kind(self.marek)
        # A plain camera capture on the delta lane — no origin at all.
        self.service.capture_snapshot(self.marek, kind=kind, layer_id=self.book_id)
        owning_baseline = self.service.capture_snapshot(self.marek, kind=kind)
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Major"},
                authoring_layer_id=self.book_id,
            ),
        )
        result = self.service.change_candidates(self.marek, baseline_snapshot_id=owning_baseline.id)
        by_layer = {layer.layer_id: layer for layer in result.layers}
        book_layer = by_layer[self.book_id]
        self.assertFalse(book_layer.whole)
        self.assertEqual(book_layer.changed_fields, ["rank"])

    def test_removed_delta_lane_follows_since(self) -> None:
        """A removed delta lane's baseline is resolved by the same "since"
        rule: a since chosen before the delta ever had a baseline finds
        nothing, and a lane that did not exist at the since and does not
        exist now is not a change at all — the lane is skipped entirely."""
        self.service.save_lore_entry(
            self.marek,
            SaveLoreEntryRequest(
                title="Marek Vell",
                body="Keeper of the gate.",
                entry_type="lore:character",
                metadata={"rank": "Sergeant"},
                authoring_layer_id=self.book_id,
            ),
        )
        kind = self.service.node_snapshot_kind(self.marek)
        before_delta_baseline = self.service.capture_snapshot(self.marek, kind=kind)
        self.service.capture_snapshot(
            self.marek, kind=kind, layer_id=self.book_id, origin="propagation"
        )
        self.service._drop_layer_overrides_for_target(self.root, self.marek)
        node_index_gate.invalidate()

        result = self.service.change_candidates(
            self.marek, baseline_snapshot_id=before_delta_baseline.id
        )
        by_layer = {layer.layer_id: layer for layer in result.layers}
        self.assertNotIn(self.book_id, by_layer)


if __name__ == "__main__":
    unittest.main()
