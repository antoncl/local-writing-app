"""A structure write lands in the project the unit of work started in (#381).

The reference purge was #381's first half and is pinned by
`test_reference_purge.py`. This is the second: the *tree* writes.

`ProjectService` is a process-global singleton (`runtime.py`) whose `root_path`
mutates in place, and every mutation route is a sync `def` on FastAPI's
threadpool. A structure mutation reads the tree, edits it in memory and writes
it back — and `_manuscript_tree` / `_research_tree` used to resolve the project
*again* at write time. A concurrent `open_project` in that window redirected the
write, overwriting the **other** project's `manuscript.structure.yaml` with this
project's tree. Same class as the purge, and equally irreversible: the target
file is replaced, not appended to.

ADR-0045 states the invariant this test pins: a unit of work resolves its scope
once and never re-resolves it.

**Only the manuscript tree is exercised, deliberately.** The research mixin binds
its `TreeStructureService` once per method and reuses it for the read and the
write, so it never resolved twice and was never exposed; `_research_tree` took
the same required-`root` parameter for uniformity, not to fix a live defect. A
test there would race a window that does not exist and pass against the old code
— pinning nothing. Verified by mutation: reverting `_manuscript_tree` to read the
singleton turns the test below red, reverting `_research_tree` does not.
"""

from __future__ import annotations

import contextlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.models import CreateSceneRequest, CreateStructureNodeRequest
from app.services.project.errors import ProjectServiceError
from app.services.project_service import ProjectService


class StructureWritesStayInTheCallersProjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.service = ProjectService()
        self.book1 = self.base / "book01"
        self.book2 = self.base / "book02"
        for path, title in ((self.book1, "Book 1"), (self.book2, "Book 2")):
            self.service.create_project(path, title)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _race_after_reading_the_tree(self, reader_name: str) -> None:
        """Another request opens book02 between the read and the write.

        The shim wraps the *read*, which is the earliest point after the unit
        has captured its root — so it fires inside the window the fix closes,
        and it would not be satisfied by merely moving the capture earlier.
        """
        real = getattr(self.service, reader_name)

        def racing(*args: object, **kwargs: object) -> object:
            document = real(*args, **kwargs)
            self.service.open_project(self.book2)
            return document

        setattr(self.service, reader_name, racing)

    def test_a_concurrent_open_does_not_redirect_the_tree_read_either(self) -> None:
        """The read half of the same invariant.

        Pinning only the write leaves the worse failure open: a unit that
        captured a root and then re-resolved the singleton at read time pulls
        the *other* project's tree in and writes it into its own — destroying
        the project the author is working in. `create_scene` writes a file
        between the capture and the read, so the window is real IO.
        """
        self.service.open_project(self.book1)
        book1_structure = self.book1 / "manuscript.structure.yaml"
        seeded = _find(self.service.read_structure().root, lambda node: bool(node.scene_id))

        real_write = self.service._write_scene_file

        def racing(*args: object, **kwargs: object) -> object:
            result = real_write(*args, **kwargs)
            self.service.open_project(self.book2)
            return result

        self.service._write_scene_file = racing  # type: ignore[method-assign]
        self.service.open_project(self.book1)
        with contextlib.suppress(ProjectServiceError):
            # The tree work completes; `create_scene`'s *response* then reads the
            # new scene back through `_path_for_node_id`, which still resolves
            # the singleton — by now book02 — and 404s. That is the general
            # drift (#399), deliberately out of this fix's scope. Suppressed
            # rather than asserted so this test fails if the response path is
            # ever fixed and starts raising something else.
            self.service.create_scene(_scene_request("Added In Book One"))

        # book01's own tree survived: the read did not come from book02.
        self.assertIn(seeded.scene_id, book1_structure.read_text(encoding="utf-8"))

    def test_a_concurrent_open_does_not_redirect_a_manuscript_write(self) -> None:
        self.service.open_project(self.book1)
        # A **move**, because it writes the tree and nothing else. Renaming a
        # scene node also rewrites the scene file, and that path resolves
        # through `_path_for_node_id`, which still reads the singleton — the
        # general drift this fix deliberately does not close (see the follow-up
        # issue). Racing a tree-only mutation is what pins the tree write.
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


def _structure_node_request(title: str, entry_type: str) -> CreateStructureNodeRequest:
    return CreateStructureNodeRequest(title=title, entry_type=entry_type)


def _scene_request(title: str) -> CreateSceneRequest:
    return CreateSceneRequest(title=title)


if __name__ == "__main__":
    unittest.main()
