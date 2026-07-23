"""Inheritance is declared, not inferred (#309 / ADR-0039 Amendment 1).

The candidate set is the filesystem walk — finite and cycle-free by
construction, which is why a user-editable `parent:` link was rejected — and
`project.yaml`'s `inherits:` selects from it. Two properties carry the design:

- the declaration can only ever **narrow** the enumeration, never reach past
  the configured base folder;
- a layer is a **project**, so a folder with no manifest cannot become one —
  there would be no name to show for it either.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from layer_fixtures import declare, make_project_folder
from project_fixtures import bind_test_project

from app.main import app
from app.models import UpdateProjectSettingsRequest
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


class DeclaredChainTestCase(unittest.TestCase):
    """base(writing) / universe(honorverse) / series(honor-harrington) / book01."""

    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.root = self.series / "book01"
        self.service = ProjectService.created_at(self.root, "Book 1")
        self.service = ProjectService.opened_at(self.root)
        self._set_base(self.base)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _set_base(self, folder: Path) -> None:
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest.setdefault("settings", {})["projects_base_folder"] = str(folder)
        self.service._write_yaml(self.root / "project.yaml", manifest)

    def _layer_folders(self) -> list[Path]:
        return [layer.folder for layer in self.service.collect_layers(self.root)]


class AnAbsentDeclarationInheritsNothingTests(DeclaredChainTestCase):
    def test_a_project_that_declares_nothing_is_flat(self) -> None:
        """The decision, pinned explicitly.

        Every project on disk predates the key, so this is the upgrade path for
        all of them. "Absent means inherit everything" was rejected: folder
        placement would still decide and the declaration would only ever let
        you opt *out*, which is inference wearing a declaration's clothes.
        """
        self.assertEqual(self._layer_folders(), [self.root])

    def test_an_empty_declaration_is_the_same_as_none(self) -> None:
        declare(self.service, self.root, [])
        self.assertEqual(self._layer_folders(), [self.root])


class TheDeclarationSelectsFromTheWalkTests(DeclaredChainTestCase):
    def test_declared_ancestors_become_layers_outermost_first(self) -> None:
        declare(self.service, self.root, [self.universe, self.series])
        self.assertEqual(self._layer_folders(), [self.universe, self.series, self.root])

    def test_a_gap_is_legal(self) -> None:
        """Declaring a grandparent without its parent is a recorded choice.

        It stays legal because membership is tested per candidate — nothing
        reads an ancestor's own declaration, so each project's list is the
        complete answer for itself.
        """
        declare(self.service, self.root, [self.universe])
        self.assertEqual(self._layer_folders(), [self.universe, self.root])

    def test_the_open_project_is_never_subject_to_the_declaration(self) -> None:
        declare(self.service, self.root, [self.series])
        self.assertIn(self.root, self._layer_folders())

    def test_a_folder_outside_the_base_cannot_be_declared_into_the_chain(self) -> None:
        """The bound the walk exists to guarantee.

        `writing`'s parent is a real folder and a plausible thing to name, so
        the declaration is the obvious way to try to reach past the configured
        base. It must not work, or `projects_base_folder` stops being a bound.
        """
        outside = self.base.parent
        make_project_folder(self.service, outside)
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest["inherits"] = ["../../../.."]
        self.service._write_yaml(self.root / "project.yaml", manifest)

        self.assertEqual(self._layer_folders(), [self.root])
        self.assertTrue(
            any("not an ancestor" in warning for warning in self.service.declared_ancestor_warnings(self.root))
        )

    def test_a_declared_entry_that_is_not_a_project_is_not_a_layer_and_says_so(self) -> None:
        """A layer is a project. Without a manifest there is no project, and no
        title to show for it either.

        It must **not** be silent: the entry is a legitimate row in the
        enumeration, so the not-an-ancestor check passes it, and the author
        ticked something and got nothing. The case that matters is a folder
        that *was* a project and stopped being one.
        """
        self.universe.mkdir(parents=True, exist_ok=True)
        manifest = self.service._read_yaml(self.root / "project.yaml")
        manifest["inherits"] = ["../.."]
        self.service._write_yaml(self.root / "project.yaml", manifest)

        self.assertEqual(self._layer_folders(), [self.root])
        self.assertTrue(
            any("is not a project" in warning for warning in self.service.declared_ancestor_warnings(self.root))
        )
        self.assertTrue(
            any("is not a project" in warning for warning in self.service.validate_project().warnings)
        )


class TheEnumerationIsReportedWholeTests(DeclaredChainTestCase):
    def test_every_ancestor_is_listed_with_its_state(self) -> None:
        make_project_folder(self.service, self.universe)
        self.series.mkdir(parents=True, exist_ok=True)  # organisational, no manifest
        declare(self.service, self.root, [self.universe])

        info = self.service.current_project()

        self.assertEqual(
            [(row.name, row.is_project, row.inherited) for row in info.ancestors],
            [("writing", False, False), ("honorverse", True, True), ("honor-harrington", False, False)],
        )

    def test_an_ancestor_that_is_a_project_carries_its_title_and_the_rest_carry_none(self) -> None:
        """The breadcrumb (#311) renders one path, so it needs one naming scheme.

        `name` is the folder and stays the folder — the wizard addresses rows by
        it. `title` is what a *project* calls itself, which is the same rule the
        layer labels already follow, and it is `None` rather than the folder for
        a non-project so that "there is nothing to display here" cannot be
        mistaken for a project named after its directory.
        """
        make_project_folder(self.service, self.universe, "The Honorverse")
        self.series.mkdir(parents=True, exist_ok=True)  # organisational, no manifest
        declare(self.service, self.root, [self.universe])

        self.assertEqual(
            [(row.name, row.title) for row in self.service.current_project().ancestors],
            [("writing", None), ("honorverse", "The Honorverse"), ("honor-harrington", None)],
        )

    def test_an_ancestor_project_with_no_title_is_still_marked_a_project(self) -> None:
        """`title is None` does not mean "not a project" — `is_project` does.

        Three states arrive as null and only one of them is "not a project".
        Pinned because #318's wizard has to decide whether a row is offerable,
        and keyed on `title` it would refuse a perfectly declarable ancestor.
        """
        self.universe.mkdir(parents=True, exist_ok=True)
        self.service._write_yaml(self.universe / "project.yaml", {"title": "   "})
        declare(self.service, self.root, [self.universe])

        row = next(row for row in self.service.current_project().ancestors if row.name == "honorverse")

        self.assertTrue(row.is_project)
        self.assertTrue(row.inherited)
        self.assertIsNone(row.title)

    def test_an_unreadable_ancestor_manifest_does_not_break_the_open_project(self) -> None:
        """A title is decoration on someone else's folder (#311 review).

        Reading it unguarded made a malformed `project.yaml` **two levels up**
        return 422 from `GET /project` and `POST /project/open` — for a project
        whose own files are fine, and for an ancestor it need not even have
        declared. The AI routes made it worse by catching `ProjectServiceError`
        and falling back to `policy="off"`, so a stray tab in an unrelated
        manifest silently turned AI off.

        The ancestor is deliberately **not** declared here: that is the case
        that proves the blast radius was unrelated to inheritance.
        """
        make_project_folder(self.service, self.universe)
        (self.universe / "project.yaml").write_text("title: Universe\n  bad: [unclosed\n", encoding="utf-8")

        info = self.service.current_project()

        row = next(row for row in info.ancestors if row.name == "honorverse")
        self.assertTrue(row.is_project)
        self.assertIsNone(row.title)

    def test_direct_child_projects_are_listed_with_their_titles(self) -> None:
        child = self.root / "part-two"
        self.service = ProjectService.created_at(child, "Part Two")
        self.service = ProjectService.opened_at(self.root)

        self.assertEqual(
            [(row.name, row.title) for row in self.service.current_project().children],
            [("part-two", "Part Two")],
        )


class TheEnumerationReachesTheWireTests(DeclaredChainTestCase):
    """The service is not the contract — `response_model` is (#311 review).

    `GET /project` declares `response_model=ProjectInfo`, so FastAPI
    re-validates and **filters** the payload against the nested models. A field
    present on the service's return value and absent from the wire model would
    leave every service-level assertion green while the frontend silently fell
    back to folder names for every crumb.
    """

    def test_ancestor_titles_survive_the_response_model(self) -> None:
        make_project_folder(self.service, self.universe, "The Honorverse")
        self.series.mkdir(parents=True, exist_ok=True)  # organisational, no manifest
        declare(self.service, self.root, [self.universe])
        bind_test_project(self.service)

        with TestClient(app) as client:
            payload = client.get("/api/project").json()

        self.assertEqual(
            [(row["name"], row["title"], row["is_project"]) for row in payload["ancestors"]],
            [("writing", None, False), ("honorverse", "The Honorverse", True), ("honor-harrington", None, False)],
        )


class WritingTheDeclarationTests(DeclaredChainTestCase):
    def test_settings_update_stores_a_relative_path(self) -> None:
        """Relative so that renaming a shelf does not invalidate every book."""
        make_project_folder(self.service, self.universe)

        self.service.update_project_settings(
            UpdateProjectSettingsRequest(inherits=[str(self.universe)])
        )

        manifest = self.service._read_yaml(self.root / "project.yaml")
        self.assertEqual(manifest["inherits"], ["../.."])
        self.assertEqual(self._layer_folders(), [self.universe, self.root])

    def test_widening_the_base_and_declaring_in_one_request_is_accepted(self) -> None:
        """The wizard's gesture is one save: pick a shelf, tick the levels.

        Validation reads the bound from the manifest, so before this was fixed
        it saw the *stored* base — and refused a declaration the same request
        was making legal. Splitting it into two requests worked, which is what
        made it easy to miss.
        """
        make_project_folder(self.service, self.base)
        self._set_base(self.universe)  # a narrower stored bound: base is out of reach

        self.service.update_project_settings(
            UpdateProjectSettingsRequest(
                projects_base_folder=str(self.base), inherits=[str(self.base)]
            )
        )

        self.assertEqual(self._layer_folders(), [self.base, self.root])

    def test_declaring_a_non_ancestor_is_refused(self) -> None:
        """A write naming a non-ancestor is a caller error and is rejected; a
        *stored* entry that stopped being one is survived with a warning. Same
        rule, different obligations."""
        stranger = self.base.parent / "elsewhere"
        make_project_folder(self.service, stranger)

        with self.assertRaises(ProjectServiceError) as caught:
            self.service.update_project_settings(
                UpdateProjectSettingsRequest(inherits=[str(stranger)])
            )

        self.assertEqual(caught.exception.status_code, 422)


class LabelsFollowTheProjectTests(DeclaredChainTestCase):
    def test_the_outermost_declared_layer_is_not_called_base_folder(self) -> None:
        """The old rule labelled position 0 "Base Folder", which was true only
        while the walk always started at the configured base."""
        self.service = ProjectService.created_at(self.universe, "Honorverse")
        self.service = ProjectService.opened_at(self.root)
        declare(self.service, self.root, [self.universe])

        labels = [layer.label for layer in self.service.collect_layers(self.root)]

        self.assertEqual(labels, ["Honorverse", "Book 1"])


class TheSnapshotFollowsTheDeclarationTests(DeclaredChainTestCase):
    def test_changing_the_declaration_invalidates_the_index(self) -> None:
        """No indexed file changes when a declaration does, so this is caught by
        the chain comparison — the walk's output — rather than by any
        per-file fingerprint."""
        make_project_folder(self.service, self.universe)
        (self.universe / "lore").mkdir(parents=True, exist_ok=True)
        self.service._write_markdown_with_front_matter(
            self.universe / "lore" / "seren.md",
            {"id": "seren", "title": "Seren", "entry_type": "lore:character", "metadata": {}},
            "Body.",
        )

        self.assertNotIn("seren", self.service._build_node_index(self.root).by_id)

        declare(self.service, self.root, [self.universe])

        self.assertIn("seren", self.service._build_node_index(self.root).by_id)


if __name__ == "__main__":
    unittest.main()
