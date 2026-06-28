"""The ProjectService error type.

Lives in its own module so the per-kind mixin slices (chats, scenes, …)
and the core `project_service.py` can both import it without a circular
import. `project_service.py` re-exports it, so the historic import path
`from app.services.project_service import ProjectServiceError` keeps
working for main.py and the test-suite.
"""

from __future__ import annotations


class ProjectServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
