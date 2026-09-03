"""Merge as a `merged_into` redirect (ADR-0082 slice 3, §5, #1784).

Merging tag A into tag B records `merged_into: B` on A's own file; the node
index's `NodeIndex.canonical_id` is the one choke point every reference-
lifecycle read (backlinks, `tagged:`, title lookup, dangling-check) resolves
through, so a reference to A reads, filters, groups and counts as B without
any file outside the merge's owned scope being touched. A's file is never
deleted — it is governance data, removed only with its survivor (cascade) or
directly by the author.

`TagMergeHttpTests` covers the single-project surface (merge rules, cascade
delete, candidates exclusion, the lazy on-save rewrite, and that the legacy
`/api/tags*` registry is gone). `TagMergeLayeredTests` walks ADR-0082's
Acceptance steps 4-5 across a series/book chain, mirroring
`test_promote_lore.py`'s fixture.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from layer_fixtures import declare_full_chain
from project_fixtures import open_test_project

from app.main import app
from app.models import CreateTagEntryRequest, SaveSceneRequest, SaveTagEntryRequest
from app.services.project_service import ProjectService


def _add_motifs_field(service: ProjectService, root: Path, entry_type: str = "lore:character") -> None:
    """Give `entry_type` an `entity_ref_list` field over the `tag` kind, the
    same fixture shape `test_tag_entries.py`'s delete-purge test uses."""
    schema_path = root / "metadata.schema.yaml"
    data = service._read_yaml(schema_path)
    data.setdefault("fields", {})["motifs"] = {
        "name": "Motifs",
        "type": "entity_ref_list",
        "picker_config": {"sources": [{"kind": "tag"}]},
    }
    definition = data.setdefault("entry_types", {}).get(entry_type) or {}
    fields = list(definition.get("fields") or [])
    if "motifs" not in fields:
        fields.insert(0, "motifs")
    definition["fields"] = fields
    data["entry_types"][entry_type] = definition
    service._write_yaml(schema_path, data)


class TagMergeHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Tag Merge Tests")
        self.client = TestClient(app)
        _add_motifs_field(self.service, self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create_tag(self, title: str, entry_type: str = "tag:tag") -> str:
        response = self.client.post(
            "/api/tag-entries", json={"title": title, "entry_type": entry_type}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["id"]

    def _write_tag(self, node_id: str, title: str, merged_into: str | None = None) -> Path:
        """Hand-write a tag file directly — the way a genuine `merged_into`
        CYCLE reaches disk (the merge endpoint's own 422s prevent one; only a
        hand edit, or two racing governance actions, can produce it)."""
        path = self.root / "tags" / f"{node_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata: dict = {}
        if merged_into is not None:
            metadata["merged_into"] = merged_into
        self.service._write_markdown_with_front_matter(
            path, {"id": node_id, "title": title, "entry_type": "tag:tag", "metadata": metadata}, ""
        )
        return path

    def _write_lore(self, node_id: str, title: str, motifs: list[str]) -> Path:
        # Filename matches the title, like a save would leave it — a save on
        # this fixture must not ALSO rename the file (`_maybe_rename_node_file`
        # fires whenever the stem doesn't already represent the title), which
        # would otherwise mask the rewrite this test is pinning under an
        # unrelated file move.
        path = self.root / "lore" / f"{title}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            path,
            {
                "id": node_id,
                "title": title,
                "entry_type": "lore:character",
                "metadata": {"motifs": motifs},
            },
            "Body.",
        )
        return path

    # --- merge happy path ---------------------------------------------------

    def test_merge_writes_redirect_and_returns_survivor(self) -> None:
        mirror = self._create_tag("mirror")
        mirrors = self._create_tag("mirrors")
        response = self.client.post(f"/api/tag-entries/{mirror}/merge", json={"into": mirrors})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["id"], mirrors)

        source = self.client.get(f"/api/tag-entries/{mirror}").json()
        self.assertEqual(source["merged_into"], mirrors)

        index = self.service._build_node_index()
        self.assertEqual(index.canonical_id(mirror), mirrors)
        self.assertEqual(index.redirects_to.get(mirrors), [mirror])

    def test_merge_rewrites_owned_scope_references_and_dedupes(self) -> None:
        mirror = self._create_tag("mirror")
        mirrors = self._create_tag("mirrors")
        # Already carries the survivor too — the merge must dedupe, not double it.
        self._write_lore("lore_hero", "Hero", [mirror, mirrors])
        self._write_lore("lore_villain", "Villain", [mirror])

        response = self.client.post(f"/api/tag-entries/{mirror}/merge", json={"into": mirrors})
        self.assertEqual(response.status_code, 200, response.text)

        hero_fm, _ = self.service._read_markdown_with_front_matter(
            self.root / "lore" / "Hero.md", strict=True
        )
        self.assertEqual(hero_fm["metadata"]["motifs"], [mirrors])
        villain_fm, _ = self.service._read_markdown_with_front_matter(
            self.root / "lore" / "Villain.md", strict=True
        )
        self.assertEqual(villain_fm["metadata"]["motifs"], [mirrors])

    def test_redirect_lands_even_when_the_owned_scope_sweep_then_raises(self) -> None:
        """R2: the redirect write (step 1) is what makes the merge correct;
        the reference-rewrite sweep (step 2) is an eager convenience that
        runs AFTER it. If the sweep raises, the redirect from step 1 already
        stands and the error propagates — the merge is not rolled back."""
        mirror = self._create_tag("mirror")
        mirrors = self._create_tag("mirrors")
        self._write_lore("lore_hero", "Hero", [mirror])

        with (
            patch.object(self.service, "_rewrite_references_from_to", side_effect=RuntimeError("boom")),
            self.assertRaises(RuntimeError),
        ):
            self.service.merge_tag_entries(mirror, mirrors)

        # The redirect already landed before the sweep raised — the source
        # reads/resolves as the survivor regardless of the carrier below.
        source = self.client.get(f"/api/tag-entries/{mirror}").json()
        self.assertEqual(source["merged_into"], mirrors)
        index = self.service._build_node_index()
        self.assertEqual(index.canonical_id(mirror), mirrors)

        # The carrier was never reached (the mock raised before doing any
        # work) — still holds the raw source id on disk.
        hero_fm, _ = self.service._read_markdown_with_front_matter(
            self.root / "lore" / "Hero.md", strict=True
        )
        self.assertEqual(hero_fm["metadata"]["motifs"], [mirror])

        # A rerun of the (real, unmocked) sweep both fixes the carrier the
        # first attempt never reached AND is idempotent to call again.
        self.service._rewrite_references_from_to(mirror, mirrors, self.root)
        hero_fm, _ = self.service._read_markdown_with_front_matter(
            self.root / "lore" / "Hero.md", strict=True
        )
        self.assertEqual(hero_fm["metadata"]["motifs"], [mirrors])
        self.service._rewrite_references_from_to(mirror, mirrors, self.root)  # no-op, no error
        hero_fm, _ = self.service._read_markdown_with_front_matter(
            self.root / "lore" / "Hero.md", strict=True
        )
        self.assertEqual(hero_fm["metadata"]["motifs"], [mirrors])

    def test_merge_at_the_machine_layer_skips_the_sweep_by_design(self) -> None:
        """R2: with no project open, `merge_tag_entries` writes the redirect
        but never calls the owned-scope sweep at all (there is no project
        node file to sweep) — correctness still holds through `canonical_id`
        on read, the same as the machine-layer delete purge's own guard."""
        from project_fixtures import clear_test_scope

        clear_test_scope()
        mirror = self._create_tag("mirror", entry_type="tag:assistant_tag")
        mirrors = self._create_tag("mirrors", entry_type="tag:assistant_tag")
        # The HTTP path resolves a FRESH `ProjectService` per request scoped
        # off the wire header (`resolve_current_project`), not `self.service`
        # — patch the class method, not the instance, so it covers whichever
        # object the request actually builds.
        with patch.object(ProjectService, "_rewrite_references_from_to") as sweep:
            response = self.client.post(f"/api/tag-entries/{mirror}/merge", json={"into": mirrors})
        self.assertEqual(response.status_code, 200, response.text)
        sweep.assert_not_called()
        source = self.client.get(f"/api/tag-entries/{mirror}").json()
        self.assertEqual(source["merged_into"], mirrors)

    # --- every 422 rule -------------------------------------------------------

    def test_merge_into_self_is_rejected(self) -> None:
        mirror = self._create_tag("mirror")
        response = self.client.post(f"/api/tag-entries/{mirror}/merge", json={"into": mirror})
        self.assertEqual(response.status_code, 422, response.text)

    def test_merge_unknown_source_is_rejected(self) -> None:
        mirrors = self._create_tag("mirrors")
        response = self.client.post("/api/tag-entries/tag_ghost/merge", json={"into": mirrors})
        self.assertEqual(response.status_code, 422, response.text)

    def test_merge_unknown_target_is_rejected(self) -> None:
        mirror = self._create_tag("mirror")
        response = self.client.post(f"/api/tag-entries/{mirror}/merge", json={"into": "tag_ghost"})
        self.assertEqual(response.status_code, 422, response.text)

    def test_merge_across_vocabularies_is_rejected(self) -> None:
        mirror = self._create_tag("mirror", entry_type="tag:tag")
        assistant_tag = self._create_tag("editor", entry_type="tag:assistant_tag")
        response = self.client.post(
            f"/api/tag-entries/{mirror}/merge", json={"into": assistant_tag}
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_merge_target_already_merged_follows_to_its_survivor(self) -> None:
        """"the target must not itself be merged (follow canonical_id first
        and merge into the survivor)" — not a 422, a silent resolution."""
        a = self._create_tag("a")
        b = self._create_tag("b")
        c = self._create_tag("c")
        self.assertEqual(
            self.client.post(f"/api/tag-entries/{a}/merge", json={"into": b}).status_code, 200
        )
        response = self.client.post(f"/api/tag-entries/{c}/merge", json={"into": a})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["id"], b)
        index = self.service._build_node_index()
        self.assertEqual(index.canonical_id(c), b)

    # --- S6: delete cascades to redirects --------------------------------------

    def test_deleting_the_survivor_removes_its_redirects_and_purges_both(self) -> None:
        mirror = self._create_tag("mirror")
        mirrors = self._create_tag("mirrors")
        self._write_lore("lore_hero", "Hero", [mirrors])
        self.assertEqual(
            self.client.post(f"/api/tag-entries/{mirror}/merge", json={"into": mirrors}).status_code,
            200,
        )

        response = self.client.delete(f"/api/tag-entries/{mirrors}")
        self.assertEqual(response.status_code, 204, response.text)

        self.assertEqual(self.client.get(f"/api/tag-entries/{mirror}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/tag-entries/{mirrors}").status_code, 404)
        hero_fm, _ = self.service._read_markdown_with_front_matter(
            self.root / "lore" / "Hero.md", strict=True
        )
        self.assertNotIn(mirrors, hero_fm["metadata"].get("motifs") or [])

    def test_deleting_a_redirect_directly_is_allowed(self) -> None:
        """"A redirect... may itself be deleted directly (governance)."""
        mirror = self._create_tag("mirror")
        mirrors = self._create_tag("mirrors")
        self.assertEqual(
            self.client.post(f"/api/tag-entries/{mirror}/merge", json={"into": mirrors}).status_code,
            200,
        )
        response = self.client.delete(f"/api/tag-entries/{mirror}")
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(self.client.get(f"/api/tag-entries/{mirrors}").status_code, 200)

    def test_deleting_a_cycle_member_does_not_double_unlink(self) -> None:
        """R1: a hand-edited 2-cycle (a.merged_into=b, b.merged_into=a) has no
        survivor — `_transitive_redirects` must never hand `delete_tag_entry`
        the id it is already deleting back as one of ITS OWN redirects, or the
        second `_delete_node_file` call raises on an already-gone file."""
        self._write_tag("tag_a", "a", merged_into="tag_b")
        self._write_tag("tag_b", "b", merged_into="tag_a")

        response = self.client.delete("/api/tag-entries/tag_a")
        self.assertEqual(response.status_code, 204, response.text)

        # Exactly the two cycle files are gone — `tag_a`'s own delete plus its
        # (one) OTHER redirect `tag_b`, never `tag_a` unlinked a second time.
        self.assertFalse((self.root / "tags" / "tag_a.md").exists())
        self.assertFalse((self.root / "tags" / "tag_b.md").exists())
        self.assertEqual(self.client.get("/api/tag-entries/tag_a").status_code, 404)
        self.assertEqual(self.client.get("/api/tag-entries/tag_b").status_code, 404)

    # --- S7: pickers exclude redirects -----------------------------------------

    def test_reference_candidates_exclude_merged_tags(self) -> None:
        mirror = self._create_tag("mirror")
        mirrors = self._create_tag("mirrors")
        self.assertEqual(
            self.client.post(f"/api/tag-entries/{mirror}/merge", json={"into": mirrors}).status_code,
            200,
        )
        candidates = self.client.get("/api/references/candidates", params={"kind": "tag"}).json()
        ids = [c["id"] for c in candidates["candidates"]]
        self.assertIn(mirrors, ids)
        self.assertNotIn(mirror, ids)

        # The governance list keeps showing it — under "Merged" (F3, frontend).
        listed = self.client.get("/api/tag-entries").json()["tags"]
        self.assertIn(mirror, [t["id"] for t in listed])

    # --- S4: lazy rewrite on save -----------------------------------------------

    def test_saving_a_lore_entry_carrying_a_merged_id_writes_the_survivor(self) -> None:
        mirror = self._create_tag("mirror")
        mirrors = self._create_tag("mirrors")
        self.assertEqual(
            self.client.post(f"/api/tag-entries/{mirror}/merge", json={"into": mirrors}).status_code,
            200,
        )
        self._write_lore("lore_hero", "Hero", [mirror])

        # A save whose client submitted the OLD (merged) id verbatim — the
        # point of the lazy rewrite, not an id the read path already healed.
        response = self.client.put(
            "/api/lore/lore_hero",
            json={"title": "Hero", "entry_type": "lore:character", "body": "Body.", "metadata": {"motifs": [mirror]}},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["metadata"]["motifs"], [mirrors])

        front_matter, _ = self.service._read_markdown_with_front_matter(
            self.root / "lore" / "Hero.md", strict=True
        )
        self.assertEqual(front_matter["metadata"]["motifs"], [mirrors])

    # --- S3: AI-template EntryRef resolves the tag kind, through a redirect --

    def test_entry_ref_resolves_a_merged_tag_id_to_the_survivor(self) -> None:
        """`entry_ref.py`'s missing `"tag"` branch (S3) plus canonicalisation:
        `{{ scene.motifs }}` items must have `.title` / `.metadata.color`, and
        a merged id must resolve to the survivor's, not its own."""
        from app.services.ai.entry_ref import EntryRef

        mirror = self._create_tag("mirror")
        mirrors_id = self._create_tag("mirrors")
        self.assertEqual(
            self.client.put(
                f"/api/tag-entries/{mirrors_id}", json={"title": "mirrors", "entry_type": "tag:tag", "metadata": {"color": "amber"}}
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(f"/api/tag-entries/{mirror}/merge", json={"into": mirrors_id}).status_code,
            200,
        )
        schema = self.service.read_metadata_schema()
        ref = EntryRef(self.service, schema, mirror)
        self.assertEqual(ref.title, "mirrors")
        self.assertEqual(ref.metadata.get("color"), "amber")

    # --- legacy registry retired --------------------------------------------

    def test_legacy_tags_registry_routes_are_gone(self) -> None:
        for method, path in [
            ("GET", "/api/tags"),
            ("GET", "/api/tags/overview"),
            ("PUT", "/api/tags/scope"),
            ("PUT", "/api/tags/color"),
            ("POST", "/api/tags/merge"),
        ]:
            response = self.client.request(method, path, json={})
            # No `/api/tags*` route is registered any more, so the request falls
            # through to the SPA catch-all mount (`main.py`, only present when
            # `frontend/dist` exists) — 404 (no such static file) for GET, 405
            # (the mount only serves GET/HEAD) for PUT/POST. Either is proof
            # there is no live handler; a real backend route would be a 2xx/4xx
            # from THIS app's own logic, never a static-file verdict.
            self.assertIn(
                response.status_code, (404, 405), f"{method} {path}: {response.text}"
            )


class TagMergeLayeredTests(unittest.TestCase):
    """ADR-0082 Acceptance steps 4-5 across a series/book chain, mirroring
    `test_promote_lore.py`'s fixture: `writing (base) -> honorverse (series)
    -> book01 (root)`."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.series = self.base / "honorverse"
        self.root = self.series / "book01"
        self.book_service = ProjectService.created_at(self.root, "Book 1")
        self.config_dir = Path(self.temp_dir.name).resolve() / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        declare_full_chain(self.book_service, self.root, self.base)
        self.series_service = ProjectService.opened_at(self.series)
        _add_motifs_field(self.series_service, self.series)

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_rename_at_series_is_visible_from_the_book_without_touching_book_files(self) -> None:
        # Step 4: a title edit at the series is visible from the book.
        tag = self.series_service.create_tag_entry(
            CreateTagEntryRequest(title="doubling", entry_type="tag:tag")
        )
        self.series_service.save_tag_entry(
            tag.id, SaveTagEntryRequest(title="doubles", entry_type="tag:tag", metadata={})
        )
        book_index = self.book_service._build_node_index()
        self.assertEqual(book_index.by_id[tag.id].title, "doubles")

    def test_merge_at_series_reads_and_filters_as_survivor_from_the_book(self) -> None:
        # Step 5: merge owned by the series; a book carrier is untouched on
        # disk until its own next save, but already reads/filters/counts as
        # the survivor.
        mirror = self.series_service.create_tag_entry(
            CreateTagEntryRequest(title="mirror", entry_type="tag:tag")
        )
        mirrors = self.series_service.create_tag_entry(
            CreateTagEntryRequest(title="mirrors", entry_type="tag:tag")
        )
        # Filename matches the title, like a save would leave it — the later
        # `save_scene` call must not ALSO rename the file, which would mask
        # the rewrite this test is pinning under an unrelated file move.
        book_scene_path = self.root / "scenes" / "Carrier.md"
        book_scene_path.parent.mkdir(parents=True, exist_ok=True)
        # The scene carries the merged tag id through the general `tags` field
        # (present on every entry type) rather than the book-only `motifs`
        # field the series doesn't need to know about.
        self.book_service._write_markdown_with_front_matter(
            book_scene_path,
            {
                "id": "scene_carrier",
                "title": "Carrier",
                "entry_type": "manuscript:scene",
                "status": "draft",
                "metadata": {"tags": [mirror.id]},
            },
            "Body.",
        )
        before_mtime = book_scene_path.stat().st_mtime_ns

        merged = self.series_service.merge_tag_entries(mirror.id, mirrors.id)
        self.assertEqual(merged.id, mirrors.id)

        # The book file was never touched by the series-owned merge.
        self.assertEqual(book_scene_path.stat().st_mtime_ns, before_mtime)

        book_service = ProjectService.opened_at(self.root)
        scene = book_service.read_scene("scene_carrier")
        self.assertEqual(scene.metadata["tags"], [mirrors.id])

        book_index = book_service._build_node_index()
        backlink_ids = {edge.src for edge in book_index.edges_by_dst.get(mirrors.id, [])}
        self.assertIn("scene_carrier", backlink_ids)
        self.assertEqual(book_index.edges_by_dst.get(mirror.id, []), [])

        # The next save writes the survivor's id to disk.
        book_service.save_scene(
            "scene_carrier",
            SaveSceneRequest(
                title="Carrier",
                body="Body.",
                status="draft",
                entry_type="manuscript:scene",
                metadata={"tags": [mirror.id]},
            ),
        )
        front_matter, _ = book_service._read_markdown_with_front_matter(book_scene_path, strict=True)
        self.assertEqual(front_matter["metadata"]["tags"], [mirrors.id])

        # Deleting the survivor at the series removes the redirect with it.
        self.series_service.delete_tag_entry(mirrors.id)
        self.assertIsNone(
            self.series_service._build_node_index().by_id.get(mirror.id)
        )

    def test_promotion_partition_canonicalises_before_the_visibility_test(self) -> None:
        """`_partition_entity_ref_list` (ADR-0082 §5): a value naming a merged
        tag's id travels/stays as the SURVIVOR, not the tag it redirects away
        from."""
        mirror = self.series_service.create_tag_entry(
            CreateTagEntryRequest(title="mirror", entry_type="tag:tag")
        )
        mirrors = self.series_service.create_tag_entry(
            CreateTagEntryRequest(title="mirrors", entry_type="tag:tag")
        )
        self.series_service.merge_tag_entries(mirror.id, mirrors.id)

        index = self.book_service._build_node_index()
        layers = self.book_service.collect_layers(self.root, include_machine=True, include_library=True)
        series_layer = next(layer for layer in layers if layer.folder == self.series)

        travel_value, stay_value, stay_item = self.book_service._partition_entity_ref_list(
            index, self.root, series_layer, "motifs", [mirror.id]
        )
        self.assertEqual(travel_value, [mirrors.id])
        self.assertIsNone(stay_item)


if __name__ == "__main__":
    unittest.main()
