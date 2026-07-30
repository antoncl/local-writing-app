"""Recording browser-reported runtime errors to the error log (#386, #741).

The UI has no filesystem, so a failure it catches (the single `run()` funnel, an
unhandled rejection) is POSTed here and appended to `errors.log` with
`origin: browser`. It lands in the open project's log when a project is open, and
in the machine-scope log (`error_log_dir()/errors.log`) when none is (#741) — the
report carries no `X-Project-Root`, so `root_path` is `None`. The backend's own
`500`s are recorded separately, by the request middleware in `app.main`.
"""

from __future__ import annotations

from app.models import ClientErrorReport
from app.services.error_log import append_error_line
from app.services.machine_settings import error_log_dir


class ClientErrorLogMixin:
    """Append a browser-reported error to the project or machine log."""

    def record_client_error(self, report: ClientErrorReport) -> None:
        root = self.root_path  # type: ignore[attr-defined]  # provided by ProjectService via MRO
        machine_scope = root is None
        append_error_line(
            error_log_dir() if machine_scope else root,
            origin="browser",
            message=report.message,
            context=report.context,
            detail=report.detail,
            # The config dir may not exist yet when no project has ever been
            # opened; create it. A real project root always exists already.
            ensure_dir=machine_scope,
        )
