"""Opening a non-leaf level is opening a project — nothing more (#310, ADR-0039).

Slice B's premise is that the backend already treats every level the same: the
walk, the index and the merged schema are level-agnostic, and `project.md`
exists at every layer (#343). This file is where that premise stops being a
claim in an issue body.

What it pins, in the order the claim can fail:

1. A non-leaf **opens at all**, and reports its direct children — the roster the
   pane renders.
2. It merges its own ancestors' canon, exactly as a book does.
3. It does **not** see its descendants. Visibility is ancestor-only (ADR-0039),
   so opening the universe must not hoover up every book's lore — the failure
   that would make the level distinction meaningless.
4. A level's manuscript is **exactly the files in its own `scenes/`** — nothing
   inherits in, nothing leaks out.

Point 4 is what settles #310's "no manuscript pane vs empty manuscript pane"
question, by making it not a question: whether there is a manuscript to show is
a **file count**, which the pane's existing empty state already answers. No
branch on leaf-vs-non-leaf is needed, or would even be correct —
`create_project` seeds a first scene into every project it makes, including one
that later grows children, so the level does not tell you whether scenes exist.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from layer_fixtures import declare_full_chain

from app.models import CreateLoreEntryRequest
from app.services.project_service import ProjectService


class OpenANonLeafLevelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        # Resolved: Windows hands back the 8.3 short form while the walk
        # canonicalises (#356).
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.universe = self.base / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.book = self.series / "book01"

        for path, title in (
            (self.universe, "Honorverse"),
            (self.series, "Honor Harrington"),
            (self.book, "Book 1"),
        ):
            declare_full_chain(ProjectService.created_at(path, title), path, self.base)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _lore_titles(self, service: ProjectService) -> set[str]:
        return {entry.title for entry in service.list_lore_entries().entries}

    def test_a_non_leaf_opens_and_reports_its_direct_children(self) -> None:
        info = ProjectService.opened_at(self.universe).current_project()

        self.assertEqual(info.title, "Honorverse")
        self.assertEqual([child.path for child in info.children], [str(self.series)])
        self.assertEqual([child.title for child in info.children], ["Honor Harrington"])

    def test_the_roster_is_direct_children_only_not_the_whole_shelf(self) -> None:
        """A level shows the places you can open *from here* (ADR-0039). Listing
        grandchildren would make the roster a project browser, and the switcher
        (#311) a second one."""
        info = ProjectService.opened_at(self.universe).current_project()

        rostered = {child.path for child in info.children}
        self.assertIn(str(self.series), rostered)
        self.assertNotIn(str(self.book), rostered)

    def test_a_leaf_has_an_empty_roster(self) -> None:
        """The same field, the same shape — the pane branches on emptiness, not
        on a level type, because there is no level type to branch on."""
        info = ProjectService.opened_at(self.book).current_project()

        self.assertEqual(info.children, [])

    def test_a_non_leaf_merges_its_own_ancestors_canon(self) -> None:
        base_service = ProjectService.opened_at(self.universe)
        base_service.create_lore_entry(
            CreateLoreEntryRequest(title="Manticore", entry_type="lore:lore_note")
        )
        series_service = ProjectService.opened_at(self.series)
        series_service.create_lore_entry(
            CreateLoreEntryRequest(title="Honor", entry_type="lore:character")
        )

        self.assertEqual(self._lore_titles(series_service), {"Manticore", "Honor"})

    def test_a_non_leaf_does_not_see_its_descendants(self) -> None:
        """The one that makes levels mean something. Visibility is ancestor-only,
        so a book's private lore must not surface when the universe is open —
        otherwise every level shows everything and the chain is decoration."""
        ProjectService.opened_at(self.book).create_lore_entry(
            CreateLoreEntryRequest(title="Nimitz", entry_type="lore:character")
        )
        ProjectService.opened_at(self.universe).create_lore_entry(
            CreateLoreEntryRequest(title="Manticore", entry_type="lore:lore_note")
        )

        universe_lore = self._lore_titles(ProjectService.opened_at(self.universe))
        self.assertIn("Manticore", universe_lore)
        self.assertNotIn("Nimitz", universe_lore)

    def _scene_ids(self, root: Path) -> set[str]:
        return {
            entry.id
            for entry in ProjectService.opened_at(root)._build_node_index(root).by_id.values()
            if entry.kind == "scene"
        }

    def test_the_manuscript_is_exactly_this_levels_own_scenes_folder(self) -> None:
        """The whole rule, stated as a count rather than as a level.

        `_families_for_layer` drops the scene family for every layer that is not
        the open project, so a level's manuscript is precisely the `.md` files in
        **its own** `scenes/`. Asserted against the folder rather than a fixed
        number, because the number is not the point: the point is that nothing
        inherits in and nothing leaks out, at any level.

        This is also why the pane needs no notion of leaf or non-leaf. Whether
        there is a manuscript to show is a question about a file count, which the
        empty state already answers — and it stays right when a universe has a
        scene (`create_project` seeds one) or a book has none.
        """
        for root in (self.universe, self.series, self.book):
            with self.subTest(level=root.name):
                self.assertEqual(
                    len(self._scene_ids(root)),
                    len(list((root / "scenes").glob("*.md"))),
                )

    def test_no_level_inherits_another_levels_scenes(self) -> None:
        self.assertEqual(self._scene_ids(self.universe) & self._scene_ids(self.book), set())


if __name__ == "__main__":
    unittest.main()
