"""Saved-view Node kind (0.5.0, #35/#78). A frontmatter-only kind carrying a
ViewSpec (anchor kind + set-algebra expr + sort) under `views/`. Covers CRUD,
body-less storage, the view_ref cycle check, ViewSpec grammar validation, and
the NodePickerConfig sources <-> legacy-membership reducer.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.main import service as svc
from app.models import NodePickerConfig
from app.models_views import ViewExpr, ViewSpec


class ViewCrudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "View Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create(self, title: str, spec: dict, presentation: str = "flat") -> dict:
        res = self.client.post(
            "/api/views",
            json={"title": title, "spec": spec, "presentation": presentation},
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_create_read_roundtrips_spec_and_presentation(self) -> None:
        spec = {
            "kind": "lore",
            "expr": {
                "difference": {
                    "keep": {"descendants_of": "lore:character"},
                    "remove": {"descendants_of": "lore:place"},
                }
            },
            "sort": {"by": "title", "dir": "asc"},
        }
        created = self._create("Non-place characters", spec, presentation="grouped")
        self.assertTrue(created["id"].startswith("view"))
        self.assertEqual(created["entry_type"], "view:view")
        self.assertEqual(created["presentation"], "grouped")
        self.assertEqual(created["spec"]["kind"], "lore")
        self.assertEqual(
            created["spec"]["expr"]["difference"]["keep"]["descendants_of"],
            "lore:character",
        )

        got = self.client.get(f"/api/views/{created['id']}")
        self.assertEqual(got.status_code, 200, got.text)
        self.assertEqual(got.json()["spec"], created["spec"])

    def test_designer_layout_persists_and_roundtrips(self) -> None:
        # A view created without the designer has no layout yet.
        created = self._create("Tagged", {"kind": "lore", "expr": {"tagged": "gotham"}})
        self.assertIsNone(created.get("layout"))

        layout = {
            "nodes": [
                {"id": "output", "kind": "output", "position": {"x": 300.0, "y": 40.0}, "cfg": {}},
                {"id": "n1", "kind": "tagged", "position": {"x": 40.0, "y": 120.0}, "cfg": {"tagged": "gotham"}},
            ],
            "edges": [
                {"id": "e1", "source": "n1", "target": "output", "source_handle": "out", "target_handle": "in"},
            ],
        }
        saved = self.client.put(
            f"/api/views/{created['id']}",
            json={
                "title": "Tagged",
                "base_revision": created["revision"],
                "spec": {"kind": "lore", "expr": {"tagged": "gotham"}},
                "presentation": "flat",
                "layout": layout,
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)

        got = self.client.get(f"/api/views/{created['id']}").json()
        leaf = got["layout"]["nodes"][1]
        self.assertEqual(leaf["kind"], "tagged")  # not collapsed to a "type" node
        self.assertEqual(leaf["position"], {"x": 40.0, "y": 120.0})  # exact positions kept
        self.assertEqual(leaf["cfg"], {"tagged": "gotham"})
        self.assertEqual(got["layout"]["edges"][0]["target_handle"], "in")
        # Persisted into the view file's front matter.
        text = next((self.root / "views").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("layout:", text)

    def test_stored_body_less_under_views_folder(self) -> None:
        created = self._create("Cast", {"kind": "lore", "expr": {"type": "lore:character"}})
        files = list((self.root / "views").glob("*.md"))
        self.assertEqual(len(files), 1)
        text = files[0].read_text(encoding="utf-8")
        # spec lives in front matter, compact (exclude_none) — no prose body.
        self.assertIn("spec:", text)
        self.assertIn("lore:character", text)
        self.assertNotIn("intersect", text)  # unset ViewExpr slots omitted
        self.assertIn(created["id"], text)  # canonical id in front matter

    def test_list_reports_summary_with_anchor_kind(self) -> None:
        self._create("Cast", {"kind": "lore", "expr": {"type": "lore:character"}})
        self._create("Scenes", {"kind": "scene"})
        res = self.client.get("/api/views")
        self.assertEqual(res.status_code, 200, res.text)
        entries = {e["title"]: e for e in res.json()["entries"]}
        self.assertEqual(entries["Cast"]["view_kind"], "lore")
        self.assertEqual(entries["Scenes"]["view_kind"], "scene")

    def test_save_updates_spec_and_conflict_guard(self) -> None:
        created = self._create("V", {"kind": "lore", "expr": {"type": "lore:character"}})
        got = self.client.get(f"/api/views/{created['id']}").json()
        # Stale revision → 409.
        stale = self.client.put(
            f"/api/views/{created['id']}",
            json={"title": "V", "base_revision": "stale", "spec": {"kind": "lore"}},
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        # Fresh revision → ok, spec replaced.
        ok = self.client.put(
            f"/api/views/{created['id']}",
            json={"title": "V2", "base_revision": got["revision"], "spec": {"kind": "scene"}},
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        self.assertEqual(
            ok.json()["spec"], {"kind": "scene", "expr": None, "groups": None, "sort": None}
        )

    def test_delete_removes_view(self) -> None:
        created = self._create("Gone", {"kind": "lore"})
        res = self.client.delete(f"/api/views/{created['id']}")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["entries"], [])
        self.assertEqual(self.client.get(f"/api/views/{created['id']}").status_code, 404)

    def test_view_ref_cycle_rejected_at_save(self) -> None:
        b = self._create("B", {"kind": "lore", "expr": {"type": "lore:character"}})
        a = self._create("A", {"kind": "lore", "expr": {"view_ref": b["id"]}})
        got_b = self.client.get(f"/api/views/{b['id']}").json()
        # Edit B to reference A → A -> B -> A is a cycle.
        res = self.client.put(
            f"/api/views/{b['id']}",
            json={
                "title": "B",
                "base_revision": got_b["revision"],
                "spec": {"kind": "lore", "expr": {"view_ref": a["id"]}},
            },
        )
        self.assertEqual(res.status_code, 422, res.text)
        self.assertIn("cycle", res.text.lower())

    def test_view_ref_cycle_via_groups_rejected_at_save(self) -> None:
        # A named-handle view carries its refs under `groups`, not `expr`. The
        # cycle guard must walk groups too, else A -> B -> A slips through when
        # the ref lives inside a group handle.
        b = self._create("B", {"kind": "lore", "expr": {"type": "lore:character"}})
        a = self._create(
            "A", {"kind": "lore", "groups": [{"name": "g", "expr": {"view_ref": b["id"]}}]}
        )
        got_b = self.client.get(f"/api/views/{b['id']}").json()
        # Edit B to reference A via a group → A -> B -> A is a cycle.
        res = self.client.put(
            f"/api/views/{b['id']}",
            json={
                "title": "B",
                "base_revision": got_b["revision"],
                "spec": {"kind": "lore", "groups": [{"name": "g", "expr": {"view_ref": a["id"]}}]},
            },
        )
        self.assertEqual(res.status_code, 422, res.text)
        self.assertIn("cycle", res.text.lower())

    def test_invalid_expr_rejected(self) -> None:
        # Two primary slots set → structural validation rejects it.
        res = self.client.post(
            "/api/views",
            json={
                "title": "Bad",
                "spec": {"kind": "lore", "expr": {"type": "lore:character", "tagged": "x"}},
            },
        )
        self.assertEqual(res.status_code, 422, res.text)


class ViewSpecModelTests(unittest.TestCase):
    def test_annotate_requires_of_and_payload(self) -> None:
        with self.assertRaises(ValueError):
            ViewExpr(annotate={"label": "X"})  # missing `of`
        with self.assertRaises(ValueError):
            ViewExpr(annotate={}, of={"type": "lore:character"})  # empty payload
        ok = ViewExpr(annotate={"label": "X", "rank": 1}, of={"type": "lore:character"})
        self.assertEqual(ok.annotate.label, "X")

    def test_of_without_annotate_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ViewExpr(type="lore:character", of={"tagged": "x"})

    def test_empty_union_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ViewExpr(union=[])

    def test_sort_field_requires_key(self) -> None:
        with self.assertRaises(ValueError):
            ViewSpec(kind="lore", sort={"by": "field"})

    def test_named_groups_roundtrip(self) -> None:
        spec = ViewSpec(
            kind="lore",
            groups=[
                {"name": "Cast", "expr": {"type": "lore:character"}},
                {"name": "Deities", "expr": {"descendants_of": "lore:deity"}, "color": "amber"},
            ],
        )
        self.assertIsNone(spec.expr)
        self.assertEqual([g.name for g in spec.groups], ["Cast", "Deities"])
        self.assertEqual(spec.groups[1].color, "amber")

    def test_group_requires_name(self) -> None:
        with self.assertRaises(ValueError):
            ViewSpec(kind="lore", groups=[{"name": "", "expr": {"type": "lore:character"}}])

    def test_expr_and_groups_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ValueError):
            ViewSpec(
                kind="lore",
                expr={"type": "lore:character"},
                groups=[{"name": "Cast", "expr": {"type": "lore:character"}}],
            )


class NodePickerConfigSourcesTests(unittest.TestCase):
    def test_membership_roundtrip(self) -> None:
        cfg = NodePickerConfig.from_membership(
            kinds=["lore", "scene"],
            entry_types={"lore": ["lore:character", "lore:place"]},
        )
        self.assertEqual(cfg.kinds, ["lore", "scene"])
        self.assertEqual(cfg.entry_types, {"lore": ["lore:character", "lore:place"]})
        # Only `sources` (+ mechanics) serialize — the dead shape is gone.
        dumped = cfg.model_dump()
        self.assertIn("sources", dumped)
        self.assertNotIn("kinds", dumped)
        self.assertNotIn("entry_types", dumped)

    def test_view_ref_source_contributes_no_membership(self) -> None:
        cfg = NodePickerConfig(
            sources=[{"view": "view_abc"}, {"kind": "lore", "expr": {"type": "lore:character"}}]
        )
        self.assertEqual(cfg.kinds, ["lore"])
        self.assertEqual(cfg.entry_types, {"lore": ["lore:character"]})


if __name__ == "__main__":
    unittest.main()
