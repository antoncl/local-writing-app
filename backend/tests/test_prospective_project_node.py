"""The wizard's review pane resolves a not-yet-created project (#318 slice 4).

The prospective twin of `test_project_node_chain`: where that folds an *open*
project's authored fields over its declared chain, this folds them over the
wizard's *ticked* ancestors before the project — or its folder — exists. Pins
the three things the review pane consumes: the inherited values, the per-field
source that names the "Reset to <source>" target, and the merged schema (so a
`select` shows an ancestor's added vocabulary).

Staged like `test_project_node_chain` — a universe (a real project) with a book
folder that does NOT exist on disk. The declaration is passed as the ticked
ancestor paths, exactly as the location step produces them.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml
from fastapi.testclient import TestClient
from layer_fixtures import make_project_folder, set_projects_root
from project_fixtures import open_test_project

from app.main import app


def _set_project_metadata(folder: Path, metadata: dict[str, Any]) -> None:
    """Write `folder`'s `project.md` with the given authored metadata (an
    ancestor's node has no open scope, so a direct write, as in
    `test_project_node_chain`)."""
    folder.mkdir(parents=True, exist_ok=True)
    front_matter = yaml.safe_dump(
        {
            "id": f"project_{folder.name}",
            "title": folder.name,
            "entry_type": "project:project",
            "metadata": metadata,
        },
        sort_keys=False,
    )
    (folder / "project.md").write_text(f"---\n{front_matter}---\n\n", encoding="utf-8")


class ProspectiveProjectNodeTests(unittest.TestCase):
    """A universe › (prospective) book — the book folder is never created."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        set_projects_root(self.base)
        self.universe = self.base / "universe"
        # The universe is a real project; the service handle is only a way to
        # call the scope-free `prospective_project_node`.
        self.service = open_test_project(self.universe, "Universe")
        self.book = self.universe / "book"  # prospective — no manifest, no project.md

    def _resolve(self, inherits: list[str]) -> Any:
        return self.service.prospective_project_node(self.book, inherits)

    def test_an_inherited_value_reaches_the_prospective_book(self) -> None:
        """The feature: units set on the universe fill the review pane."""
        _set_project_metadata(self.universe, {"measurement_system": "metric"})
        result = self._resolve([str(self.universe)])
        self.assertEqual(result.metadata["measurement_system"], "metric")

    def test_the_source_names_the_supplying_ancestor(self) -> None:
        """`field_sources` is the "Reset to <source>" label — the layer title."""
        _set_project_metadata(self.universe, {"measurement_system": "metric"})
        result = self._resolve([str(self.universe)])
        self.assertEqual(result.field_sources["measurement_system"], "Universe")

    def test_an_unstated_key_is_absent_and_unsourced(self) -> None:
        """Absence is not a default: a key no ancestor states never appears,
        and carries no source (the pane falls to the schema default for it)."""
        _set_project_metadata(self.universe, {"measurement_system": "metric"})
        result = self._resolve([str(self.universe)])
        self.assertNotIn("spelling", result.metadata)
        self.assertNotIn("spelling", result.field_sources)

    def test_empty_inherits_is_a_flat_project(self) -> None:
        """Ticking nothing resolves no inherited values — even though the
        universe (an ancestor) states some. The declaration selects; it is not
        inferred from folder placement."""
        _set_project_metadata(self.universe, {"measurement_system": "metric"})
        result = self._resolve([])
        self.assertEqual(result.metadata, {})
        self.assertEqual(result.field_sources, {})
        # The schema is still the built-in default — the project kind is present.
        self.assertIn("project:project", result.metadata_schema.entry_types)

    def test_color_leads_the_authored_project_fields_so_it_clears_the_review_fold(self) -> None:
        """#560: the review pane renders project fields in schema order inside a
        fixed 560px frame, skipping intrinsic fields (id/title/entry_type). `color`
        is the level/inheritance cue, so it must lead the AUTHORED fields to stay
        above the fold instead of trailing off the bottom. Asserted on the
        resolved/served schema the pane actually consumes — where the intrinsics
        are prepended, so the check filters them exactly as the pane does."""
        schema = self._resolve([]).metadata_schema
        fields = schema.entry_types["project:project"].fields
        authored = [f for f in fields if not schema.fields[f].intrinsic]
        self.assertEqual(authored[0], "color")

    def test_a_non_ancestor_tick_is_dropped(self) -> None:
        """A ticked path that is not on the book's parent chain contributes
        nothing — the declaration can only select from real ancestors, never
        name its way outside them (`prospective_layers` reuses
        `ancestor_projects`)."""
        sibling = self.base / "sibling"
        make_project_folder(self.service, sibling, "Sibling")
        _set_project_metadata(sibling, {"tense": "past"})
        result = self._resolve([str(sibling)])
        self.assertNotIn("tense", result.metadata)

    def test_the_merged_schema_carries_an_ancestor_layer_field(self) -> None:
        """The schema is folded over the ticked chain, so a field an ancestor
        adds in its own `metadata.schema.yaml` reaches the review pane — which
        is what lets a `select` show the real vocabulary."""
        self.service._write_yaml(
            self.universe / "metadata.schema.yaml",
            {"version": 1, "fields": {"world_flag": {"name": "World Flag", "type": "text"}}},
        )
        result = self._resolve([str(self.universe)])
        self.assertIn("world_flag", result.metadata_schema.fields)

    def test_the_ancestor_field_is_absent_when_not_ticked(self) -> None:
        """The schema merge honours the tick too: the universe's added field is
        gone from a flat declaration."""
        self.service._write_yaml(
            self.universe / "metadata.schema.yaml",
            {"version": 1, "fields": {"world_flag": {"name": "World Flag", "type": "text"}}},
        )
        result = self._resolve([])
        self.assertNotIn("world_flag", result.metadata_schema.fields)


class ProspectiveThreeLevelTests(unittest.TestCase):
    """universe › series › (prospective) book — a nearer ancestor must win, and
    the source must name the layer that actually supplied each value."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        set_projects_root(self.base)
        self.universe = self.base / "universe"
        self.series = self.universe / "series"
        self.service = open_test_project(self.universe, "Universe")
        make_project_folder(self.service, self.series, "Series")
        self.book = self.series / "book"  # prospective

    def test_a_nearer_ancestor_wins_per_key_with_the_right_source(self) -> None:
        _set_project_metadata(self.universe, {"measurement_system": "metric", "tense": "past"})
        _set_project_metadata(self.series, {"tense": "present"})  # series overrides universe
        result = self.service.prospective_project_node(
            self.book, [str(self.universe), str(self.series)]
        )
        self.assertEqual(result.metadata["measurement_system"], "metric")
        self.assertEqual(result.metadata["tense"], "present")
        self.assertEqual(result.field_sources["measurement_system"], "Universe")
        self.assertEqual(result.field_sources["tense"], "Series")


class ProspectiveProjectNodeRouteTests(unittest.TestCase):
    """The endpoint round-trips through FastAPI — the route wiring and, notably,
    the `MetadataSchema` response serialization the service tests never exercise."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        set_projects_root(self.base)
        self.universe = self.base / "universe"
        # A bound project so `CurrentProject` resolves; the endpoint ignores the
        # scope and answers from the request path, like `prospective_ancestor_candidates`.
        self.service = open_test_project(self.universe, "Universe")
        _set_project_metadata(self.universe, {"measurement_system": "metric"})
        self.book = self.universe / "book"

    def test_the_route_resolves_inherited_fields_and_a_serialized_schema(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/project/prospective-node",
                json={"root_path": str(self.book), "inherits": [str(self.universe)]},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["metadata"]["measurement_system"], "metric")
        self.assertEqual(body["field_sources"]["measurement_system"], "Universe")
        # The merged schema survives the response model with its project kind.
        self.assertIn("project:project", body["metadata_schema"]["entry_types"])

    def test_the_route_defaults_inherits_and_returns_a_flat_result(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/project/prospective-node",
                json={"root_path": str(self.book)},  # inherits omitted → []
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["metadata"], {})
        self.assertEqual(body["field_sources"], {})
        self.assertIn("project:project", body["metadata_schema"]["entry_types"])


class ProspectiveAiPolicyTests(unittest.TestCase):
    """The wizard's AI step resolves the policy a not-yet-created project would
    inherit over the ticked chain, plus its provenance (#1672)."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        set_projects_root(self.base)
        self.universe = self.base / "universe"
        self.series = self.universe / "series"
        self.service = open_test_project(self.universe, "Universe")
        make_project_folder(self.service, self.series, "Series")
        self.book = self.series / "book"  # prospective — no manifest yet

    def _set_policy(self, folder: Path, policy: str) -> None:
        """Write `settings.ai.policy` into an ancestor's manifest directly (an
        ancestor has no open scope, as in the metadata tests above)."""
        manifest = self.service._read_yaml(folder / "project.yaml")
        manifest.setdefault("settings", {}).setdefault("ai", {})["policy"] = policy
        self.service._write_yaml(folder / "project.yaml", manifest)

    def test_inherited_policy_names_its_source(self) -> None:
        self._set_policy(self.universe, "cloud-allowed")
        result = self.service.prospective_ai_policy(
            self.book, [str(self.universe), str(self.series)]
        )
        self.assertEqual(result.policy, "cloud-allowed")
        self.assertEqual(result.source, "Universe")

    def test_a_nearer_ancestor_wins_and_sources_to_it(self) -> None:
        self._set_policy(self.universe, "cloud-allowed")
        self._set_policy(self.series, "local-only")  # series overrides universe
        result = self.service.prospective_ai_policy(
            self.book, [str(self.universe), str(self.series)]
        )
        self.assertEqual(result.policy, "local-only")
        self.assertEqual(result.source, "Series")

    def test_no_stated_policy_is_the_app_default_with_no_source(self) -> None:
        # Nobody up the chain states a policy → the app-global default, and no
        # source (it isn't an ancestor's doing) so the step can say "app default".
        result = self.service.prospective_ai_policy(
            self.book, [str(self.universe), str(self.series)]
        )
        self.assertIsNone(result.source)

    def test_the_declaration_selects_an_unticked_ancestor_policy_is_dropped(self) -> None:
        self._set_policy(self.universe, "cloud-allowed")
        result = self.service.prospective_ai_policy(self.book, [])
        self.assertIsNone(result.source)

    def test_the_route_round_trips(self) -> None:
        self._set_policy(self.universe, "cloud-allowed")
        with TestClient(app) as client:
            response = client.post(
                "/api/project/prospective-ai-policy",
                json={"root_path": str(self.book), "inherits": [str(self.universe)]},
            )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["policy"], "cloud-allowed")
        self.assertEqual(body["source"], "Universe")


if __name__ == "__main__":
    unittest.main()
