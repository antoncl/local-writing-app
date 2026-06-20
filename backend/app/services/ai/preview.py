"""Preview + generation dispatch.

Preview (`build_preview`) renders a template against a target scene and
returns structured messages. It does NOT call a model. M2.4.

Generation (`build_chat_payload` + caller) converts the rendered template
into the chat-API shape (system_prompt + alternating user/assistant
messages). The actual chat call lives in the route handler, which has
access to settings and policy. M4.0.
"""

from __future__ import annotations

from datetime import date as _date_cls
from typing import Any

from jinja2 import TemplateError

from app.services.ai.helpers import create_environment_for_project
from app.services.ai.sessions import AISession, default_registry
from app.services.ai.templates import RenderedTemplate, render_template


class _DateProxy:
    """Exposes the current date as `date.today`, `date.iso`, and bare {{ date }}.

    Avoids confusion with Python's `date.today()` callable: `{{ date.today }}` returns
    the ISO string for today, not a method object.
    """

    def __init__(self, today: _date_cls) -> None:
        self._today = today

    @property
    def today(self) -> str:
        return self._today.isoformat()

    @property
    def iso(self) -> str:
        return self._today.isoformat()

    def __str__(self) -> str:
        return self._today.isoformat()


class PreviewError(Exception):
    """Raised when the template can't be rendered (syntax, undefined var, etc.).

    `line` and `col` are populated when the underlying Jinja2 error carries
    location info — surfacing them lets the editor pin a gutter marker on
    the offending line in the inline preview.
    """

    def __init__(
        self,
        message: str,
        status_code: int = 422,
        *,
        line: int | None = None,
        col: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.line = line
        self.col = col


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
    selection: str = "",
) -> tuple[RenderedTemplate, str | None]:
    """Render the template and return (output, session_id_used).

    `session_id_used` is None when no session was bound (caller did not supply
    one), so the response surface can report 'no caching' to the user.
    """
    if target_scene_id:
        try:
            scene = project_service.read_scene(target_scene_id)
        except Exception as exc:  # noqa: BLE001
            raise PreviewError(f"Target scene not found: {exc}", 404) from exc
    else:
        # Chat-routed prompts may not target a specific scene. Templates that
        # reference `scene` will see None and can guard with `{% if scene %}`.
        scene = None

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
        "novel": project_info,
        "input": inputs,
        "text_before": text_before,
        "text_after": text_after,
        "selection": selection,
        "date": _DateProxy(_date_cls.today()),
    }

    try:
        rendered = render_template(template_source, context=context, env=env)
    except TemplateError as exc:
        # `lineno` is set for TemplateSyntaxError and most subclasses; for
        # UndefinedError it's typically missing. Surface what we have.
        line = getattr(exc, "lineno", None)
        # Jinja2 doesn't expose column info on TemplateError; col stays None.
        raise PreviewError(
            f"{type(exc).__name__}: {exc.message}",
            422,
            line=int(line) if isinstance(line, int) else None,
        ) from exc

    if session is not None and commit:
        session.commit()

    return rendered, session_id


def build_chat_payload(rendered: RenderedTemplate) -> tuple[str, list[dict[str, str]]]:
    """Convert a RenderedTemplate into a chat-API payload.

    System messages are concatenated into a single system_prompt string.
    User and assistant messages pass through verbatim in order. Other roles
    are ignored (warnings on the rendered template already flag them).

    Returns: (system_prompt, messages)
    """
    system_parts: list[str] = []
    chat_messages: list[dict[str, str]] = []
    for msg in rendered.messages:
        text = "".join(block.text for block in msg.blocks)
        if msg.role == "system":
            if text.strip():
                system_parts.append(text)
        elif msg.role in ("user", "assistant"):
            chat_messages.append({"role": msg.role, "content": text})
    system_prompt = "\n\n".join(system_parts)
    return system_prompt, chat_messages
