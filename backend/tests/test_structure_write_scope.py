"""A structure write lands in the project the unit of work started in (#381, #399).

The reference purge was #381's first half and is pinned by
`test_reference_purge.py`. This is the second: the *tree* writes.

`_manuscript_tree` / `_research_tree` used to resolve the project *again* at
write time, off a process-wide service whose `root_path` `open_project` swapped
in place. A concurrent open in that window redirected the write, overwriting the
**other** project's `manuscript.structure.yaml` with this project's tree —
irreversible, since the target file is replaced rather than appended to.

Since #399 the scope is not a field anything can swap: a unit holds a
`ProjectService` bound to an immutable `WorkScope`, and a concurrent open only
changes `current_scope`, which is what the *next* request resolves. So the race
below is expressed the way it actually happens — a second request opening
book02 mid-unit — and these tests now pin the general property rather than two
patched call sites. Reverting either fix alone no longer reproduces the failure;
what would reproduce it is a helper reaching back to `current_scope` mid-unit,
which is the thing this file exists to catch.

ADR-0045 states the invariant: a unit of work resolves its scope once and never
re-resolves it.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models import CreateSceneRequest, CreateStructureNodeRequest
from app.runtime import current_scope
from app.services.project_service import ProjectService


class StructureWritesStayInTheCallersProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.book1 = self.base / "book01"
        self.book2 = self.base / "book02"
        for path, title in ((self.book1, "Book 1"), (self.book2, "Book 2")):
            ProjectService.created_at(path, title)
        self.service = ProjectService.opened_at(self.book1)
        current_scope.set(self.service.scope)

    def tearDown(self) -> None:
        current_scope.clear()
        self.temp_dir.cleanup()

    def _open_book2_concurrently(self) -> None:
        """Exactly what a concurrent `/api/project/open` does, and no more.

        It changes what the *next* request resolves. `self.service` — the unit
        already in flight — is untouched, because a handle cannot be re-pointed.
        """
        current_scope.set(ProjectService.opened_at(self.book2).scope)

    def _race_after_reading_the_tree(self, reader_name: str) -> None:
        """Another request opens book02 between the read and the write.

        The shim wraps the *read*, the earliest point after the unit has
        captured its root — so it fires inside the window the fix closes, and
        would not be satisfied by merely moving the capture earlier.
        """
        real = getattr(self.service, reader_name)

        def racing(*args: object, **kwargs: object) -> object:
            document = real(*args, **kwargs)
            self._open_book2_concurrently()
            return document

        setattr(self.service, reader_name, racing)

    def test_a_concurrent_open_does_not_redirect_the_tree_read_either(self) -> None:
        """The read half of the same invariant.

        Pinning only the write leaves the worse failure open: a unit that
        captured a root and then re-resolved at read time pulls the *other*
        project's tree in and writes it into its own — destroying the project
        the author is working in. `create_scene` writes a file between the
        capture and the read, so the window is real IO.
        """
        book1_structure = self.book1 / "manuscript.structure.yaml"
        seeded = _find(self.service.read_structure().root, lambda node: bool(node.scene_id))

        real_write = self.service._write_scene_file

        def racing(*args: object, **kwargs: object) -> object:
            result = real_write(*args, **kwargs)
            self._open_book2_concurrently()
            return result

        self.service._write_scene_file = racing  # type: ignore[method-assign]
        # Completes, rather than 404ing on the read-back. Before #399 the
        # response path resolved the scene through `_path_for_node_id`, which
        # re-read the singleton — by then book02 — and raised. That was the
        # general drift #381 left open; asserting the scene comes back is what
        # pins it closed.
        created = self.service.create_scene(_scene_request("Added In Book One"))

        self.assertEqual(created.title, "Added In Book One")
        self.assertTrue(
            any(path.stem for path in (self.book1 / "scenes").glob("*.md") if created.id in path.read_text(encoding="utf-8")),
            "the new scene was not written into book01",
        )
        # book01's own tree survived: the read did not come from book02.
        self.assertIn(seeded.scene_id, book1_structure.read_text(encoding="utf-8"))

    def test_a_concurrent_open_does_not_redirect_a_manuscript_write(self) -> None:
        created = self.service.create_structure_node(
            _structure_node_request("Act One", "scene:act")
        )
        act = _find(created.root, lambda node: node.title == "Act One")
        scene_node = _find(created.root, lambda node: bool(node.scene_id))
        book2_structure = self.book2 / "manuscript.structure.yaml"
        before = book2_structure.read_text(encoding="utf-8")

        self._race_after_reading_the_tree("_read_structure")
        self.service.move_structure_node(scene_node.id, act.id, 0)

        self.assertEqual(book2_structure.read_text(encoding="utf-8"), before)
        moved = self.service._read_yaml(self.book1 / "manuscript.structure.yaml")
        self.assertIn(scene_node.id, str(moved))

    def test_a_concurrent_open_does_not_redirect_a_rename(self) -> None:
        """The instance #399 was filed for.

        `rename_structure_node` resolves the *scene file* through
        `_path_for_node_id` after capturing its root. While that helper re-read
        the process's open project, racing an open in redirected the lookup:
        a 404 when the id was absent from the other project, and a **rewrite of
        the wrong project's scene file** when it was not — so the two projects
        here deliberately share a scene id.
        """
        scene_node = _find(self.service.read_structure().root, lambda node: bool(node.scene_id))
        victim = _scene_file_for(self.book2, "book02-scene")
        # Same id in both projects: the lookup can only be shown to have used
        # the right one if the wrong one would also have resolved.
        self.service._write_markdown_with_front_matter(
            victim,
            {"id": scene_node.scene_id, "title": "Book Two Scene", "entry_type": "scene:scene", "metadata": {}},
            "Book two's prose.",
        )
        before = victim.read_text(encoding="utf-8")

        self._race_after_reading_the_tree("_read_structure")
        self.service.rename_structure_node(scene_node.id, "Renamed In Book One")

        # Tolerates the file being gone rather than merely changed: a rename
        # canonicalises the filename to the title, so a redirected write moves
        # book02's scene as well as rewriting it.
        after = victim.read_text(encoding="utf-8") if victim.exists() else "<the file was moved>"
        self.assertEqual(after, before, "the rename reached book02's scene")
        self.assertIn(
            "Renamed In Book One",
            (self.book1 / "manuscript.structure.yaml").read_text(encoding="utf-8"),
        )


def _find(node, predicate):
    """First node in the tree satisfying `predicate` — the structure shape a
    fresh project seeds is not part of what these tests pin."""
    if predicate(node):
        return node
    for child in node.children:
        found = _find(child, predicate)
        if found is not None:
            return found
    return None


def _scene_file_for(root: Path, stem: str) -> Path:
    (root / "scenes").mkdir(parents=True, exist_ok=True)
    return root / "scenes" / f"{stem}.md"


def _structure_node_request(title: str, entry_type: str) -> CreateStructureNodeRequest:
    return CreateStructureNodeRequest(title=title, entry_type=entry_type)


def _scene_request(title: str) -> CreateSceneRequest:
    return CreateSceneRequest(title=title)


if __name__ == "__main__":
    unittest.main()
