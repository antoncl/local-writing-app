"""The durable AI commit-pipeline trace (#2260): the writer itself.

`ai_trace.jsonl`'s content is exercised end-to-end where it's written
(`test_ai_extraction.py`, `test_plot_beats.py`); this covers the writer in
isolation — no project, rotation, and the never-raises guarantee.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from project_fixtures import open_test_project

from app.services.project import ai_trace
from app.services.project_service import ProjectService


class RecordAiTraceTests:
    def test_no_project_open_is_a_no_op(self) -> None:
        service = ProjectService()  # no scope bound — no project open
        service.record_ai_trace({"event": "x"})  # must not raise
        assert service.root_path is None

    def test_appends_one_json_line_with_a_leading_timestamp(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "project"
            service = open_test_project(root, "AI trace")
            service.record_ai_trace({"event": "ai_commit_extraction", "ok": True})
            text = (root / ai_trace.TRACE_FILENAME).read_text(encoding="utf-8")
            lines = text.strip().splitlines()
            assert len(lines) == 1
            record = json.loads(lines[0])
            assert record["event"] == "ai_commit_extraction"
            assert record["ok"] is True
            assert "ts" in record

    def test_rotates_at_the_cap(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "project"
            service = open_test_project(root, "AI trace rotation")
            with patch.object(ai_trace, "_MAX_BYTES", 10):
                service.record_ai_trace({"event": "first"})
                service.record_ai_trace({"event": "second"})
            rotated = (root / "ai_trace.1.jsonl").read_text(encoding="utf-8")
            current = (root / ai_trace.TRACE_FILENAME).read_text(encoding="utf-8")
            assert json.loads(rotated.strip().splitlines()[0])["event"] == "first"
            assert json.loads(current.strip().splitlines()[0])["event"] == "second"

    def test_a_write_failure_never_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "project"
            service = open_test_project(root, "AI trace write failure")
            with patch("pathlib.Path.open", side_effect=OSError("disk full")):
                service.record_ai_trace({"event": "x"})  # must not raise
