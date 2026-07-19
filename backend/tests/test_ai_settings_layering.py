"""AI settings resolve over the project hierarchy chain (#312, ADR-0039 slice F).

`settings.ai` in `project.yaml` used to be read from the open project's folder
only. It now walks the same ancestor chain as the metadata schema and the node
index — outermost first, nearer layers overriding farther ones — so a universe
can set an AI policy that its books inherit.

Two consequences carry their own tests here, because without either the feature
does not actually work:

* a new project no longer seeds an `ai` block (a stored value shadows the chain,
  so a seeded `policy: "off"` would make inheritance unreachable), and
* `update_project_settings` writes *sparsely* — a value matching the inherited
  resolution is stored as nothing, so the settings pane round-tripping resolved
  values cannot freeze them into the book and sever inheritance.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from app.models import UpdateProjectSettingsRequest
from app.services.project_service import ProjectService


class AiSettingsLayeringTests(unittest.TestCase):
    """Layout: <base>/universe/series/book, `book` is the open project."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name) / "writing"
        self.universe = self.base / "universe"
        self.series = self.universe / "series"
        self.root = self.series / "book"
        self.service = ProjectService()
        self.service.create_project(self.root, "Book")
        self._patch_manifest(self.root, lambda settings: settings.__setitem__("projects_base_folder", str(self.base)))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -- helpers ---------------------------------------------------------

    def _patch_manifest(self, folder: Path, mutate: Any) -> None:
        manifest = self.service._read_yaml(folder / "project.yaml")
        settings = manifest.setdefault("settings", {})
        mutate(settings)
        self.service._write_yaml(folder / "project.yaml", manifest)

    def _write_layer_ai(self, folder: Path, ai: dict[str, Any]) -> None:
        """Give an ancestor folder a `project.yaml` carrying only an ai block."""
        folder.mkdir(parents=True, exist_ok=True)
        self.service._write_yaml(folder / "project.yaml", {"title": folder.name, "settings": {"ai": ai}})

    def _own_ai(self) -> dict[str, Any]:
        manifest = self.service._read_yaml(self.root / "project.yaml")
        return manifest.get("settings", {}).get("ai", {})

    # -- resolution ------------------------------------------------------

    def test_new_project_does_not_seed_an_ai_block(self) -> None:
        # A seeded block would shadow every ancestor and make inheritance dead.
        manifest = self.service._read_yaml(self.root / "project.yaml")
        self.assertNotIn("ai", manifest["settings"])

    def test_policy_defaults_to_off_when_nothing_in_the_chain_sets_it(self) -> None:
        self.assertEqual(self.service.current_project().ai_policy, "off")

    def test_policy_is_inherited_from_an_ancestor_layer(self) -> None:
        self._write_layer_ai(self.universe, {"policy": "cloud-allowed"})

        self.assertEqual(self.service.current_project().ai_policy, "cloud-allowed")

    def test_nearer_layer_overrides_farther_one(self) -> None:
        self._write_layer_ai(self.universe, {"policy": "cloud-allowed"})
        self._write_layer_ai(self.series, {"policy": "local-only"})

        self.assertEqual(self.service.current_project().ai_policy, "local-only")

    def test_open_project_overrides_every_ancestor(self) -> None:
        self._write_layer_ai(self.universe, {"policy": "cloud-allowed"})
        self._patch_manifest(self.root, lambda s: s.__setitem__("ai", {"policy": "off"}))

        self.assertEqual(self.service.current_project().ai_policy, "off")

    def test_folder_without_a_project_yaml_is_skipped_not_a_break(self) -> None:
        # `series` is a bare organizational folder; the universe still reaches
        # the book, exactly as a missing metadata.schema.yaml is skipped.
        self._write_layer_ai(self.universe, {"policy": "cloud-allowed"})

        self.assertFalse((self.series / "project.yaml").exists())
        self.assertEqual(self.service.current_project().ai_policy, "cloud-allowed")

    def test_explicit_null_at_a_layer_falls_through(self) -> None:
        self._write_layer_ai(self.universe, {"policy": "cloud-allowed"})
        self._write_layer_ai(self.series, {"policy": None})

        self.assertEqual(self.service.current_project().ai_policy, "cloud-allowed")

    def test_keys_resolve_independently_of_each_other(self) -> None:
        self._write_layer_ai(self.universe, {"policy": "cloud-allowed", "default_provider": "anthropic"})
        self._write_layer_ai(self.series, {"policy": "local-only"})

        project = self.service.current_project()
        self.assertEqual(project.ai_policy, "local-only")
        self.assertEqual(project.ai_default_provider, "anthropic")

    # -- sparse writes ---------------------------------------------------

    def test_saving_the_inherited_value_writes_no_local_override(self) -> None:
        self._write_layer_ai(self.universe, {"policy": "cloud-allowed"})

        # What the settings pane sends back after loading the resolved value.
        project = self.service.update_project_settings(UpdateProjectSettingsRequest(ai_policy="cloud-allowed"))

        self.assertEqual(project.ai_policy, "cloud-allowed")
        self.assertEqual(self._own_ai(), {})

    def test_a_non_diverged_project_follows_a_later_ancestor_change(self) -> None:
        self._write_layer_ai(self.universe, {"policy": "cloud-allowed"})
        self.service.update_project_settings(UpdateProjectSettingsRequest(ai_policy="cloud-allowed"))

        self._write_layer_ai(self.universe, {"policy": "local-only"})

        self.assertEqual(self.service.current_project().ai_policy, "local-only")

    def test_saving_a_divergent_value_is_recorded(self) -> None:
        self._write_layer_ai(self.universe, {"policy": "cloud-allowed"})

        project = self.service.update_project_settings(UpdateProjectSettingsRequest(ai_policy="off"))

        self.assertEqual(project.ai_policy, "off")
        self.assertEqual(self._own_ai(), {"policy": "off"})

    def test_returning_to_the_inherited_value_removes_the_override(self) -> None:
        self._write_layer_ai(self.universe, {"policy": "cloud-allowed"})
        self.service.update_project_settings(UpdateProjectSettingsRequest(ai_policy="off"))
        self.assertEqual(self._own_ai(), {"policy": "off"})

        self.service.update_project_settings(UpdateProjectSettingsRequest(ai_policy="cloud-allowed"))

        self.assertEqual(self._own_ai(), {})

    def test_policy_matching_the_implicit_off_default_is_not_written(self) -> None:
        project = self.service.update_project_settings(UpdateProjectSettingsRequest(ai_policy="off"))

        self.assertEqual(project.ai_policy, "off")
        self.assertEqual(self._own_ai(), {})

    def test_clearing_a_field_falls_back_to_the_inherited_value(self) -> None:
        self._write_layer_ai(self.universe, {"default_provider": "anthropic"})
        self.service.update_project_settings(UpdateProjectSettingsRequest(ai_default_provider="openai"))
        self.assertEqual(self._own_ai(), {"default_provider": "openai"})

        project = self.service.update_project_settings(UpdateProjectSettingsRequest(ai_default_provider=None))

        self.assertEqual(self._own_ai(), {})
        self.assertEqual(project.ai_default_provider, "anthropic")

    def test_an_emptied_ai_block_is_dropped_from_the_manifest(self) -> None:
        self.service.update_project_settings(UpdateProjectSettingsRequest(ai_policy="local-only"))
        self.service.update_project_settings(UpdateProjectSettingsRequest(ai_policy="off"))

        manifest = self.service._read_yaml(self.root / "project.yaml")
        self.assertNotIn("ai", manifest["settings"])

    def test_unset_fields_are_left_alone(self) -> None:
        self.service.update_project_settings(UpdateProjectSettingsRequest(ai_default_provider="openai"))

        self.service.update_project_settings(UpdateProjectSettingsRequest(ai_policy="local-only"))

        self.assertEqual(self._own_ai(), {"default_provider": "openai", "policy": "local-only"})


if __name__ == "__main__":
    unittest.main()
