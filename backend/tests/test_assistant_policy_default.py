"""ADR-0073 S2: `resolve_assistant(None)` skips a listed candidate whose SET
provider the project's resolved policy forbids, rather than handing back
whatever sorts first in `.order.yaml` regardless of whether a send through it
would even be permitted. Mirrors the rule `_policy_allows` already enforces on
an explicit provider/model pick (`services/ai/providers.py`), reused here via
the public `policy_permits`.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from project_fixtures import open_test_project

from app.models import UpdateProjectSettingsRequest
from app.services import machine_settings as ms


class DefaultAssistantPolicyTests(unittest.TestCase):
    """A cloud assistant ("cloud") is listed above a local one ("local") in
    the same `.order.yaml`; only the project's resolved policy differs across
    the three tests below."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "project"
        self.service = open_test_project(self.root, "Policy Default Tests")
        self.config_dir = Path(self.temp_dir.name) / "config"
        self.config_dir.mkdir()
        self._patcher = patch(
            "app.services.machine_settings.config_path",
            return_value=self.config_dir / "config.yaml",
        )
        self._patcher.start()
        folder = self.config_dir / "assistants"
        folder.mkdir(parents=True)
        (folder / "cloud.md").write_text(
            "---\n"
            "id: cloud\n"
            "title: Cloud drafting\n"
            "entry_type: assistant\n"
            "metadata:\n"
            "  ai_provider: anthropic\n"
            "  ai_model: claude-sonnet-4-6\n"
            "---\n",
            encoding="utf-8",
        )
        (folder / "local.md").write_text(
            "---\n"
            "id: local\n"
            "title: Local drafting\n"
            "entry_type: assistant\n"
            "metadata:\n"
            "  ai_provider: ollama\n"
            "  ai_model: llama3\n"
            "---\n",
            encoding="utf-8",
        )
        # "cloud" is topmost — the un-gated pre-S2 default.
        (folder / ".order.yaml").write_text(
            "ids:\n- cloud\n- local\nexcluded: []\n", encoding="utf-8"
        )
        ms.save_settings(
            ms.MachineSettings(providers=ms.ProviderCredentials(anthropic_api_key="sk-ant-test"))
        )

    def tearDown(self) -> None:
        self._patcher.stop()
        self.temp_dir.cleanup()

    def _set_policy(self, policy: str) -> None:
        self.service.update_project_settings(UpdateProjectSettingsRequest(ai_policy=policy))

    def test_local_only_skips_the_topmost_cloud_assistant(self) -> None:
        self._set_policy("local-only")
        result = self.service.resolve_assistant(None)
        assert result is not None
        self.assertEqual(result.id, "local")

    def test_cloud_allowed_returns_the_topmost(self) -> None:
        self._set_policy("cloud-allowed")
        result = self.service.resolve_assistant(None)
        assert result is not None
        self.assertEqual(result.id, "cloud")

    def test_off_returns_none(self) -> None:
        self._set_policy("off")
        self.assertIsNone(self.service.resolve_assistant(None))


if __name__ == "__main__":
    unittest.main()
