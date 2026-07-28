"""current_project() serves the layer chain once per request, not twice (#466).

Building the ancestor view and the resolved chain each drove the same walk
(`declared_ancestor_candidates`) and each asked every ancestor for its title, so
one `GET /project` re-parsed every ancestor's `project.yaml` and re-ran the
folder stat-sweep — two thirds of the call. A per-request memo on the throwaway
`ProjectService` collapses each to one read. It carries no authority and cannot
go stale across requests (a fresh service is resolved per request), and any
write clears it at the write choke so a read taken before a manifest change is
never served after it.

The assertions count the underlying reads rather than time the call, so they
fail if either memo — or the write-invalidation — is removed.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from layer_fixtures import set_projects_root

from app.services.project_service import ProjectService


class ChainWalkMemoTestCase(unittest.TestCase):
    """writing / honorverse / honor-harrington / on-basilisk-station, declared —
    the same three-level chain #466 was measured on."""

    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.shelf = Path(self.tmp.name).resolve() / "writing"
        self.universe = self.shelf / "honorverse"
        self.series = self.universe / "honor-harrington"
        self.book = self.series / "on-basilisk-station"
        self.shelf.mkdir(parents=True)
        set_projects_root(self.shelf)
        # Created exactly as the app creates them, so each declares its ancestors.
        ProjectService.created_at(self.universe, "The Honorverse")
        ProjectService.created_at(self.series, "Honor Harrington")
        ProjectService.created_at(self.book, "On Basilisk Station")
        self.service = ProjectService.opened_at(self.book)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _spy(self, name: str) -> mock._patch:
        """Patch a service method with a call-counting pass-through."""
        return mock.patch.object(self.service, name, wraps=getattr(self.service, name))


class TheWalkRunsOncePerRequestTests(ChainWalkMemoTestCase):
    def test_current_project_joins_the_declaration_once(self) -> None:
        """The headline: both `ancestors` and `chain` are built, but the join of
        the walk with `root`'s `inherits:` — the one place the walk parses a
        manifest — happens a single time."""
        with self._spy("_declared_ancestors") as spy:
            self.service.current_project()

        self.assertEqual(spy.call_count, 1)

    def test_the_walk_is_computed_once_across_repeated_calls(self) -> None:
        with self._spy("_declared_ancestors") as spy:
            first = self.service.declared_ancestor_candidates(self.book)
            second = self.service.declared_ancestor_candidates(self.book)

        self.assertEqual(spy.call_count, 1)
        self.assertEqual(first, second)

    def test_a_resolved_and_an_unresolved_root_share_one_cache_slot(self) -> None:
        """The two consumers spell the root differently — `_project_layer_folders`
        resolves it, the ancestor view does not — so the memo keys on the
        resolved form or the walk still runs twice."""
        wobbly = self.book / "nonexistent" / ".."
        self.assertEqual(wobbly.resolve(), self.book)  # precondition, not the point

        with self._spy("_declared_ancestors") as spy:
            self.service.declared_ancestor_candidates(self.book)
            self.service.declared_ancestor_candidates(wobbly)

        self.assertEqual(spy.call_count, 1)


class EachTitleIsParsedOnceTests(ChainWalkMemoTestCase):
    def test_a_repeated_title_read_opens_the_manifest_once(self) -> None:
        manifest = self.universe / "project.yaml"
        with self._spy("_read_yaml") as spy:
            first = self.service._project_title(self.universe)
            second = self.service._project_title(self.universe)

        reads = [call for call in spy.call_args_list if call.args and call.args[0] == manifest]
        self.assertEqual(len(reads), 1)
        self.assertEqual(first, "The Honorverse")
        self.assertEqual(second, "The Honorverse")

    def test_current_project_reads_each_ancestor_manifest_at_most_once_for_its_title(self) -> None:
        """The specific duplication #466 names: the ancestor view and the chain
        label both want a title for the same folder."""
        with self._spy("_project_title") as spy:
            self.service.current_project()

        # `_project_title` is *called* more than once per folder (both views ask),
        # but a real `_read_yaml` behind it must happen once — proven by the read
        # count staying at one open per ancestor manifest.
        with self._spy("_read_yaml") as read_spy:
            self.service.current_project()  # warm-cache within this second call
        for ancestor in (self.universe, self.series):
            manifest = ancestor / "project.yaml"
            reads = [c for c in read_spy.call_args_list if c.args and c.args[0] == manifest]
            self.assertEqual(len(reads), 1, f"{ancestor.name} manifest parsed {len(reads)}x")
        self.assertTrue(spy.called)


class AWriteDropsTheMemoTests(ChainWalkMemoTestCase):
    def test_a_retitle_through_the_service_is_seen_within_the_request(self) -> None:
        """The memo lives one request, but a request may both read and write.
        A write routes `_maintain_index_after_write`, which clears the memo, so
        the read after it sees disk — not the value cached before it."""
        self.assertEqual(self.service._project_title(self.universe), "The Honorverse")

        self.service._write_yaml(self.universe / "project.yaml", {"title": "Renamed"})

        self.assertEqual(self.service._project_title(self.universe), "Renamed")

    def test_a_write_drops_the_walk_memo_too(self) -> None:
        self.service.declared_ancestor_candidates(self.book)

        with self._spy("_declared_ancestors") as spy:
            # Any write clears the memo; a scene write is enough.
            self.service._write_yaml(self.book / "project.yaml", {"title": "On Basilisk Station"})
            self.service.declared_ancestor_candidates(self.book)

        self.assertEqual(spy.call_count, 1)


class TheMemoDoesNotChangeTheAnswerTests(ChainWalkMemoTestCase):
    def test_current_project_still_reports_the_whole_chain(self) -> None:
        info = self.service.current_project()

        self.assertEqual(
            [layer.folder for layer in self.service.collect_layers(self.book)],
            [self.universe, self.series, self.book],
        )
        self.assertEqual(
            [row.title for row in info.ancestors if row.is_project],
            ["The Honorverse", "Honor Harrington"],
        )


if __name__ == "__main__":
    unittest.main()
