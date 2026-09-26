"""Durable trace of AI brainstorm-commit pipeline decisions (#2260).

Before this, a wrong or missing AI change — a beat that vanished, a field
that silently didn't land — had nothing durable behind it: `errors.log`
(`services/error_log.py`) only ever recorded UNUSABLE patches (garbled or
empty, #2195), so a patch that was well-formed but wrong (a dropped field, a
beat the model renamed onto another beat's id, a truncated roster the old
`_close_unbalanced` repair silently shortened) left no record of what the
model actually returned or what the pipeline did with it. `ai_trace.jsonl` is
that record: one JSON line per interesting event
(`ai_commit_extraction`/`plot_beats_saved`/`beat_links_healed`), so an author
or a developer can attribute the outcome to the model's reply, schema
validation, id reconciliation, truncation, or the save — not just observe
that something went wrong.

Deliberately NOT `errors.log`: this traces normal operation (most records
describe a SUCCESSFUL commit), not failures, and it is high-volume enough
(one record per commit attempt) that it gets its own rotation.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

TRACE_FILENAME = "ai_trace.jsonl"

# Rotate before the file grows unbounded — a long dogfooding session commits
# constantly, and nothing here is prunable (each line stands alone). 5 MB is
# generous for a jsonl of small structured records while staying well short
# of "large file a text editor struggles with".
_MAX_BYTES = 5 * 1024 * 1024


class AITraceMixin:
    """Append one JSON line per AI commit-pipeline event to the open
    project's `ai_trace.jsonl` — the one place the rotation and
    never-raises rules live."""

    def record_ai_trace(self, record: dict[str, Any]) -> None:
        """Append `record` (plus a leading `"ts"`) as one JSON line. Never
        raises — a trace we couldn't write is strictly less bad than an
        extraction or save that failed because tracing did (mirrors
        `append_error_line`'s #386 acceptance). A no-op when no project is
        open: there is nowhere to put the file."""
        root = self.root_path  # type: ignore[attr-defined]  # from ProjectService via MRO
        if root is None:
            return
        try:
            path = root / TRACE_FILENAME
            if path.exists() and path.stat().st_size >= _MAX_BYTES:
                rotated = root / "ai_trace.1.jsonl"
                # `replace` overwrites any previous rotated file — one
                # generation of history is enough for this trace's purpose.
                path.replace(rotated)
            line = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), **record}
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        except Exception:
            # Same acceptance as `append_error_line` (#386): tracing must
            # never break the operation it's tracing.
            log.warning("Failed to write ai_trace.jsonl record", exc_info=True)
