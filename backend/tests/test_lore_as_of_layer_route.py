"""GET /api/lore/{id}?layer_id=... (#2189): the "Editing at" rail picker's
read, over the wire. `read_lore_entry(as_of_layer_id=...)` itself is covered
service-level in `test_layer_overrides.py`; this pins the route plumbing —
the query param reaches the service and an unknown id still 422s through
`translate_errors`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from layer_fixtures import declare_full_chain
from project_fixtures import bind_test_project

from app.main import app
from app.models import LoreEntry, SaveLoreEntryRequest
from app.scope import WorkScope
from app.services.project_service import ProjectService


class LoreAsOfLayerRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        declare_full_chain(self.service, self.root, self.base)
        declare_full_chain(ProjectService(WorkScope(root=self.series)), self.series, self.base)
        self.service._write_yaml(
            self.base / "metadata.schema.yaml",
            {
                "version": 1,
                "fields": {"rank": {"name": "rank", "type": "text", "label": "Rank"}},
                "entry_types": {"lore:character": {"fields": ["rank"]}},
            },
        )
        bind_test_project(self.service)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _layer_id(self, folder: Path) -> str:
        return next(layer.id for layer in self.service.collect_layers(self.root) if layer.folder == folder)

    def _write_lore_at(self, folder: Path, node_id: str, title: str, metadata: dict) -> None:
        writer = ProjectService(WorkScope(root=folder))
        writer._write_lore_entry_file(
            folder / "lore" / f"{node_id}.md",
            LoreEntry(
                id=node_id, title=title, body="Body.", revision="", entry_type="lore:character", metadata=metadata
            ),
        )

    def test_layer_id_query_param_returns_the_as_of_view(self) -> None:
        self._write_lore_at(self.universe, "honor", "Honor Harrington", {"rank": "Ensign"})
        self.service.save_lore_entry(
            "honor",
            SaveLoreEntryRequest(
                title="Honor Harrington", body="Body.", entry_type="lore:character",
                metadata={"rank": "Captain"}, authoring_layer_id=self._layer_id(self.root),
            ),
        )

        default = self.client.get("/api/lore/honor")
        self.assertEqual(default.status_code, 200, default.text)
        self.assertEqual(default.json()["metadata"]["rank"], "Captain")

        as_owner = self.client.get(
            "/api/lore/honor", params={"layer_id": self._layer_id(self.universe)}
        )
        self.assertEqual(as_owner.status_code, 200, as_owner.text)
        self.assertEqual(as_owner.json()["metadata"]["rank"], "Ensign")
        self.assertEqual(as_owner.json()["overridden_fields"], [])

    def test_an_unknown_layer_id_422s(self) -> None:
        self._write_lore_at(self.universe, "honor", "Honor Harrington", {"rank": "Ensign"})
        response = self.client.get("/api/lore/honor", params={"layer_id": "not-a-layer"})
        self.assertEqual(response.status_code, 422, response.text)


if __name__ == "__main__":
    unittest.main()
