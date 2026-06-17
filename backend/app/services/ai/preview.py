"""Preview dispatch — renders a template against a target scene and returns
structured messages for the UI to render.

This is the M2.4 surface. It does NOT call any model — preview is for staring
at the assembled prompt before paying tokens for it.
"""

from __future__ import annotations

from typing import Any

from jinja2 import TemplateError

from app.services.ai.helpers import create_environment_for_project
from app.services.ai.sessions import AISession, default_registry
from app.services.ai.templates import RenderedTemplate, render_template


class PreviewError(Exception):
    """Raised when the template can't be rendered (syntax, undefined var, etc.)."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def build_preview(
    *,
    project_service,
    template_source: str,
    target_scene_id: str,
    session_id: str | None,
    inputs: dict[str, Any],
    text_before: str,
    text_after: str,
    commit: bool,
) -> tuple[RenderedTemplate, str | None]:
    """Render the template and return (output, session_id_used).

    `session_id_used` is None when no session was bound (caller did not supply
    one), so the response surface can report 'no caching' to the user.
    """
    try:
        scene = project_service.read_scene(target_scene_id)
    except Exception as exc:  # noqa: BLE001
        raise PreviewError(f"Target scene not found: {exc}", 404) from exc

    session: AISession | None = None
    if session_id:
        session = default_registry.get_or_create(session_id)
        # Each preview render is its own "what was pulled in this call" snapshot;
        # clear touched so we don't carry over IDs from a previous render.
        session.touched = {}

    env = create_environment_for_project(project_service, session=session)

    try:
        project_info = project_service.current_project()
    except Exception:  # noqa: BLE001
        project_info = None

    context = {
        "scene": scene,
        "project": project_info,
        "input": inputs,
        "text_before": text_before,
        "text_after": text_after,
    }

    try:
        rendered = render_template(template_source, context=context, env=env)
    except TemplateError as exc:
        raise PreviewError(f"{type(exc).__name__}: {exc.message}", 422) from exc

    if session is not None and commit:
        session.commit()

    return rendered, session_id
