from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain

from app.models import CreateSceneRequest
from app.services.project_service import ProjectService


class MetadataValidationBase(unittest.TestCase):
    """Shared scaffolding (setUp/tearDown + helpers) for the metadata
    validation test suites split out of the former monolith."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "universe"
        self.world = self.universe / "series"
        self.root = self.world / "test"
        self.service = ProjectService.created_at(self.root, "Test Project")
        self._set_projects_base_folder(self.base)
        # `home_place` is a built-in entity_ref field on Character (#1316);
        # tests that exercise validation / ref-graph behaviour use it directly.
        first_scene_path = next((self.root / "scenes").glob("*.md"))
        self.scene_id = self.service._read_front_matter_only(
            first_scene_path, strict=True
        )["id"]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _set_projects_base_folder(self, path: Path) -> None:
        declare_full_chain(self.service, self.root, path)

    def _first_scene_id(self) -> str:
        first_scene_path = next((self.root / "scenes").glob("*.md"))
        return self.service._read_front_matter_only(first_scene_path, strict=True)["id"]

    def _make_create_scene(self, title: str, parent_id: str | None = None):

        return CreateSceneRequest(title=title, parent_id=parent_id)

    def _add_clearable_fields(self, root: Path, entry_type: str) -> None:
        # One stored field of each awkward-to-unset type (#522). `flagged` carries
        # a default so we can prove clearing does NOT re-seed it.
        schema_path = root / "metadata.schema.yaml"
        data = self.service._read_yaml(schema_path)
        fields = data.setdefault("fields", {})
        fields["flagged"] = {"name": "Flagged", "type": "boolean", "default": True}
        fields["rank"] = {"name": "Rank", "type": "number"}
        fields["tier"] = {
            "name": "Tier",
            "type": "select",
            "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
        }
        tdef = data["entry_types"].get(entry_type) or {}
        existing = list(tdef.get("fields") or [])
        for key in ("flagged", "rank", "tier"):
            if key not in existing:
                existing.append(key)
        tdef["fields"] = existing
        data["entry_types"][entry_type] = tdef
        self.service._write_yaml(schema_path, data)

    def _project_layer_id(self) -> str:
        return next(
            layer.id
            for layer in self.service.read_metadata_schema_layers().layers
            if layer.folder_path == str(self.root)
        )
