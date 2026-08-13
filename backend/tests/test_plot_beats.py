"""Backend tests for the `plot` kind's beat-bearing nodes (ADR-0048 S7; ADR-0053).

The template / plotline-instantiation / beat-identity suites, split out of
`test_plot.py` (which keeps plotline, card, board, and layered-inheritance
coverage). `plot:template` is the ADR-0049 Library's second tenant (S4b); a
plotline is a plot-template instance (ADR-0053 §1) — instantiating a template
snapshots its beats into a book-local `plot:plotline` (Slice 2, #776) — and beat
identity (Slice 3a, #779) is the stable per-beat `id` the card->beat links of
Slice 3b point at.
"""

from __future__ import annotations

from pathlib import Path

from plot_fixtures import PlotTestCase

from app.models import (
    MetadataFieldDefinition,
    UpsertMetadataFieldRequest,
)

_THREE_ACT = "builtin-plot-three-act-story-arc"
# The shipped node file behind _THREE_ACT — read to prove a refused write left it
# byte-untouched (backend/app/builtin_library/plot/, relative to backend/tests/).
_BUILTIN_THREE_ACT = Path(__file__).resolve().parents[1] / "app" / "builtin_library" / "plot" / "three-act-story-arc.md"


class PlotTemplateLibraryTests(PlotTestCase):
    """`plot:template` is the ADR-0049 Library's second tenant (ADR-0048 S4b).

    The 14 diagnostic templates ship as read-only ancestor nodes; a writer clones
    one into the project (a new id, editable) to adapt it. Read-only-in-place and
    clone are the shared Library-tenant surface, proven here for a non-prompt kind.
    """

    def test_ships_fourteen_readonly_library_templates(self) -> None:
        listing = self.client.get("/api/plot/templates")
        self.assertEqual(listing.status_code, 200, listing.text)
        entries = listing.json()["entries"]
        self.assertEqual(len(entries), 14)
        # Every shipped template is inherited from the Library: read-only, flagged.
        self.assertTrue(all(e["is_library"] for e in entries))
        self.assertTrue(all(e["editable"] is False for e in entries))
        self.assertIn(_THREE_ACT, [e["id"] for e in entries])

    def test_read_round_trips_the_spec_and_guide(self) -> None:
        got = self.client.get(f"/api/plot/templates/{_THREE_ACT}")
        self.assertEqual(got.status_code, 200, got.text)
        body = got.json()
        self.assertEqual(body["entry_type"], "plot:template")
        self.assertFalse(body["editable"])
        self.assertEqual(body["template"]["family"], "act")
        # The beat roster is now the `beats` ordered-list metadata field (#736),
        # not the opaque `template:` block — it heals + validates on read.
        beats = body["metadata"]["beats"]
        self.assertEqual(len(beats), 7)
        self.assertEqual(beats[0]["id"], "setup_pressure")
        self.assertEqual(beats[0]["title"], "Setup pressure")
        self.assertIn("Establishes", beats[0]["function"])
        # The prose guide is the node body.
        self.assertIn("# Three-Act Story Arc", body["body"])

    def test_saving_an_inherited_template_is_refused(self) -> None:
        before = _BUILTIN_THREE_ACT.read_bytes()
        refused = self.client.put(
            f"/api/plot/templates/{_THREE_ACT}",
            json={"title": "Hijacked", "body": "", "template": {}},
        )
        self.assertEqual(refused.status_code, 409, refused.text)
        # The 409 must precede any write: the shipped file is byte-untouched.
        self.assertEqual(_BUILTIN_THREE_ACT.read_bytes(), before)
        self.assertNotIn(b"Hijacked", before)
        # And a re-read still shows the original.
        self.assertEqual(self.client.get(f"/api/plot/templates/{_THREE_ACT}").json()["title"], "Three-Act Story Arc")

    def test_deleting_an_inherited_template_is_refused(self) -> None:
        refused = self.client.delete(f"/api/plot/templates/{_THREE_ACT}")
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertEqual(self.client.get(f"/api/plot/templates/{_THREE_ACT}").status_code, 200)

    def test_fork_mints_an_owned_editable_copy(self) -> None:
        forked = self.client.post(f"/api/plot/templates/{_THREE_ACT}/fork")
        self.assertEqual(forked.status_code, 200, forked.text)
        clone = forked.json()
        # New id, owned + editable, and the Library original stays in place.
        self.assertTrue(clone["id"].startswith("plot_"))
        self.assertNotEqual(clone["id"], _THREE_ACT)
        self.assertTrue(clone["editable"])
        self.assertFalse(clone["is_library"])
        self.assertEqual(clone["title"], "Three-Act Story Arc")
        # The whole entry came across (not just title/body) — beats included.
        self.assertEqual(len(clone["metadata"]["beats"]), 7)
        # The owned clone is a plot/ family node — indexed like a plotline.
        entry = self.service._build_node_index().by_id.get(clone["id"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry.entry_type, "plot:template")
        # The Library original is still listed alongside the clone.
        ids = [e["id"] for e in self.client.get("/api/plot/templates").json()["entries"]]
        self.assertIn(_THREE_ACT, ids)
        self.assertIn(clone["id"], ids)

    def test_owned_clone_is_editable_and_deletable(self) -> None:
        clone = self.client.post(f"/api/plot/templates/{_THREE_ACT}/fork").json()
        spec = clone["template"]
        spec["description"] = "My adapted lens."
        saved = self.client.put(
            f"/api/plot/templates/{clone['id']}",
            json={"title": "My Three-Act", "body": "# Mine\n", "template": spec, "base_revision": clone["revision"]},
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        reread = self.client.get(f"/api/plot/templates/{clone['id']}").json()
        self.assertEqual(reread["title"], "My Three-Act")
        self.assertEqual(reread["template"]["description"], "My adapted lens.")
        self.assertTrue(reread["editable"])
        deleted = self.client.delete(f"/api/plot/templates/{clone['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(self.client.get(f"/api/plot/templates/{clone['id']}").status_code, 404)

    def test_forking_an_owned_template_is_refused(self) -> None:
        clone = self.client.post(f"/api/plot/templates/{_THREE_ACT}/fork").json()
        # Nothing to clone — an owned template is directly editable.
        again = self.client.post(f"/api/plot/templates/{clone['id']}/fork")
        self.assertEqual(again.status_code, 409, again.text)

    def test_owned_clone_metadata_round_trips_on_save(self) -> None:
        # S4c finding #1: read_plot_template heals + returns metadata, so the save
        # path must persist it — a schema-editor-added field must survive an edit,
        # not be silently wiped (the write-side of the S4b finding #5 gap). Add a
        # `note` field to plot:template, set it on an owned clone, save, re-read.
        layer_id = self.service._metadata_schema_layer_id(self.root)
        self.service.upsert_metadata_field(
            UpsertMetadataFieldRequest(
                layer_id=layer_id,
                field_id="note",
                field=MetadataFieldDefinition(name="Note", type="text"),
                entry_type="plot:template",
            )
        )
        clone = self.client.post(f"/api/plot/templates/{_THREE_ACT}/fork").json()
        saved = self.client.put(
            f"/api/plot/templates/{clone['id']}",
            json={
                "title": clone["title"],
                "body": "# edited\n",
                "template": clone["template"],
                "metadata": {"note": "keep me"},
                "base_revision": clone["revision"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        # Persisted to disk, not just echoed: a fresh read carries the field.
        reread = self.client.get(f"/api/plot/templates/{clone['id']}").json()
        self.assertEqual(reread["metadata"].get("note"), "keep me")

    def test_owned_clone_beats_are_editable_and_round_trip(self) -> None:
        # The #736 win: the beat roster is a real `beats` ordered-list field, so it
        # edits + persists through the standard metadata save path — no bespoke beat
        # editor, no opaque `template:` block. Fork, rename a beat + drop one, save,
        # re-read, and confirm the edit stuck and stable beat ids survived.
        clone = self.client.post(f"/api/plot/templates/{_THREE_ACT}/fork").json()
        beats = clone["metadata"]["beats"]
        self.assertEqual(len(beats), 7)
        beats[0]["title"] = "Reframed setup"
        edited = beats[:-1]  # drop the trailing beat → 6
        saved = self.client.put(
            f"/api/plot/templates/{clone['id']}",
            json={
                "title": clone["title"],
                "body": clone["body"],
                "template": clone["template"],
                "metadata": {"beats": edited},
                "base_revision": clone["revision"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        got = self.client.get(f"/api/plot/templates/{clone['id']}").json()["metadata"]["beats"]
        self.assertEqual(len(got), 6)
        self.assertEqual(got[0]["title"], "Reframed setup")
        self.assertEqual(got[0]["id"], "setup_pressure")  # stable id preserved through the edit

    def test_a_plotline_is_not_a_template(self) -> None:
        created = self.client.post("/api/plot/plotlines", json={"title": "A Thread"}).json()
        # Same `plot` kind + folder, but reading it as a template is refused.
        self.assertEqual(self.client.get(f"/api/plot/templates/{created['id']}").status_code, 404)
        # And templates never leak into the plotline list.
        plotline_ids = [e["id"] for e in self.client.get("/api/plot/plotlines").json()["entries"]]
        self.assertNotIn(_THREE_ACT, plotline_ids)

    def test_missing_template_404s(self) -> None:
        self.assertEqual(self.client.get("/api/plot/templates/builtin-plot-nope").status_code, 404)


class PlotlineInstantiationTests(PlotTestCase):
    """A plotline is a plot-template instance (ADR-0053 §1; ADR-0048 §3 / S7 Slice 2,
    #776): instantiating a template snapshots its beat roster into a book-local
    `plot:plotline` the writer then specializes. An ad-hoc plotline is just a plotline
    created with no beats — there is no separate instance kind or `/instances`
    resource. Plotline CRUD proper lives in `test_plot.py`; this covers `instantiate`
    (the one bespoke op) and the beats/lineage/specifics it seeds."""

    def _instantiate(self, template_id: str = _THREE_ACT) -> dict:
        response = self.client.post(f"/api/plot/templates/{template_id}/instantiate")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_instantiate_snapshots_beats_and_lineage(self) -> None:
        plotline = self._instantiate()
        # A book-local editable plotline, titled after the template.
        self.assertTrue(plotline["id"].startswith("plot_"))
        self.assertEqual(plotline["entry_type"], "plot:plotline")
        self.assertEqual(plotline["title"], "Three-Act Story Arc")
        # The 7 beats came across verbatim (title / function / stable id); the
        # per-beat `specifics` is left for the writer, so it is not snapshotted.
        beats = plotline["metadata"]["instance_beats"]
        self.assertEqual(len(beats), 7)
        self.assertEqual(beats[0]["id"], "setup_pressure")
        self.assertEqual(beats[0]["title"], "Setup pressure")
        self.assertIn("Establishes", beats[0]["function"])
        self.assertNotIn("specifics", beats[0])
        # Lineage snapshot — "which of the 14 structures is this?"
        self.assertEqual(plotline["metadata"]["source_template_id"], _THREE_ACT)
        self.assertEqual(plotline["metadata"]["source_template_name"], "Three-Act Story Arc")

    def test_instantiate_copies_every_snapshot_member_faithfully(self) -> None:
        # Full fidelity across ALL snapshot keys for every beat, compared against
        # the source template — so a regression dropping (say) `guidance` or
        # `required` from _INSTANCE_BEAT_SNAPSHOT_KEYS is caught, not just title/id.
        template_beats = self.client.get(f"/api/plot/templates/{_THREE_ACT}").json()["metadata"]["beats"]
        plotline_beats = self._instantiate()["metadata"]["instance_beats"]
        self.assertEqual(len(plotline_beats), len(template_beats))
        for src, got in zip(template_beats, plotline_beats, strict=True):
            for key in ("title", "function", "guidance", "required", "id"):
                self.assertEqual(got.get(key), src.get(key), f"beat member {key} not copied faithfully")
            self.assertNotIn("specifics", got)  # the one member left for the writer

    def test_plotline_is_indexed_book_local_and_the_template_stays_pristine(self) -> None:
        before = _BUILTIN_THREE_ACT.read_bytes()
        plotline = self._instantiate()
        entry = self.service._build_node_index().by_id.get(plotline["id"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry.kind, "plot")
        self.assertEqual(entry.entry_type, "plot:plotline")
        # Instantiate is a pure read of the (inherited, read-only) template — the
        # shipped file is byte-untouched.
        self.assertEqual(_BUILTIN_THREE_ACT.read_bytes(), before)
        # It appears in the plotline listing and reads back on its own endpoint.
        listed = [e["id"] for e in self.client.get("/api/plot/plotlines").json()["entries"]]
        self.assertIn(plotline["id"], listed)
        self.assertEqual(self.client.get(f"/api/plot/plotlines/{plotline['id']}").status_code, 200)

    def test_specifics_round_trip_through_the_standard_save(self) -> None:
        # The Slice-2 win: the writer makes a generic beat concrete to this book,
        # and it persists through the ordinary metadata save path (no bespoke editor).
        plotline = self._instantiate()
        beats = plotline["metadata"]["instance_beats"]
        beats[0]["specifics"] = "The debt Mara hides from Jon."
        saved = self.client.put(
            f"/api/plot/plotlines/{plotline['id']}",
            json={
                "title": "Mara & Jon",
                "body": "",
                "metadata": {**plotline["metadata"], "instance_beats": beats},
                "base_revision": plotline["revision"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        reread = self.client.get(f"/api/plot/plotlines/{plotline['id']}").json()
        self.assertEqual(reread["title"], "Mara & Jon")
        got = reread["metadata"]["instance_beats"]
        self.assertEqual(len(got), 7)
        self.assertEqual(got[0]["specifics"], "The debt Mara hides from Jon.")
        self.assertEqual(got[0]["title"], "Setup pressure")  # generic context rode along
        # Lineage preserved across the save (the hidden fields round-trip in metadata).
        self.assertEqual(reread["metadata"]["source_template_name"], "Three-Act Story Arc")

    def test_ad_hoc_plotline_has_empty_beats_and_no_lineage(self) -> None:
        created = self.client.post("/api/plot/plotlines", json={"title": "My own plot"})
        self.assertEqual(created.status_code, 200, created.text)
        plotline = created.json()
        self.assertEqual(plotline["entry_type"], "plot:plotline")
        self.assertEqual(plotline["title"], "My own plot")
        # No template behind it → no beats, no lineage.
        self.assertEqual(plotline["metadata"].get("instance_beats", []), [])
        self.assertFalse(plotline["metadata"].get("source_template_id"))
        self.assertFalse(plotline["metadata"].get("source_template_name"))

    def test_ad_hoc_plotline_can_author_and_save_beats(self) -> None:
        # The "roll your own plot" path (Anton): create an empty plotline, author
        # beats from scratch — including `specifics` — and save through the standard
        # metadata path. Distinct from the specifics round-trip (which starts from an
        # instantiated, pre-filled roster).
        plotline = self.client.post("/api/plot/plotlines", json={"title": "Custom arc"}).json()
        beats = [
            {"id": "b1", "title": "Inciting spark", "specifics": "Mara loses the ledger.", "required": True},
            {"id": "b2", "title": "The reckoning", "specifics": "Jon finds the debt.", "required": False},
        ]
        saved = self.client.put(
            f"/api/plot/plotlines/{plotline['id']}",
            json={
                "title": "Custom arc",
                "body": "",
                "metadata": {"instance_beats": beats},
                "base_revision": plotline["revision"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        got = self.client.get(f"/api/plot/plotlines/{plotline['id']}").json()["metadata"]["instance_beats"]
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["title"], "Inciting spark")
        self.assertEqual(got[0]["specifics"], "Mara loses the ledger.")
        self.assertEqual(got[1]["required"], False)

    def test_delete_removes_from_list_and_404s(self) -> None:
        plotline = self._instantiate()
        deleted = self.client.delete(f"/api/plot/plotlines/{plotline['id']}")
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertNotIn(plotline["id"], [e["id"] for e in deleted.json()["entries"]])
        self.assertEqual(self.client.get(f"/api/plot/plotlines/{plotline['id']}").status_code, 404)

    def test_lineage_survives_the_source_template_being_deleted(self) -> None:
        # The durability point (Anton): instantiate from an OWNED template, then
        # delete it. `source_template_*` are plain text, not a live ref, so the
        # reference purge never touches them and the plotline still names its
        # structure — a healing entity_ref would have blanked here.
        clone = self.client.post(f"/api/plot/templates/{_THREE_ACT}/fork").json()
        plotline = self._instantiate(clone["id"])
        self.assertEqual(plotline["metadata"]["source_template_id"], clone["id"])
        self.assertEqual(self.client.delete(f"/api/plot/templates/{clone['id']}").status_code, 200)
        reread = self.client.get(f"/api/plot/plotlines/{plotline['id']}").json()
        self.assertEqual(reread["metadata"]["source_template_name"], "Three-Act Story Arc")
        self.assertEqual(len(reread["metadata"]["instance_beats"]), 7)

    def test_instantiate_from_an_inherited_library_template(self) -> None:
        # The source is a read-only Library node; instantiate reads it fine and the
        # plotline is book-local + editable regardless.
        plotline = self._instantiate(_THREE_ACT)
        saved = self.client.put(
            f"/api/plot/plotlines/{plotline['id']}",
            json={"title": "Renamed", "body": "", "metadata": plotline["metadata"], "base_revision": plotline["revision"]},
        )
        self.assertEqual(saved.status_code, 200, saved.text)

    def test_instantiating_a_missing_template_404s(self) -> None:
        self.assertEqual(self.client.post("/api/plot/templates/builtin-plot-nope/instantiate").status_code, 404)

    def test_instantiating_a_non_template_plot_node_404s(self) -> None:
        # instantiate resolves the template through the family guard — a card id
        # is not a template, so it 404s rather than snapshotting a bogus roster.
        card = self.client.post("/api/plot/cards", json={"title": "A card"}).json()
        self.assertEqual(
            self.client.post(f"/api/plot/templates/{card['id']}/instantiate").status_code, 404
        )


class BeatIdentityTests(PlotTestCase):
    """ADR-0048 S7 Slice 3a (#779): every beat carries a stable, list-unique `id`.

    A card→beat link (Slice 3b) points at the composite *(plotline node id, beat
    id)*, so a beat's id must be present and unique within its own list. The write
    path mints one where it is missing (`beat_<sha256(title+salt)[:12]>`) and
    re-salts a within-list collision. It is auto-fill only — a blank beat still
    saves, matching the sparse-spec principle — and stable once minted, so 3b's
    links survive edits. Both write surfaces are covered: the template `beats`
    field and the plotline `instance_beats` field.
    """

    def _fork(self) -> dict:
        return self.client.post(f"/api/plot/templates/{_THREE_ACT}/fork").json()

    def _save_template_beats(self, clone: dict, beats: list[dict]) -> dict:
        saved = self.client.put(
            f"/api/plot/templates/{clone['id']}",
            json={
                "title": clone["title"],
                "body": clone["body"],
                "template": clone["template"],
                "metadata": {"beats": beats},
                "base_revision": clone["revision"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        return self.client.get(f"/api/plot/templates/{clone['id']}").json()

    def test_a_new_beat_without_an_id_is_minted(self) -> None:
        clone = self._fork()
        beats = clone["metadata"]["beats"] + [{"title": "A fresh beat", "function": "Does a thing."}]
        got = self._save_template_beats(clone, beats)["metadata"]["beats"]
        self.assertEqual(len(got), 8)
        self.assertEqual(got[0]["id"], "setup_pressure")  # pre-existing human id untouched
        self.assertTrue(got[-1]["id"].startswith("beat_"))  # the appended beat gained a minted id
        self.assertGreater(len(got[-1]["id"]), len("beat_"))

    def test_two_same_title_beats_get_distinct_ids(self) -> None:
        # Salt, not title, guarantees uniqueness: identically-named beats diverge.
        clone = self._fork()
        got = self._save_template_beats(clone, [{"title": "Twist"}, {"title": "Twist"}])["metadata"]["beats"]
        self.assertEqual(len(got), 2)
        self.assertTrue(all(b["id"].startswith("beat_") for b in got))
        self.assertNotEqual(got[0]["id"], got[1]["id"])

    def test_a_blank_beat_saves_and_gains_an_id(self) -> None:
        # No `required` gate: an empty beat (no title, no id) must not block the
        # write — it simply saves and is minted an id (sparse-spec principle).
        clone = self._fork()
        got = self._save_template_beats(clone, [{}])["metadata"]["beats"]
        self.assertEqual(len(got), 1)
        self.assertTrue(got[0]["id"].startswith("beat_"))

    def test_a_minted_id_survives_a_retitle(self) -> None:
        # Minted once, then persisted: renaming a beat never changes its id, so a
        # 3b link to it survives the edit.
        clone = self._fork()
        first = self._save_template_beats(clone, [{"title": "Original"}])
        minted = first["metadata"]["beats"][0]["id"]
        self.assertTrue(minted.startswith("beat_"))
        retitled = self._save_template_beats(
            {**clone, "revision": first["revision"]},
            [{"id": minted, "title": "Renamed"}],
        )["metadata"]["beats"]
        self.assertEqual(retitled[0]["id"], minted)
        self.assertEqual(retitled[0]["title"], "Renamed")

    def test_a_within_list_id_collision_is_resalted(self) -> None:
        # Copy-pasting a beat carries its id along; the second occurrence is
        # re-minted so the two stay distinct — never rejected.
        clone = self._fork()
        got = self._save_template_beats(
            clone, [{"id": "dup", "title": "A"}, {"id": "dup", "title": "B"}]
        )["metadata"]["beats"]
        ids = [b["id"] for b in got]
        self.assertEqual(len(set(ids)), 2)
        self.assertEqual(ids.count("dup"), 1)  # the first kept it; the clash re-salted

    def test_ad_hoc_plotline_beats_are_minted(self) -> None:
        # The plotline `instance_beats` write path is hooked too, not only the
        # template `beats` path — an ad-hoc plotline's hand-authored beats get ids.
        plotline = self.client.post("/api/plot/plotlines", json={"title": "Custom"}).json()
        saved = self.client.put(
            f"/api/plot/plotlines/{plotline['id']}",
            json={
                "title": "Custom",
                "body": "",
                "metadata": {"instance_beats": [{"title": "Spark"}, {"title": "Spark"}]},
                "base_revision": plotline["revision"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        got = self.client.get(f"/api/plot/plotlines/{plotline['id']}").json()["metadata"]["instance_beats"]
        self.assertTrue(all(b["id"].startswith("beat_") for b in got))
        self.assertNotEqual(got[0]["id"], got[1]["id"])

    def test_instantiate_keeps_copied_ids_and_mints_added_beats(self) -> None:
        # Provenance + growth: instantiate copies the template's beat ids verbatim
        # (already list-unique), and a beat added afterwards is minted a fresh id
        # while the copied ones stay put.
        plotline = self.client.post(f"/api/plot/templates/{_THREE_ACT}/instantiate").json()
        beats = plotline["metadata"]["instance_beats"]
        self.assertEqual(beats[0]["id"], "setup_pressure")  # copied verbatim
        beats = [*beats, {"title": "An added beat"}]
        saved = self.client.put(
            f"/api/plot/plotlines/{plotline['id']}",
            json={
                "title": plotline["title"],
                "body": "",
                "metadata": {**plotline["metadata"], "instance_beats": beats},
                "base_revision": plotline["revision"],
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        got = self.client.get(f"/api/plot/plotlines/{plotline['id']}").json()["metadata"]["instance_beats"]
        self.assertEqual(len(got), 8)
        self.assertEqual(got[0]["id"], "setup_pressure")  # copied id untouched
        self.assertTrue(got[-1]["id"].startswith("beat_"))  # added beat minted
