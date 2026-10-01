"""Shared base for the `plot` kind's HTTP test suites.

`PlotTestCase` opens a fresh temp project, binds it as the wire scope (so
`TestClient` requests resolve it), and hands back both the `ProjectService` and a
`TestClient`. Extracted from `test_plot.py` so the beat/template/instance suites
(`test_plot_beats.py`) and the card/link suites (`test_plot_card_links.py`) share
one base instead of each re-declaring it. Imported top-level (`from plot_fixtures
import PlotTestCase`), matching `project_fixtures` / `layer_fixtures`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from project_fixtures import open_test_project

from app.main import app
from app.models import AttachCardRequest, CardEntry, SaveCardRequest


class PlotTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Plot Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def save_card_written(self, card_id: str, request: SaveCardRequest) -> CardEntry:
        """What `save_card` with a `scene` in its metadata used to do: save the card,
        then attach the scene through the endpoint that owns it now (ADR-0097 §1).
        The card's body wins a text conflict, so it becomes the scene's summary."""
        scene_id = request.metadata.get("scene")
        metadata = {key: value for key, value in request.metadata.items() if key != "scene"}
        saved = self.service.save_card(card_id, request.model_copy(update={"metadata": metadata}))
        if not scene_id:
            return saved
        return self.service.attach_card(card_id, AttachCardRequest(scene_id=str(scene_id), text="card"))

    def plant_duplicate_scene(self, card_id: str, scene_id: str) -> None:
        """Give a card a scene another card already holds by writing its file
        directly — the pre-v15 state the migration cleans up (ADR-0097 §10), which
        the save path itself no longer lets a test reach."""
        card = self.service.read_card(card_id)
        self.service._write_node_entry_file(
            self.service._path_for_node_id(card_id, "plot"),
            card_id,
            card.title,
            card.entry_type,
            {**card.metadata, "scene": scene_id},
            card.body,
        )
