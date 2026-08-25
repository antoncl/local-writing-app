"""#1402 — the first-run create wizard hires assistants with NO project open
(the wizard has no project of its own yet). The machine-global assistant
create/save path must resolve its schema from the built-in (machine-layer)
schema instead of 409ing "No project is open"."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.models import CreateAssistantEntryRequest, SaveAssistantEntryRequest
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


class MachineHireWithNoProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        # Isolate machine-global config so the test never touches the real
        # %APPDATA% roster (tests-isolate-machine-config, #1358).
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def test_create_then_save_assistant_with_no_project_open(self) -> None:
        service = ProjectService()  # unbound — root_path is None (first-run wizard)
        self.assertIsNone(service.root_path)

        created = service.create_assistant_entry(
            CreateAssistantEntryRequest(
                title="My Assistant", entry_type="assistant:assistant", layer_id=""
            )
        )
        self.assertEqual(created.title, "My Assistant")
        # It landed in the machine roster (config dir), not a project.
        machine_files = list((self.config_dir / "assistants").glob("*.md"))
        self.assertEqual(len(machine_files), 1)

        # The wizard's follow-up save stamps provider/tier/model — also unbound.
        saved = service.save_assistant_entry(
            created.id,
            SaveAssistantEntryRequest(
                title=created.title,
                entry_type="assistant:assistant",
                metadata={
                    "ai_provider": "ollama",
                    "ai_capability_tier": "local",
                    "ai_model": "llama3",
                },
            ),
        )
        self.assertEqual(saved.metadata.get("ai_provider"), "ollama")
        self.assertEqual(saved.metadata.get("ai_model"), "llama3")

    def test_shared_kind_check_still_requires_a_project(self) -> None:
        # The built-in fallback is scoped to the assistant write path via an
        # explicit schema. The shared guard (no schema passed) still 409s when
        # unbound, so a project-scoped create is not silently allowed with no
        # project open.
        service = ProjectService()
        with self.assertRaises(ProjectServiceError) as ctx:
            service._check_entry_type_kind("lore:base", "lore")
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
