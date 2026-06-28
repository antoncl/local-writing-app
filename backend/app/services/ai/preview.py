"""Preview + generation dispatch.

Preview (`build_preview`) renders a template against a target scene and
returns structured messages. It does NOT call a model. M2.4.

Generation (`build_chat_payload` + caller) converts the rendered template
into the chat-API shape (system_prompt + alternating user/assistant
messages). The actual chat call lives in the route handler, which has
access to settings and policy. M4.0.
"""

from __future__ import annotations

import json
import re
from datetime import date as _date_cls
from typing import Any

from jinja2 import TemplateError, UndefinedError, TemplateSyntaxError

from app.services.ai.helpers import EntryRef, create_environment_for_project
from app.services.ai.sessions import AISession, default_registry
from app.services.ai.templates import RenderedTemplate, render_template


def _find_marked_target_scene_id(inputs: dict[str, Any]) -> str | None:
    """Scan context_pick input values for a scene ref marked as ★ target.

    The picker UI flags a single picked scene per input with `target: true`;
    if any input carries such a ref, the marked scene becomes the template's
    `scene` binding (overriding any caller-supplied target_scene_id). Returns
    the first match; the picker enforces at most one per input, but if two
    inputs each mark a scene, the first by iteration order wins.

    Frontend serializes context_pick values as JSON strings (see
    PromptInputField.svelte). Accept either a string or an already-decoded
    list so backend tests can pass plain Python structures.
    """
    for value in inputs.values():
        if isinstance(value, str):
            stripped = value.strip()
            if not (stripped.startswith("[") and stripped.endswith("]")):
                continue
            try:
                value = json.loads(stripped)
            except (ValueError, TypeError):
                continue
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            if item.get("target") and item.get("kind") == "scene":
                scene_id = item.get("id")
                if isinstance(scene_id, str) and scene_id:
                    return scene_id
    return None


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

    `kind` is a coarse classification consumed by /api/ai/preview to populate
    `AIPreviewResponse.error.kind`; the frontend uses it (with `undefined_name`)
    to render a friendly message without re-parsing `message`.
    """

    def __init__(
        self,
        message: str,
        status_code: int = 422,
        *,
        line: int | None = None,
        col: int | None = None,
        kind: str = "other",
        undefined_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.line = line
        self.col = col
        self.kind = kind
        self.undefined_name = undefined_name


# UndefinedError messages from Jinja2 look like:
#   "'dict object' has no attribute 'character'"
#   "'character' is undefined"
_UNDEFINED_ATTR_RE = re.compile(r"has no attribute '([^']+)'")
_UNDEFINED_NAME_RE = re.compile(r"'([^']+)' is undefined")


def _extract_undefined_name(message: str) -> str | None:
    m = _UNDEFINED_ATTR_RE.search(message)
    if m:
        return m.group(1)
    m = _UNDEFINED_NAME_RE.search(message)
    if m:
        return m.group(1)
    return None


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
    # A scene marked ★ in any context_pick input wins over the caller's
    # implicit target_scene_id. This is the NC-style pattern: the user
    # picks the focus scene in the context picker (per-invocation) instead
    # of relying on dispatch context.
    effective_scene_id = _find_marked_target_scene_id(inputs) or target_scene_id

    if effective_scene_id:
        try:
            scene = project_service.read_scene(effective_scene_id)
        except Exception as exc:  # noqa: BLE001
            raise PreviewError(
                f"Target scene not found: {exc}",
                404,
                kind="scene_not_found",
            ) from exc
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

    # Wrap the loaded scene as an EntryRef so templates can write
    # `scene.pov.title` instead of `scene.metadata.pov.title`. The wrapper
    # pre-fills `loaded=` so .title / .body_markdown don't trigger a re-read,
    # and helpers reach the raw payload via _attr_or_item's EntryRef path.
    if scene is not None:
        try:
            schema = project_service.read_metadata_schema()
        except Exception:  # noqa: BLE001
            schema = None
        scene = EntryRef(project_service, schema, scene.id, loaded=scene)

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
        if isinstance(exc, UndefinedError):
            kind = "undefined"
            undefined_name = _extract_undefined_name(exc.message or "")
        elif isinstance(exc, TemplateSyntaxError):
            kind = "syntax"
            undefined_name = None
        else:
            kind = "other"
            undefined_name = None
        raise PreviewError(
            f"{type(exc).__name__}: {exc.message}",
            422,
            line=int(line) if isinstance(line, int) else None,
            kind=kind,
            undefined_name=undefined_name,
        ) from exc

    if session is not None and commit:
        session.commit()

    return rendered, session_id


def build_chat_payload(rendered: RenderedTemplate) -> tuple[str, list[dict[str, str]]]:
    """Convert a RenderedTemplate into a chat-API payload.

    System messages are concatenated into a single system_prompt string.
    User and assistant messages pass through in order, with two safety
    transforms: whitespace-only messages are dropped (an empty conditional
    in the template shouldn't emit a no-op turn), and consecutive
    same-role messages are coalesced (Anthropic rejects user/user or
    assistant/assistant pairs outright; this also keeps OpenAI happy).
    Other roles are ignored — warnings on the rendered template already
    flag them.

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
            if not text.strip():
                continue
            if chat_messages and chat_messages[-1]["role"] == msg.role:
                chat_messages[-1]["content"] = chat_messages[-1]["content"].rstrip() + "\n\n" + text.lstrip()
            else:
                chat_messages.append({"role": msg.role, "content": text})
    system_prompt = "\n\n".join(system_parts)
    return system_prompt, chat_messages
