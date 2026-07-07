"""Shared FastAPI runtime: the process-wide ProjectService singleton and the
error-translation context manager (#170).

Extracted from main.py so router modules can share them without importing the
app module. The singleton is deliberate module-level state: every router imports
THIS same `service` object, so `open_project()` mutating it in place stays
globally visible — the exact behavior main.py had when it owned the global.
"""

from __future__ import annotations

from contextlib import contextmanager

from fastapi import HTTPException

from app.services.project_service import ProjectService, ProjectServiceError

service = ProjectService()


@contextmanager
def translate_errors():
    try:
        yield
    except ProjectServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
