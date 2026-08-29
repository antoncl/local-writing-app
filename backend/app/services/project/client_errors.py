"""Recording runtime errors to the error log (#386, #741, #1601).

Two origins feed the same durable log. A **browser** failure (the single `run()`
funnel, an unhandled rejection) is POSTed here because the UI has no filesystem.
A **backend** AI-stream failure (a rate-limit, a bad key, an empty completion) is
recorded straight from the dispatch layer. Both land in the open project's
`errors.log` when a project is open, and in the machine-scope log
(`error_log_dir()/errors.log`) when none is (#741). The backend's own `500`s are
recorded separately, by the request middleware in `app.main`.
"""

from __future__ import annotations

from app.models import ClientErrorReport
from app.services.error_log import append_error_line
from app.services.machine_settings import error_log_dir


class ErrorLogMixin:
    """Append a runtime error (browser- or backend-originated) to the project or
    machine error log — the one place the project-vs-machine scope rule lives."""

    def _append_scoped(
        self,
        *,
        origin: str,
        message: str,
        context: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Resolve the log's scope (project when one is open, machine otherwise,
        #741) and append one line. Never raises — `append_error_line` swallows,
        so recording a failure can't break the operation it records."""
        root = self.root_path  # type: ignore[attr-defined]  # from ProjectService via MRO
        machine_scope = root is None
        append_error_line(
            error_log_dir() if machine_scope else root,
            origin=origin,
            message=message,
            context=context,
            detail=detail,
            # The config dir may not exist yet when no project has ever been
            # opened; create it. A real project root always exists already.
            ensure_dir=machine_scope,
        )

    def record_client_error(self, report: ClientErrorReport) -> None:
        """Record a browser-reported runtime failure (origin `browser`)."""
        self._append_scoped(
            origin="browser",
            message=report.message,
            context=report.context,
            detail=report.detail,
        )

    def record_ai_error(
        self, *, message: str, provider: str, model: str, detail: str | None = None
    ) -> None:
        """Record an AI stream failure (origin `backend`, #1601). `detail` carries
        developer diagnostics (e.g. the empty-stream dump) into the log — never to
        the user, who saw only the plain `message`."""
        self._append_scoped(
            origin="backend",
            message=message,
            context=f"ai {provider}/{model}".strip(),
            detail=detail,
        )
