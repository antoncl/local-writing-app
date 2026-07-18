"""Saved-view Node kind (0.5.0, #35/#78). A frontmatter-only kind carrying a
ViewSpec (anchor kind + set-algebra expr + sort) under `views/`. Covers CRUD,
body-less storage, ViewSpec grammar validation, and the NodePickerConfig
sources <-> legacy-membership reducer.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app
from app.models import NodePickerConfig
from app.models_views import NestMatch, NestOp, ViewExpr, ViewSpec
from app.runtime import service as svc


class ViewCrudTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "View Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create(self, title: str, spec: dict) -> dict:
        res = self.client.post(
            "/api/views",
            json={"title": title, "spec": spec},
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_create_read_roundtrips_spec(self) -> None:
        spec = {
            "kind": "lore",
            "expr": {
                "difference": {
                    "keep": {"descendants_of": "lore:character"},
                    "remove": {"descendants_of": "lore:location"},
                }
            },
            "sort": {"by": "title", "dir": "asc"},
        }
        created = self._create("Non-place characters", spec)
        self.assertTrue(created["id"].startswith("view"))
        self.assertEqual(created["entry_type"], "view:view")
        self.assertNotIn("presentation", created)
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
        # The summary carries the full spec (#95) so a client needn't refetch
        # each view to evaluate it (serialized dense, like the getView endpoint).
        self.assertEqual(entries["Cast"]["spec"]["kind"], "lore")
        self.assertEqual(entries["Cast"]["spec"]["expr"]["type"], "lore:character")

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
            ok.json()["spec"],
            {"kind": "scene", "expr": None, "groups": None, "sort": None, "params": None, "group_by": None},
        )

    def test_delete_removes_view(self) -> None:
        created = self._create("Gone", {"kind": "lore"})
        res = self.client.delete(f"/api/views/{created['id']}")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["entries"], [])
        self.assertEqual(self.client.get(f"/api/views/{created['id']}").status_code, 404)

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

    def test_multi_level_sort_chain_roundtrip(self) -> None:
        # #230: `then` chains a tiebreaker; stored verbatim, round-trips.
        spec = ViewSpec(
            kind="lore",
            expr={"descendants_of": "lore:base"},
            sort={"by": "field", "field_key": "team", "dir": "asc", "then": {"by": "title", "dir": "desc"}},
        )
        self.assertEqual(spec.sort.by, "field")
        self.assertEqual(spec.sort.then.by, "title")
        self.assertEqual(spec.sort.then.dir, "desc")
        self.assertIsNone(spec.sort.then.then)
        back = ViewSpec.model_validate(spec.model_dump(exclude_none=True))
        self.assertEqual(back.sort.then.by, "title")
        self.assertEqual(back.sort.then.dir, "desc")

    def test_per_group_group_by_roundtrip(self) -> None:
        # ADR-0037 Amendment 1: each named group carries its OWN organize levels.
        spec = ViewSpec(
            kind="lore",
            groups=[
                {"name": "Cast", "expr": {"type": "lore:character"}, "group_by": [{"field": "rank"}]},
                {"name": "Places", "expr": {"type": "lore:location"}},
            ],
        )
        self.assertEqual([lvl.field for lvl in spec.groups[0].group_by], ["rank"])
        self.assertIsNone(spec.groups[1].group_by)
        # Survives the storage round-trip (model_dump exclude_none → model_validate).
        back = ViewSpec.model_validate(spec.model_dump(exclude_none=True))
        self.assertEqual(back.groups[0].group_by[0].field, "rank")
        self.assertIsNone(back.groups[1].group_by)

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


class ParameterizedViewGrammarTests(unittest.TestCase):
    """#184 forward model grammar (ADR-0031/0032, views-and-filters.md §14): the
    `field_of` projection + `var`/`$self` leaves, the 6→4 op enum, and the
    `params` formal list on a ViewSpec."""

    def test_op_enum_is_4_valued(self) -> None:
        for op in ("overlap", "disjoint", "set", "unset"):
            self.assertEqual(ViewExpr(field={"key": "pov", "op": op}).field.op, op)
        # The retired 6-op values no longer validate.
        for old in ("eq", "neq", "includes", "not_includes"):
            with self.assertRaises(ValueError):
                ViewExpr(field={"key": "pov", "op": old})

    def test_field_of_is_a_primary_slot(self) -> None:
        expr = ViewExpr(field_of={"of": {"type": "scene:scene"}, "field": "pov"})
        self.assertEqual(expr.field_of.field, "pov")
        self.assertEqual(expr.field_of.of.type, "scene:scene")
        # Exclusive with other primaries.
        with self.assertRaises(ValueError):
            ViewExpr(field_of={"of": {"type": "scene:scene"}, "field": "pov"}, type="lore:character")

    def test_field_of_requires_field(self) -> None:
        with self.assertRaises(ValueError):
            ViewExpr(field_of={"of": {"type": "scene:scene"}, "field": ""})

    def test_var_leaf(self) -> None:
        self.assertEqual(ViewExpr(var="$self").var, "$self")
        self.assertEqual(ViewExpr(var="POV").var, "POV")
        with self.assertRaises(ValueError):
            ViewExpr(var="$self", type="lore:character")

    def test_tagged_operand_in_predicate_value_roundtrips(self) -> None:
        # A predicate value may carry a tagged operand (loose `Any`, structural).
        expr = ViewExpr(field={"key": "pov", "op": "overlap", "value": {"var": "POV"}})
        self.assertEqual(expr.field.value, {"var": "POV"})
        proj = ViewExpr(
            field={"key": "tags", "op": "overlap", "value": {"field_of": {"of": {"var": "$self"}, "field": "tags"}}}
        )
        self.assertEqual(proj.field.value["field_of"]["field"], "tags")

    def test_params_list_roundtrips_and_stores_no_type(self) -> None:
        spec = ViewSpec(
            kind="scene",
            expr={"field": {"key": "pov", "op": "overlap", "value": {"var": "POV"}}},
            params=[{"name": "POV", "label": "Point of view", "default": None},
                    {"name": "status", "label": "Status", "default": ["draft", "revised"]}],
        )
        self.assertEqual([p.name for p in spec.params], ["POV", "status"])
        self.assertEqual(spec.params[1].default, ["draft", "revised"])
        # No `type` field is stored on a param (recomputed at load, §14.1).
        self.assertNotIn("type", spec.params[0].model_dump())

    def test_params_absent_is_degenerate_closed_case(self) -> None:
        spec = ViewSpec(kind="lore", expr={"type": "lore:character"})
        self.assertIsNone(spec.params)


class NestGrammarTests(unittest.TestCase):
    """The `nest` relational operator (ADR-0028 / #106) — structural validation."""

    def _nest(self, **over: object) -> dict:
        base = {
            "parents": {"field": {"key": "parent", "op": "unset"}},
            "children": {"type": "lore:location"},
            "match": {"field": "parent", "direction": "child_to_parent", "by": "ref"},
        }
        base.update(over)
        return base

    def test_valid_nest_expr_and_defaults(self) -> None:
        expr = ViewExpr(nest=self._nest())
        assert expr.nest is not None
        self.assertEqual(expr.nest.match.direction, "child_to_parent")
        self.assertEqual(expr.nest.match.by, "ref")  # `by` defaults to ref
        self.assertFalse(expr.nest.recursive)  # non-recursive by default
        self.assertEqual(expr.nest.children.type, "lore:location")

    def test_recursive_self_loop_flag(self) -> None:
        expr = ViewExpr(nest=self._nest(recursive=True))
        assert expr.nest is not None
        self.assertTrue(expr.nest.recursive)

    def test_match_by_title(self) -> None:
        m = NestMatch(field="house", direction="parent_to_children", by="title")
        self.assertEqual(m.by, "title")
        self.assertEqual(m.direction, "parent_to_children")

    def test_invalid_direction_rejected(self) -> None:
        with self.assertRaises(ValueError):
            NestMatch(field="parent", direction="sideways", by="ref")

    def test_invalid_match_by_rejected(self) -> None:
        with self.assertRaises(ValueError):
            NestMatch(field="parent", direction="child_to_parent", by="context_pick")

    def test_empty_match_field_rejected(self) -> None:
        with self.assertRaises(ValueError):
            NestMatch(field="", direction="child_to_parent", by="ref")

    def test_nest_requires_match(self) -> None:
        # match is the one required field — without a rule there is no join.
        with self.assertRaises(ValueError):
            NestOp(parents={"field": {"key": "parent", "op": "unset"}})

    def test_nest_handles_optional_default_to_universe(self) -> None:
        # An unconnected handle = the whole universe (None).
        op = NestOp(match={"field": "parent", "direction": "child_to_parent"})
        self.assertIsNone(op.parents)
        self.assertIsNone(op.children)

    def test_nest_is_exclusive_primary_slot(self) -> None:
        # nest + another primary slot violates exactly-one.
        with self.assertRaises(ValueError):
            ViewExpr(nest=self._nest(), type="lore:location")


class NestApiTests(ViewCrudTests):
    """Nest specs must round-trip through the CRUD API and be cycle-checked."""

    def test_nest_spec_roundtrips(self) -> None:
        spec = {
            "kind": "lore",
            "expr": {
                "nest": {
                    "parents": {"field": {"key": "parent", "op": "unset"}},
                    "children": {"descendants_of": "lore:location"},
                    "match": {"field": "parent", "direction": "child_to_parent", "by": "ref"},
                    "recursive": True,
                }
            },
        }
        created = self._create("Nested locations", spec)
        got = self.client.get(f"/api/views/{created['id']}").json()
        self.assertEqual(got["spec"]["expr"]["nest"]["recursive"], True)
        self.assertEqual(
            got["spec"]["expr"]["nest"]["match"]["direction"], "child_to_parent"
        )
        self.assertEqual(got["spec"], created["spec"])


class NodePickerConfigSourcesTests(unittest.TestCase):
    def test_membership_roundtrip(self) -> None:
        cfg = NodePickerConfig.from_membership(
            kinds=["lore", "scene"],
            entry_types={"lore": ["lore:character", "lore:location"]},
        )
        self.assertEqual(cfg.kinds, ["lore", "scene"])
        self.assertEqual(cfg.entry_types, {"lore": ["lore:character", "lore:location"]})
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


class ViewUiStateTests(unittest.TestCase):
    """Fold/ui state on the view node (ADR-0036): the lock-free /ui endpoint,
    round-trip, independence from the spec revision-lock, and the system-view
    read-only guard."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        svc.__init__()
        svc.create_project(self.root, "View UI Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _create(self, title: str, spec: dict) -> dict:
        res = self.client.post("/api/views", json={"title": title, "spec": spec})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def test_ui_absent_by_default(self) -> None:
        created = self._create("Plain", {"kind": "lore", "expr": {"tagged": "x"}})
        self.assertIsNone(created.get("ui"))
        self.assertFalse(created.get("system"))

    def test_put_ui_roundtrips_collapsed_and_ships_on_list(self) -> None:
        created = self._create("Folded", {"kind": "lore", "expr": {"tagged": "x"}})
        keys = ["node:a1", "group:type:lore:character"]
        res = self.client.put(f"/api/views/{created['id']}/ui", json={"ui": {"collapsed": keys}})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["ui"]["collapsed"], keys)

        got = self.client.get(f"/api/views/{created['id']}")
        self.assertEqual(got.json()["ui"]["collapsed"], keys)
        # Summary ships the ui so a pane seeds collapse without a per-view fetch.
        listed = self.client.get("/api/views").json()["entries"]
        self.assertEqual(next(v for v in listed if v["id"] == created["id"])["ui"]["collapsed"], keys)

    def test_put_ui_is_lock_free_and_preserves_spec(self) -> None:
        spec = {"kind": "lore", "expr": {"tagged": "x"}}
        created = self._create("Keep spec", spec)
        rev_before = self.client.get(f"/api/views/{created['id']}").json()["revision"]

        self.client.put(f"/api/views/{created['id']}/ui", json={"ui": {"collapsed": ["node:z"]}})
        after = self.client.get(f"/api/views/{created['id']}").json()
        # Spec untouched by a fold write.
        self.assertEqual(after["spec"], created["spec"])
        # A fold write is content-addressed too, but it takes NO base_revision —
        # it never 409s. Prove it accepts a write with no revision guard.
        self.assertNotEqual(after["revision"], rev_before)  # ui blob changed the file

    def test_save_view_preserves_existing_ui(self) -> None:
        created = self._create("Edit me", {"kind": "lore", "expr": {"tagged": "x"}})
        self.client.put(f"/api/views/{created['id']}/ui", json={"ui": {"collapsed": ["node:keep"]}})
        # A spec save (Edit) must not wipe fold state (independent lifecycle).
        res = self.client.put(
            f"/api/views/{created['id']}",
            json={"title": "Edit me", "spec": {"kind": "lore", "expr": {"tagged": "y"}}},
        )
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["spec"]["expr"]["tagged"], "y")
        self.assertEqual(res.json()["ui"]["collapsed"], ["node:keep"])

    def test_empty_collapsed_drops_the_ui_blob(self) -> None:
        created = self._create("Emptyable", {"kind": "lore", "expr": {"tagged": "x"}})
        self.client.put(f"/api/views/{created['id']}/ui", json={"ui": {"collapsed": ["node:a"]}})
        self.client.put(f"/api/views/{created['id']}/ui", json={"ui": {"collapsed": []}})
        self.assertIsNone(self.client.get(f"/api/views/{created['id']}").json().get("ui"))

    def test_system_view_rejects_spec_edit_but_allows_ui(self) -> None:
        # Hand-write a system view file (materialization is a later slice; the
        # read-only guard must already hold so a system default can't be edited).
        views_dir = self.root / "views"
        views_dir.mkdir(parents=True, exist_ok=True)
        (views_dir / "view_default_lore.md").write_text(
            "---\n"
            "id: view_default_lore\n"
            "title: Default\n"
            "entry_type: view:view\n"
            "system: true\n"
            "spec:\n  kind: lore\n  expr:\n    descendants_of: lore:base\n"
            "---\n\n",
            encoding="utf-8",
        )
        got = self.client.get("/api/views/view_default_lore")
        self.assertEqual(got.status_code, 200, got.text)
        self.assertTrue(got.json()["system"])

        # Edit (spec save) is refused.
        edit = self.client.put(
            "/api/views/view_default_lore",
            json={"title": "Default", "spec": {"kind": "lore", "expr": {"tagged": "x"}}},
        )
        self.assertEqual(edit.status_code, 403, edit.text)

        # Fold state still updates, and preserves the system flag.
        ui = self.client.put("/api/views/view_default_lore/ui", json={"ui": {"collapsed": ["node:q"]}})
        self.assertEqual(ui.status_code, 200, ui.text)
        self.assertTrue(ui.json()["system"])
        self.assertEqual(ui.json()["ui"]["collapsed"], ["node:q"])

    def test_first_ui_write_materializes_system_default_view(self) -> None:
        # No file for view_default_scene yet; a fold write materializes it (§5).
        self.assertEqual(self.client.get("/api/views/view_default_scene").status_code, 404)
        res = self.client.put(
            "/api/views/view_default_scene/ui", json={"ui": {"collapsed": ["node:act1"]}}
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        # Materialized as the read-only structural default (ADR-0037 §7): a
        # recursive containment Nest over the `parent` relation, roots =
        # parentless, children = the whole scene roster.
        self.assertTrue(body["system"])
        self.assertEqual(body["spec"]["kind"], "scene")
        nest = body["spec"]["expr"]["nest"]
        self.assertTrue(nest["recursive"])
        self.assertEqual(nest["match"], {"field": "parent", "direction": "child_to_parent", "by": "ref"})
        self.assertEqual(nest["parents"]["field"]["key"], "parent")
        self.assertEqual(nest["parents"]["field"]["op"], "unset")
        self.assertEqual(nest["children"]["descendants_of"], "scene:base")
        self.assertNotIn("presentation", body)
        self.assertEqual(body["ui"]["collapsed"], ["node:act1"])

    def test_materialized_lore_default_groups_by_entry_type(self) -> None:
        # ADR-0037 §7: the Lore default is a real grouped view — the whole-kind
        # roster with a group_by entry_type level (alphabetical labels) — not a
        # flat spec the pane re-shapes.
        res = self.client.put(
            "/api/views/view_default_lore/ui", json={"ui": {"collapsed": ["group:x"]}}
        )
        self.assertEqual(res.status_code, 200, res.text)
        body = res.json()
        self.assertEqual(body["spec"]["expr"]["descendants_of"], "lore:base")
        self.assertEqual(body["spec"]["group_by"], [{"field": "entry_type", "order": "label"}])

    def test_group_by_and_orphans_round_trip_through_create_and_read(self) -> None:
        # ADR-0037 group_by + ADR-0028 Amendment 1 (#260): the nest's orphan output
        # is a first-class node-set — the Nest carries an `id` and a second group
        # references it via `{"orphans_of": id}`. Both survive create → read (the
        # backend never evaluates them; the scalar keep/drop is retired).
        spec = {
            "kind": "lore",
            "groups": [
                {
                    "name": "Placed",
                    "expr": {
                        "nest": {
                            "id": "cities",
                            "parents": {"type": "lore:location"},
                            "children": {"descendants_of": "lore:base"},
                            "match": {"field": "located_in", "direction": "child_to_parent", "by": "ref"},
                        }
                    },
                },
                {"name": "Orphans", "expr": {"orphans_of": "cities"}},
            ],
            "group_by": [{"field": "entry_type"}],
        }
        created = self._create("Paris view", spec)
        got = self.client.get(f"/api/views/{created['id']}").json()
        self.assertEqual(got["spec"]["group_by"], [{"field": "entry_type", "order": None}])
        # The Nest id and the orphans reference survive, still consistent.
        self.assertEqual(got["spec"]["groups"][0]["expr"]["nest"]["id"], "cities")
        self.assertEqual(got["spec"]["groups"][1]["expr"]["orphans_of"], "cities")

    def test_materialized_default_is_listed_and_reused_on_next_write(self) -> None:
        self.client.put("/api/views/view_default_scene/ui", json={"ui": {"collapsed": ["node:a"]}})
        listed = self.client.get("/api/views").json()["entries"]
        defaults = [v for v in listed if v["id"] == "view_default_scene"]
        self.assertEqual(len(defaults), 1)
        self.assertTrue(defaults[0]["system"])
        # A second fold write reuses the existing node (no duplicate file).
        self.client.put("/api/views/view_default_scene/ui", json={"ui": {"collapsed": ["node:b"]}})
        listed2 = self.client.get("/api/views").json()["entries"]
        self.assertEqual(len([v for v in listed2 if v["id"] == "view_default_scene"]), 1)
        self.assertEqual(
            self.client.get("/api/views/view_default_scene").json()["ui"]["collapsed"], ["node:b"]
        )

    def test_default_view_for_unknown_kind_is_422(self) -> None:
        res = self.client.put(
            "/api/views/view_default_nonsense/ui", json={"ui": {"collapsed": ["x"]}}
        )
        self.assertEqual(res.status_code, 422, res.text)


if __name__ == "__main__":
    unittest.main()
