"""The durable error log (#386, #741): the writer, the browser route, the middleware.

Three seams under test: `append_error_line` (the swallowing writer), the
`POST /api/log` route that records a browser-origin line, and the `main.py`
middleware that gives a genuine `500` a backend-origin line before it vanishes.
Each seam is exercised in both scopes — the open project's log, and the
machine-scope log (`error_log_dir()`) used when no project is bound (#741).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient
from project_fixtures import clear_test_scope, open_test_project

from app.main import app
from app.models import ClientErrorReport
from app.services.error_log import LOG_FILENAME, append_error_line
from app.services.machine_settings import error_log_dir
from app.services.project_service import ProjectService


def _log_text(root: Path) -> str:
    return (root / LOG_FILENAME).read_text(encoding="utf-8")


class TestAppendErrorLine:
    """The writer is a pure, swallowing append — no service, no HTTP."""

    def test_writes_a_single_timestamped_line(self, tmp_path: Path) -> None:
        append_error_line(
            tmp_path, origin="browser", message="boom", context="save", detail="stack"
        )
        text = _log_text(tmp_path)
        assert text.count("\n") == 1
        assert text.startswith("[")  # bracketed timestamp
        assert "browser error: boom" in text
        assert "(context: save)" in text
        assert "— stack" in text

    def test_appends_rather_than_truncates(self, tmp_path: Path) -> None:
        append_error_line(tmp_path, origin="browser", message="first")
        append_error_line(tmp_path, origin="backend", message="second")
        lines = _log_text(tmp_path).strip().split("\n")
        assert len(lines) == 2
        assert "first" in lines[0]
        assert "second" in lines[1]

    def test_multiline_message_and_detail_collapse_to_one_line(self, tmp_path: Path) -> None:
        append_error_line(
            tmp_path, origin="backend", message="a\nb", detail="trace\nline2\nline3"
        )
        text = _log_text(tmp_path)
        assert text.count("\n") == 1  # one failure is one physical line
        assert "a b" in text
        assert "trace line2 line3" in text

    def test_optional_fields_are_omitted_when_absent(self, tmp_path: Path) -> None:
        append_error_line(tmp_path, origin="browser", message="bare")
        text = _log_text(tmp_path)
        assert "context:" not in text
        assert "—" not in text

    def test_a_blank_message_gets_a_placeholder(self, tmp_path: Path) -> None:
        # A bare Error()/`throw ""` still deserves a line — the silent-failure
        # class this log exists to catch must not itself vanish.
        append_error_line(tmp_path, origin="browser", message="", context="run")
        text = _log_text(tmp_path)
        assert "browser error: (no message)" in text
        assert "(context: run)" in text

    def test_a_failed_write_is_swallowed(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"  # parent dir absent → open('a') raises
        append_error_line(missing, origin="backend", message="boom")  # must not raise
        assert not (missing / LOG_FILENAME).exists()

    def test_ensure_dir_creates_a_missing_root(self, tmp_path: Path) -> None:
        # The machine-scope path (#741): the config dir may not exist yet when the
        # first error is a project-open failure before any settings were saved.
        missing = tmp_path / "config" / "nested"  # neither level exists
        append_error_line(missing, origin="backend", message="boom", ensure_dir=True)
        assert "backend error: boom" in _log_text(missing)


class TestRecordClientError:
    """The mixin bridges a browser report to the project or machine log."""

    def test_writes_a_browser_line_to_the_open_project(self, tmp_path: Path) -> None:
        service = ProjectService.created_at(tmp_path / "book", "Book")
        service.record_client_error(
            ClientErrorReport(message="ui blew up", context="save-scene", detail="Error: x")
        )
        text = _log_text(service.root_path)
        assert "browser error: ui blew up" in text
        assert "(context: save-scene)" in text

    def test_no_project_open_writes_to_the_machine_log(self) -> None:
        # Unbound (no project open) is no longer a no-op (#741): the report lands
        # in the machine-scope log. `error_log_dir()` is isolated to a per-test
        # tempdir by the autouse conftest fixture (via the patched config_path).
        service = ProjectService(None)
        service.record_client_error(
            ClientErrorReport(message="pre-open boom", context="open-project")
        )
        text = _log_text(error_log_dir())
        assert "browser error: pre-open boom" in text
        assert "(context: open-project)" in text


class TestLogHttp(unittest.TestCase):
    """The `/api/log` route and the unhandled-error middleware over the ASGI surface."""

    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name).resolve() / "book"
        self.service = open_test_project(self.root, "Book")
        self.client = TestClient(app)

    def tearDown(self) -> None:
        clear_test_scope()
        self.temp.cleanup()

    def test_post_log_writes_a_browser_line_and_returns_204(self) -> None:
        resp = self.client.post(
            "/api/log",
            json={"message": "client failure", "context": "open-project", "detail": "TypeError: nope"},
        )
        self.assertEqual(resp.status_code, 204, resp.text)
        text = _log_text(self.root)
        self.assertIn("browser error: client failure", text)
        self.assertIn("(context: open-project)", text)

    def test_a_blank_or_missing_message_is_recorded_not_rejected(self) -> None:
        # The blank-message class is exactly what must not be dropped: accept it
        # (no 422) and write a placeholder line rather than swallowing a 422.
        resp = self.client.post("/api/log", json={"context": "open-project"})
        self.assertEqual(resp.status_code, 204, resp.text)
        text = _log_text(self.root)
        self.assertIn("browser error: (no message)", text)
        self.assertIn("(context: open-project)", text)

    def test_an_unhandled_500_records_a_backend_line(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)
        with patch.object(
            ProjectService, "record_client_error", side_effect=ValueError("kaboom in the route")
        ):
            resp = client.post("/api/log", json={"message": "x"})
        self.assertEqual(resp.status_code, 500)
        text = _log_text(self.root)
        self.assertIn("backend error: ValueError: kaboom in the route", text)
        self.assertIn("POST /api/log", text)

    def test_post_log_with_no_project_open_writes_to_the_machine_log(self) -> None:
        # No project bound → no X-Project-Root on the wire → the browser report
        # lands in the machine-scope log, not the project one (#741).
        clear_test_scope()
        resp = self.client.post(
            "/api/log", json={"message": "pre-open failure", "context": "open-project"}
        )
        self.assertEqual(resp.status_code, 204, resp.text)
        text = _log_text(error_log_dir())
        self.assertIn("browser error: pre-open failure", text)
        self.assertFalse((self.root / LOG_FILENAME).exists())  # not the project log

    def test_an_unhandled_500_with_no_project_records_a_machine_backend_line(self) -> None:
        # The class slice 1 could not catch: a 500 with no project bound (a bad
        # ancestor manifest while resolving /api/project/open) now lands machine-side.
        clear_test_scope()
        client = TestClient(app, raise_server_exceptions=False)
        with patch.object(
            ProjectService, "record_client_error", side_effect=ValueError("kaboom, no project")
        ):
            resp = client.post("/api/log", json={"message": "x"})
        self.assertEqual(resp.status_code, 500)
        text = _log_text(error_log_dir())
        self.assertIn("backend error: ValueError: kaboom, no project", text)
        self.assertIn("POST /api/log", text)


if __name__ == "__main__":
    unittest.main()
