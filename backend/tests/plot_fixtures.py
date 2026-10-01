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


class PlotTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve() / "project"
        self.service = open_test_project(self.root, "Plot Tests")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

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
