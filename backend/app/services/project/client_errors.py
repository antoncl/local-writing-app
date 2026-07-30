"""Recording browser-reported runtime errors to the project log (#386).

The UI has no filesystem, so a failure it catches (the single `run()` funnel, an
unhandled rejection) is POSTed here and appended to the open project's
`errors.log` with `origin: browser`. The backend's own `500`s are recorded
separately, by the request middleware in `app.main`.
"""

from __future__ import annotations

from app.models import ClientErrorReport
from app.services.error_log import append_error_line


class ClientErrorLogMixin:
    """Append a browser-reported error to the open project's log."""

    def record_client_error(self, report: ClientErrorReport) -> None:
        root = self.root_path  # type: ignore[attr-defined]  # provided by ProjectService via MRO
        if root is None:
            # No project open → no per-project log in slice 1; machine-level
            # scope is the question slice 2 settles (#386). Nothing to record.
            return
        append_error_line(
            root,
            origin="browser",
            message=report.message,
            context=report.context,
            detail=report.detail,
        )
