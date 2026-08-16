"""Project-node authored fields resolve over the declared chain (#317).

The channel #317 is about: a value set on a *world* — its measurement system,
tense, spelling — must reach every book beneath it, and a prompt template must
be able to read it as `{{ project.metadata.<field> }}`. The mechanism is the
authored-fields twin of the #312 AI-policy walk: nearest-explicit-wins over the
layer chain, **per key**, with absence meaning "inherit". These tests pin that
fold and the template channel it feeds.

Staged like `test_ai_policy_chain`: a universe › book chain, fully declared.
Where the policy tests write into each layer's `project.yaml`, these write into
each layer's `project.md` — the authored node, not the manifest.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml
from layer_fixtures import declare, declare_full_chain, make_project_folder
from project_fixtures import open_test_project

from app.services.ai.preview import PreviewRequest, build_preview
from app.services.ai.templates import create_environment, render_template


def _seeded_scene_id(root: Path) -> str:
    """The id of the scene `_scaffold_new_project` seeds, read off disk."""
    scene_file = next((root / "scenes").glob("*.md"))
    front_matter = scene_file.read_text(encoding="utf-8").split("---")[1]
    return str(yaml.safe_load(front_matter)["id"])


def _set_project_metadata(folder: Path, metadata: dict[str, Any]) -> None:
    """Write `folder`'s `project.md` with the given authored metadata.

    Direct file write rather than `save_project_node`, which only operates on the
    *open* project — an ancestor's node has no open scope of its own. Only the
    front-matter `metadata` block matters to the fold; a minimal id/title keeps
    the file honest without pulling in the collector.
    """
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


class ProjectNodeChainTests(unittest.TestCase):
    """A two-level chain: universe › book, fully declared."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.universe = self.base / "universe"
        self.book = self.universe / "book"
        self.service = open_test_project(self.book, "Book")
        make_project_folder(self.service, self.universe, "Universe")
        declare_full_chain(self.service, self.book, self.base)

    def _resolved(self) -> dict[str, Any]:
        return self.service._resolved_project_node_metadata(self.book)

    # ----- the fold -----------------------------------------------------

    def test_ancestor_field_reaches_a_book_that_leaves_it_absent(self) -> None:
        """The feature: set units once on the universe, every book inherits."""
        _set_project_metadata(self.universe, {"measurement_system": "metric"})
        self.assertEqual(self._resolved()["measurement_system"], "metric")

    def test_a_nearer_layer_wins_per_key(self) -> None:
        """Nearest explicit statement wins — and only for the key it states."""
        _set_project_metadata(self.universe, {"measurement_system": "metric", "tense": "past"})
        _set_project_metadata(self.book, {"measurement_system": "imperial", "pov_mode": "first"})
        resolved = self._resolved()
        # Book overrides units, inherits tense, contributes its own POV.
        self.assertEqual(resolved["measurement_system"], "imperial")
        self.assertEqual(resolved["tense"], "past")
        self.assertEqual(resolved["pov_mode"], "first")

    def test_a_key_no_layer_states_is_absent(self) -> None:
        """Absence is not a default: an unstated key never appears."""
        _set_project_metadata(self.universe, {"measurement_system": "metric"})
        self.assertNotIn("spelling", self._resolved())

    def test_current_project_metadata_exposes_the_resolved_fold(self) -> None:
        """The envelope path: `project.metadata` on `ProjectInfo` is the fold."""
        _set_project_metadata(self.universe, {"measurement_system": "metric"})
        self.assertEqual(self.service.current_project().metadata["measurement_system"], "metric")

    # ----- the template channel -----------------------------------------

    def test_a_template_resolves_an_inherited_project_field(self) -> None:
        """End to end: `{{ project.metadata.<field> }}` renders the world value."""
        _set_project_metadata(self.universe, {"measurement_system": "metric"})
        context = {"project": self.service.current_project()}
        rendered = render_template(
            '{% role "system" %}Measurements are {{ project.metadata.measurement_system }}.{% endrole %}',
            context,
            env=create_environment(),
        )
        self.assertIn("Measurements are metric.", rendered.messages[0].text)

    def test_build_preview_resolves_an_inherited_field(self) -> None:
        """Through the REAL builder: `preview.py` binds `project = current_project()`,
        so an ancestor's field reaches a rendered prompt — the actual AI channel,
        not a hand-built context."""
        _set_project_metadata(self.universe, {"measurement_system": "metric"})
        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=(
                    '{% role "system" %}{% if "measurement_system" in project.metadata %}'
                    "Use {{ project.metadata.measurement_system }} units.{% endif %}{% endrole %}"
                ),
                target_scene_id=_seeded_scene_id(self.book),
                session_id=None,
                inputs={},
                text_before="",
                text_after="",
                commit=False,
            ),
        )
        self.assertIn("Use metric units.", rendered.messages[0].text)

    def test_the_in_guard_skips_an_unset_field(self) -> None:
        """The doc's guard pattern: an unset field renders nothing, no error."""
        # Nothing sets `tense` anywhere in the chain.
        rendered, _ = build_preview(
            self.service,
            PreviewRequest(
                template_source=(
                    '{% role "system" %}A{% if "tense" in project.metadata %}'
                    " {{ project.metadata.tense }}{% endif %}B{% endrole %}"
                ),
                target_scene_id=_seeded_scene_id(self.book),
                session_id=None,
                inputs={},
                text_before="",
                text_after="",
                commit=False,
            ),
        )
        self.assertIn("AB", rendered.messages[0].text)

    def test_a_bare_access_to_an_unset_field_raises(self) -> None:
        """The other half of the doc's promise: under StrictUndefined an
        unguarded `{{ project.metadata.tense }}` raises, so the guard is not
        optional. Pins the guidance `template-language.md` now gives."""
        from jinja2 import UndefinedError

        context = {"project": self.service.current_project()}
        with self.assertRaises(UndefinedError):
            render_template(
                '{% role "system" %}{{ project.metadata.tense }}{% endrole %}',
                context,
                env=create_environment(),
            )


class ProjectNodeFlatTests(unittest.TestCase):
    """A standalone project — a chain of length one — sees only its own fields."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve() / "solo"
        self.service = open_test_project(self.root, "Solo")

    def test_flat_project_returns_its_own_authored_metadata(self) -> None:
        _set_project_metadata(self.root, {"tense": "present"})
        self.assertEqual(
            self.service._resolved_project_node_metadata(self.root)["tense"],
            "present",
        )

    def test_a_hand_edited_yaml_date_does_not_break_the_route(self) -> None:
        """A YAML date scalar in project.md is outside `MetadataValue`; unguarded
        it would 500 `current_project()`. It must survive as its ISO string —
        `project.md` is hand-editable and one bad value cannot make a project
        unopenable (the `_stated_ai_policy` guarantee, extended to the node)."""
        # An unquoted ISO date round-trips through yaml.safe_load as datetime.date.
        (self.root / "project.md").write_text(
            "---\nid: project_solo\ntitle: Solo\nentry_type: project:project\n"
            "metadata:\n  published: 2020-01-01\n  history:\n    - 1999-12-31\n---\n\n",
            encoding="utf-8",
        )
        info = self.service.current_project()
        self.assertEqual(info.metadata["published"], "2020-01-01")
        self.assertEqual(info.metadata["history"], ["1999-12-31"])


class ProjectNodeThreeLevelTests(unittest.TestCase):
    """universe › series › book — the design's actual depth (§3). A middle
    layer's override must reach the book, and the book must still override it."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name).resolve()
        self.universe = self.base / "universe"
        self.series = self.universe / "series"
        self.book = self.series / "book"
        self.service = open_test_project(self.book, "Book")
        make_project_folder(self.service, self.universe, "Universe")
        make_project_folder(self.service, self.series, "Series")
        declare(self.service, self.book, [self.universe, self.series], base=self.base)

    def test_a_middle_layer_override_reaches_the_book(self) -> None:
        _set_project_metadata(self.universe, {"measurement_system": "metric", "tense": "past"})
        _set_project_metadata(self.series, {"tense": "present"})  # series overrides universe
        resolved = self.service._resolved_project_node_metadata(self.book)
        self.assertEqual(resolved["measurement_system"], "metric")  # from the universe
        self.assertEqual(resolved["tense"], "present")  # the nearer series wins

    def test_the_book_still_overrides_a_middle_layer(self) -> None:
        _set_project_metadata(self.series, {"tense": "present"})
        _set_project_metadata(self.book, {"tense": "past"})
        self.assertEqual(
            self.service._resolved_project_node_metadata(self.book)["tense"],
            "past",  # the book is nearest of all
        )
