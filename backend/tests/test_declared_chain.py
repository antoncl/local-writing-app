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
from layer_fixtures import declare, make_project_folder, set_projects_root
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
        """Set the walk's outer bound — the machine root since #429.

        It used to be this project's own `settings.projects_base_folder`. One
        folder per machine now, so it is written to machine settings; safe here
        because conftest redirects `config_path()` per test.
        """
        set_projects_root(folder)

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

    def test_an_unreadable_child_manifest_does_not_break_the_open_project(self) -> None:
        """The mirror of the ancestor case, found reviewing the ancestor fix.

        `_project_children` read a child's manifest unguarded (#310), so a
        malformed `project.yaml` in any direct subfolder took out
        `current_project()` just as an ancestor's did. A child is another
        folder's file too; the roster falls back to the folder name.
        """
        child = self.root / "part-two"
        self.service = ProjectService.created_at(child, "Part Two")
        self.service = ProjectService.opened_at(self.root)
        (child / "project.yaml").write_text("title: Part Two\n  bad: [unclosed\n", encoding="utf-8")

        self.assertEqual(
            [(row.name, row.title) for row in self.service.current_project().children],
            [("part-two", "part-two")],
        )

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


class TheResolvedChainReachesTheWireTests(DeclaredChainTestCase):
    """`ProjectInfo.chain` — the selection and the labels, decided once (#432).

    These cases used to live in the frontend's `projectChain.test.ts`, against
    a transcription of `_project_layer_folders` + `_layer_label_for_folder`
    that the walker already implemented. Testing the transcript is what let the
    two disagree in the first place: the walker labels a titleless outermost
    layer that is the machine root "Base Folder", and the copy called the same
    folder by its directory name. They belong here, against the code that
    actually decides them.
    """

    def _chain(self) -> list[tuple[str, str, bool]]:
        bind_test_project(self.service)
        with TestClient(app) as client:
            payload = client.get("/api/project").json()
        return [(row["label"], Path(row["path"]).name, row["is_root"]) for row in payload["chain"]]

    def test_the_chain_is_the_declared_subset_outermost_first(self) -> None:
        make_project_folder(self.service, self.universe, "The Honorverse")
        make_project_folder(self.service, self.series, "Honor Harrington")
        declare(self.service, self.root, [self.universe, self.series])

        self.assertEqual(
            self._chain(),
            [
                ("The Honorverse", "honorverse", False),
                ("Honor Harrington", "honor-harrington", False),
                ("Book 1", "book01", True),
            ],
        )

    def test_an_ancestor_project_that_was_never_declared_is_not_in_the_chain(self) -> None:
        """#318's wizard offers it from `ancestors`; the chain must not imply
        it is part of what is being built here."""
        make_project_folder(self.service, self.universe, "The Honorverse")

        self.assertEqual(self._chain(), [("Book 1", "book01", True)])

    def test_a_declared_folder_that_is_not_a_project_is_not_in_the_chain(self) -> None:
        """The `is_project` half of the rule. A declared folder whose manifest
        was deleted keeps its declaration — `declared_ancestor_warnings` says
        so out loud rather than dropping it silently — but it contributes
        nothing, so it is not a layer and has no label to render."""
        make_project_folder(self.service, self.universe, "The Honorverse")
        declare(self.service, self.root, [self.universe])
        (self.universe / "project.yaml").unlink()

        self.assertEqual(self._chain(), [("Book 1", "book01", True)])

    def test_a_declared_project_with_no_title_falls_back_to_its_folder_name(self) -> None:
        self.universe.mkdir(parents=True, exist_ok=True)
        self.service._write_yaml(self.universe / "project.yaml", {"version": 1})
        declare(self.service, self.root, [self.universe])

        self.assertEqual(
            self._chain(),
            [("honorverse", "honorverse", False), ("Book 1", "book01", True)],
        )

    def test_a_gap_is_carried_as_declared(self) -> None:
        """Declaring a grandparent without its parent is legal upstream, so the
        chain reports two layers with a folder between them. Whether the BAR
        should say so is #431; this pins that the data does not quietly fill
        the gap in."""
        make_project_folder(self.service, self.universe, "The Honorverse")
        make_project_folder(self.service, self.series, "Honor Harrington")
        declare(self.service, self.root, [self.universe])

        self.assertEqual(
            self._chain(),
            [("The Honorverse", "honorverse", False), ("Book 1", "book01", True)],
        )

    def test_a_flat_project_is_a_chain_of_one(self) -> None:
        self.assertEqual(self._chain(), [("Book 1", "book01", True)])

    def test_a_malformed_ancestor_manifest_does_not_stop_the_project_opening(self) -> None:
        """A label is decoration on someone else's folder (#430, forced by #432).

        `_layer_label_for_folder` read each layer's manifest unguarded, and
        `_read_yaml` raises 422 on a syntax error. That already broke the node
        index and the validation report. Putting `collect_layers` on
        `current_project()` — which is what `POST /project/open` returns — made
        the same broken file stop the project below it opening at all, for a
        project whose own files are fine.

        The layer survives with its folder name, exactly as
        `_readable_project_title` already did for `ancestors`.
        """
        make_project_folder(self.service, self.universe, "The Honorverse")
        declare(self.service, self.root, [self.universe])
        (self.universe / "project.yaml").write_text("title: [unclosed\n", encoding="utf-8")

        self.assertEqual(
            self._chain(),
            [("honorverse", "honorverse", False), ("Book 1", "book01", True)],
        )

    def test_a_malformed_ancestor_manifest_leaves_the_validation_report_readable(self) -> None:
        """#430's own reproduction: the report that should name the problem was
        the request that failed. The walk no longer raises, so it renders."""
        make_project_folder(self.service, self.universe, "The Honorverse")
        declare(self.service, self.root, [self.universe])
        (self.universe / "project.yaml").write_text("title: [unclosed\n", encoding="utf-8")
        bind_test_project(self.service)

        with TestClient(app) as client:
            response = client.post("/api/project/validate")

        self.assertEqual(response.status_code, 200)

    def test_the_chain_agrees_with_the_schema_layers_view(self) -> None:
        """The disagreement #432 exists to remove, pinned as an equality.

        Both views are `collect_layers` now, so this fails the moment either
        one starts deriving its own answer again.
        """
        make_project_folder(self.service, self.universe, "The Honorverse")
        declare(self.service, self.root, [self.universe])
        bind_test_project(self.service)

        with TestClient(app) as client:
            chain = client.get("/api/project").json()["chain"]
            layers = client.get("/api/metadata/schema/layers").json()["layers"]

        self.assertEqual(
            [(row["id"], row["label"]) for row in chain],
            [(row["id"], row["label"]) for row in layers],
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

    def test_widening_the_bound_is_a_machine_change_that_every_project_sees(self) -> None:
        """Since #429 the bound is the machine root, so widening it is not part
        of any project's save — and does not need to be.

        This replaces `test_widening_the_base_and_declaring_in_one_request_is
        _accepted`, which pinned the old shape: a settings update could carry a
        new `projects_base_folder` *and* a declaration, because validation read
        the bound from the manifest and would otherwise refuse a declaration
        the same request was making legal. That gesture is gone with the key.

        What replaces it is stronger. Widening happens once, in machine
        settings, and every project sees it at once — so a folder that was out
        of reach becomes declarable without touching any project, and the
        declaration is then an ordinary save.
        """
        make_project_folder(self.service, self.base)
        self._set_base(self.universe)  # a narrower machine root: base is out of reach

        with self.assertRaises(ProjectServiceError):
            self.service.update_project_settings(
                UpdateProjectSettingsRequest(inherits=[str(self.base)])
            )

        self._set_base(self.base)  # one machine-level change, no project touched

        self.service.update_project_settings(UpdateProjectSettingsRequest(inherits=[str(self.base)]))

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


class OneMachineRootMeansEveryLevelAgreesTests(unittest.TestCase):
    """#429 — the defect this replaced, pinned so it cannot come back.

    The bound used to be `settings.projects_base_folder`, written per project.
    The create wizard built each project directly under the folder it passed as
    the bound, so every project recorded **its own parent** — and no two levels
    of one chain ever agreed. Opening the series enumerated `[universe]`;
    opening the book enumerated `[series]`. `Universe › Series › Book` was
    unreachable no matter what anyone declared, because the declaration can
    only ever *select* from the enumeration.
    """

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.shelf = Path(self.tmp.name).resolve() / "writing"
        self.universe = self.shelf / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.book = self.series / "on-basilisk-station"
        self.shelf.mkdir(parents=True)
        set_projects_root(self.shelf)
        # Created exactly as the app creates them — no per-project bound to
        # pass any more, which is the point.
        ProjectService.created_at(self.universe, "The Honorverse")
        ProjectService.created_at(self.series, "Honor Harrington")
        ProjectService.created_at(self.book, "On Basilisk Station")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_every_level_reports_the_same_bound(self) -> None:
        for root in (self.universe, self.series, self.book):
            with self.subTest(project=root.name):
                service = ProjectService.opened_at(root)
                self.assertEqual(service.current_project().projects_base_folder, str(self.shelf))

    def test_the_enumeration_deepens_with_the_project_instead_of_stopping_at_the_parent(self) -> None:
        expected = {
            self.universe: [],
            self.series: [self.universe],
            self.book: [self.universe, self.series],
        }
        for root, ancestors in expected.items():
            with self.subTest(project=root.name):
                service = ProjectService.opened_at(root)
                self.assertEqual(service.ancestor_projects(root), ancestors)

    def test_a_three_level_chain_is_declarable_and_walks_whole(self) -> None:
        """The demo that motivated #311, end to end."""
        service = ProjectService.opened_at(self.book)
        declare(service, self.book, [self.universe, self.series])

        service = ProjectService.opened_at(self.book)
        info = service.current_project()
        chain = [row.title for row in info.ancestors if row.inherited and row.is_project]

        self.assertEqual(chain, ["The Honorverse", "Honor Harrington"])
        self.assertEqual(
            [layer.folder for layer in service.collect_layers(self.book)],
            [self.universe, self.series, self.book],
        )

    def test_a_project_outside_the_machine_root_stands_alone(self) -> None:
        """Anton's framing: outside the root it is not a project the app works
        on. Preventing it from being reachable at all is future work; today it
        opens, warns, and inherits nothing rather than half-participating."""
        stray = Path(self.tmp.name).resolve() / "elsewhere" / "orphan"
        service = ProjectService.created_at(stray, "Orphan")

        self.assertEqual(service.ancestor_candidates(stray), [])
        self.assertEqual([layer.folder for layer in service.collect_layers(stray)], [stray])
        self.assertTrue(
            any("outside the machine's projects folder" in w for w in service.validate_project().warnings)
        )


class TheWalkIsSeparateFromTheDeclarationTests(DeclaredChainTestCase):
    """#460 — the walk parses nothing; the declaration is an overlay.

    It used to be one method returning `(folder, is_project, inherited)`, and
    that third flag was the only reason the walk read a manifest. Three of five
    consumers discarded it, and on the create path the discarded parse was the
    only thing that could fail.
    """

    def test_the_walk_survives_the_projects_own_manifest_being_malformed(self) -> None:
        """The property the split buys, stated as a property rather than as the
        create-path symptom it was found through: enumerating a project's
        ancestors is a filesystem question and must not depend on parsing that
        project's own file."""
        make_project_folder(self.service, self.universe)
        (self.root / "project.yaml").write_text("title: X\n  bad: [unclosed\n", encoding="utf-8")

        self.assertEqual(
            self.service.ancestor_candidates(self.root),
            [(self.base, False), (self.universe, True), (self.series, False)],
        )
        self.assertEqual(self.service.ancestor_projects(self.root), [self.universe])

    def test_the_declared_overlay_still_reads_the_declaration(self) -> None:
        """The two consumers that need `inherited` must still get it — the
        split must not quietly turn every chain flat."""
        declare(self.service, self.root, [self.universe])

        self.assertEqual(
            self.service.declared_ancestor_candidates(self.root),
            [(self.base, False, False), (self.universe, True, True), (self.series, False, False)],
        )


class ANewProjectDeclaresItsAncestorsTests(unittest.TestCase):
    """#425 — the default. Every project the app created declared nothing, so
    every chain was length one and #311's breadcrumb was empty for all of them.

    The fixture is the reported case: `writing/honorverse/honor-harrington/
    on-basilisk-station`, created exactly as the app creates it.
    """

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.shelf = Path(self.tmp.name).resolve() / "writing"
        self.universe = self.shelf / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.book = self.series / "on-basilisk-station"
        self.shelf.mkdir(parents=True)
        set_projects_root(self.shelf)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _create_chain(self) -> None:
        ProjectService.created_at(self.universe, "The Honorverse")
        ProjectService.created_at(self.series, "Honor Harrington")
        ProjectService.created_at(self.book, "On Basilisk Station")

    def test_a_project_created_inside_a_chain_opens_with_that_chain(self) -> None:
        """Acceptance 1, and the whole point: no further action."""
        self._create_chain()

        service = ProjectService.opened_at(self.book)

        self.assertEqual(
            [layer.folder for layer in service.collect_layers(self.book)],
            [self.universe, self.series, self.book],
        )

    def test_the_default_is_every_ancestor_project_not_the_nearest_one(self) -> None:
        """Nearest-only would be enough under a transitive reading, which is
        exactly what #428 closed. With each project's list complete for itself,
        declaring only the parent leaves the universe out of the book's chain.
        """
        self._create_chain()

        manifest = ProjectService.opened_at(self.book)._read_yaml(self.book / "project.yaml")

        self.assertEqual(manifest["inherits"], ["../..", ".."])

    def test_a_project_created_outside_any_ancestor_project_is_a_chain_of_one(self) -> None:
        """Acceptance 2. The shelf is a folder, not a project, so there is
        nothing above the universe to declare."""
        service = ProjectService.created_at(self.universe, "The Honorverse")

        self.assertEqual(
            service._read_yaml(self.universe / "project.yaml")["inherits"], []
        )
        self.assertEqual([layer.folder for layer in service.collect_layers(self.universe)], [self.universe])

    def test_a_non_project_ancestor_is_never_written_into_the_declaration(self) -> None:
        """Acceptance 3. An organisational folder mid-chain is skipped, not
        declared: it carries no manifest, so declaring it would contribute
        nothing and seed a `declared_ancestor_warnings` entry on a project
        nobody had touched yet."""
        ProjectService.created_at(self.universe, "The Honorverse")
        self.series.mkdir(parents=True, exist_ok=True)  # organisational, no manifest

        service = ProjectService.created_at(self.book, "On Basilisk Station")

        self.assertEqual(service._read_yaml(self.book / "project.yaml")["inherits"], ["../.."])
        self.assertEqual(service.declared_ancestor_warnings(self.book), [])

    def test_a_project_created_outside_the_machine_root_declares_nothing(self) -> None:
        """The enumeration is empty out there (#429/#441), so the default has
        nothing to select and must not fall back to walking the filesystem."""
        stray = Path(self.tmp.name).resolve() / "elsewhere" / "orphan"

        service = ProjectService.created_at(stray, "Orphan")

        self.assertEqual(service._read_yaml(stray / "project.yaml")["inherits"], [])

    def test_the_machine_root_is_declared_when_it_is_itself_a_project(self) -> None:
        """The enumeration's own boundary, which nothing else pins.

        The root folder is a candidate like any other, so "every ancestor
        project" includes it when it carries a manifest. The mirror case — a
        project *outside* the root — is pinned above; this is the same edge
        approached from the inside, and a change to the walk's slicing would
        otherwise add or drop a layer on such a machine in silence.
        """
        (self.shelf / "project.yaml").write_text("title: The Shelf\n", encoding="utf-8")

        service = ProjectService.created_at(self.universe, "The Honorverse")

        self.assertEqual(service._read_yaml(self.universe / "project.yaml")["inherits"], [".."])

    def test_creating_over_a_folder_whose_manifest_is_malformed_still_works(self) -> None:
        """#460, from the create side. Resolving the default used to read the
        target's own `project.yaml` for an `inherited` flag it discarded — so a
        stale malformed file in the folder being scaffolded turned create into
        a 422, naming a parse error for a file the very next line overwrites.
        """
        ProjectService.created_at(self.universe, "The Honorverse")
        victim = self.universe / "half-made"
        victim.mkdir()
        (victim / "project.yaml").write_text("title: X\n  bad: [unclosed\n", encoding="utf-8")

        service = ProjectService.created_at(victim, "Remade")

        self.assertEqual(service._read_yaml(victim / "project.yaml")["inherits"], [".."])

    def test_an_explicit_declaration_is_honoured_verbatim(self) -> None:
        """`inherits` on the request is what #318's wizard will send. An empty
        list is a real choice — a flat project inside a chain — and must not be
        re-defaulted, which is why the request field distinguishes `[]` from
        unset."""
        self._create_chain()
        deliberate = self.series / "part-two"

        service = ProjectService.created_at(deliberate, "Part Two", [str(self.universe)])

        self.assertEqual(service._read_yaml(deliberate / "project.yaml")["inherits"], ["../.."])

    def test_an_explicit_empty_declaration_creates_a_flat_project(self) -> None:
        self._create_chain()
        flat = self.series / "standalone"

        service = ProjectService.created_at(flat, "Standalone", [])

        self.assertEqual(service._read_yaml(flat / "project.yaml")["inherits"], [])
        self.assertEqual([layer.folder for layer in service.collect_layers(flat)], [flat])

    def test_an_explicit_non_ancestor_is_refused_before_anything_is_written(self) -> None:
        """Same rule as the settings save — and it must refuse *first*: a 422
        raised after the scaffold began would leave a folder on disk for a
        request that never should have written one."""
        self._create_chain()
        stranger = Path(self.tmp.name).resolve() / "elsewhere"
        stranger.mkdir(parents=True)
        (stranger / "project.yaml").write_text("title: Elsewhere\n", encoding="utf-8")
        doomed = self.series / "doomed"

        with self.assertRaises(ProjectServiceError) as caught:
            ProjectService.created_at(doomed, "Doomed", [str(stranger)])

        self.assertEqual(caught.exception.status_code, 422)
        self.assertFalse(doomed.exists())

    def test_the_declaration_reaches_the_wire(self) -> None:
        """`POST /project/create` is the only caller that matters, and the
        response is re-validated against `ProjectInfo` — a default written to
        disk but absent from the enumeration would still read as empty."""
        self._create_chain()
        part_two = self.book / "part-two"

        with TestClient(app) as client:
            payload = client.post(
                "/api/project/create",
                json={"root_path": str(part_two), "title": "Part Two"},
            ).json()

        self.assertEqual(
            [(row["name"], row["inherited"]) for row in payload["ancestors"]],
            [
                ("writing", False),
                ("honorverse", True),
                ("honor-harrington", True),
                ("on-basilisk-station", True),
            ],
        )

    def test_an_explicit_declaration_on_the_request_is_what_gets_written(self) -> None:
        """The field has to be *read* by the route, not merely exist on the
        model: with the default doing the visible work, a route that dropped
        `inherits` would look correct in every other test here."""
        self._create_chain()
        part_two = self.book / "part-two"

        with TestClient(app) as client:
            payload = client.post(
                "/api/project/create",
                json={
                    "root_path": str(part_two),
                    "title": "Part Two",
                    "inherits": [str(self.universe)],
                },
            ).json()

        self.assertEqual(
            [row["name"] for row in payload["ancestors"] if row["inherited"]], ["honorverse"]
        )


if __name__ == "__main__":
    unittest.main()
