"""The resolution scope is derived from the request, not from process state (#413).

ADR-0045: *scope belongs to the unit of work*, and the choke point that reads it
is what covers **restart** (which is not a switch). #399 made the scope a frozen
property of a per-request `ProjectService`; #413 put it on the wire — the
`X-Project-Root` header — and deleted `current_scope`, the last process-wide
record of what was open.

These tests exercise the real resolver over the ASGI boundary with explicit
per-request headers (the autouse conftest fixture only fills a header in when the
test did not set one, so an explicit `X-Project-Root` wins). They are the
successor to the `current_scope`-swap race tests: those simulated a shared mutable
being swapped mid-unit; here there is no shared mutable to swap, so the property
is shown directly — a request lands in the project *its own header* names,
whatever else happened first.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.main import app


def _hdr(root: Path) -> dict[str, str]:
    """The header the browser's `api.ts` sends — URL-encoded project root."""
    return {"X-Project-Root": quote(str(root), safe="")}


class ScopeOnTheWireTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.base = Path(self.temp_dir.name).resolve() / "writing"
        self.client = TestClient(app)
        # Two real projects on disk, created through the wire like the app does.
        self.book1 = self.base / "book01"
        self.book2 = self.base / "book02"
        for root, title in ((self.book1, "Book One"), (self.book2, "Book Two")):
            created = self.client.post(
                "/api/project/create", json={"root_path": str(root), "title": title}
            )
            self.assertEqual(created.status_code, 200, created.text)
        # `create` resolved each to an absolute root; use that verbatim as the
        # header so the memo key and the write target agree.
        self.book1_root = self.book1.resolve()
        self.book2_root = self.book2.resolve()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_scope_comes_from_the_request_not_from_what_was_last_opened(self) -> None:
        """Interleaved reads for two projects each resolve their own, with no
        process state deciding it — the property `current_scope` could not give."""
        one = self.client.get("/api/project", headers=_hdr(self.book1_root))
        two = self.client.get("/api/project", headers=_hdr(self.book2_root))

        self.assertEqual(one.json()["title"], "Book One")
        self.assertEqual(two.json()["title"], "Book Two")

    def test_a_stale_write_lands_in_its_own_project_after_the_world_moved_on(self) -> None:
        """The acceptance case: the resolver's view of the world changes between
        a unit capturing its project and its write arriving.

        The buffer is editing book01, so its write carries book01's header. In
        between, book02 is the project that got opened (a restart, or simply
        another pane) — the only `/open` this process has seen. The write must
        still land in book01, or fail; never in book02, which is what an ambient
        "whatever is open now" would have done.
        """
        # The world moves on: book02 is what got opened.
        opened = self.client.post("/api/project/open", json={"root_path": str(self.book2_root)})
        self.assertEqual(opened.status_code, 200, opened.text)

        # The late write for book01 arrives, carrying its own project on the wire.
        wrote = self.client.post(
            "/api/lore",
            json={"title": "Stale But Correct", "entry_type": "lore:character"},
            headers=_hdr(self.book1_root),
        )
        self.assertEqual(wrote.status_code, 200, wrote.text)

        # It landed in book01 and nowhere near book02.
        book1_files = list((self.book1_root / "lore").glob("*.md"))
        self.assertTrue(
            any("Stale But Correct" in p.read_text(encoding="utf-8") for p in book1_files),
            "the write did not land in book01",
        )
        book2_lore = self.book2_root / "lore"
        book2_files = list(book2_lore.glob("*.md")) if book2_lore.exists() else []
        self.assertFalse(
            any("Stale But Correct" in p.read_text(encoding="utf-8") for p in book2_files),
            "the write leaked into book02 — the exact failure #413 closes",
        )

    def test_the_open_route_drops_the_node_index_memo(self) -> None:
        """The open event rebuilds the index (#392/#476).

        #413 moved this invalidation off the deleted `CurrentScope.set` and onto
        the open *event* — `ProjectService.open` -> `_register_open_event` (#977
        folded it out of the route handler). It must fire on that event and not in
        the per-request resolver (which builds a throwaway service every call), so
        the `/open` round trip is what this pins: without the invalidate, a reopen
        after an external backup-restore would serve the pre-restore index — and a
        plain browser F5 re-runs `/open`, so this is the gesture that saves that user.
        """
        from app.scope import WorkScope
        from app.services.project.node_index_gate import node_index_gate
        from app.services.project_service import ProjectService

        # Warm the memo for book01.
        ProjectService(WorkScope(root=self.book1_root))._build_node_index(self.book1_root)
        self.assertIsNotNone(node_index_gate.peek(self.book1_root), "the memo did not warm")

        # Reopening book01 through the route must drop it, so the next resolve
        # rebuilds from disk.
        opened = self.client.post("/api/project/open", json={"root_path": str(self.book1_root)})
        self.assertEqual(opened.status_code, 200, opened.text)
        self.assertIsNone(
            node_index_gate.peek(self.book1_root),
            "POST /api/project/open did not invalidate the node-index memo",
        )

    def test_a_request_with_no_scope_is_unbound_rather_than_refused(self) -> None:
        """An absent header is not policed at the boundary: the machine-level
        surfaces run unbound, and a route that needs a root still 409s through
        `_require_project` — the pre-#413 behaviour, unchanged."""
        unbound = self.client.get("/api/project")  # no header at all

        self.assertEqual(unbound.status_code, 409)
        self.assertIn("No project is open", unbound.text)

    def test_a_header_naming_a_non_project_never_falls_back_to_an_open_one(self) -> None:
        """A header that is not a project resolves to *that path*, never to some
        other still-open project.

        There is deliberately no gate at the boundary — a single-user app lets a
        client point itself at a junk folder (the same self-inflicted footgun as
        deleting a project's files mid-session), so this returns 200 for the junk
        folder itself. The guarantee #413 makes is not a refusal but the absence
        of a *fallback*: with `current_scope` deleted, a bad header cannot be
        silently redirected onto whatever was open — the failure mode it closes.
        """
        # book02 is genuinely open, so a fallback (if one existed) would surface it.
        self.client.post("/api/project/open", json={"root_path": str(self.book2_root)})
        stray = self.base / "not-a-project"
        stray.mkdir(parents=True)

        result = self.client.get("/api/project", headers=_hdr(stray))

        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["title"], "not-a-project")  # the path it named
        self.assertNotIn("Book One", result.text)
        self.assertNotIn("Book Two", result.text)


if __name__ == "__main__":
    unittest.main()
