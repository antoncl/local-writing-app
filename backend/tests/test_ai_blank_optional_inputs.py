"""#2578: a blank optional prompt input reaches the template defined but empty.

The frontend ships a blank optional input as `""` (text) or `null` (every other
scalar) instead of dropping it; these tests pin that both survive the bind layer
and that `{% if inputs.x %}` renders over them. The renderer is StrictUndefined,
so the dropped key — the shape before the fix — is the UndefinedError a user
saw running a prompt with an optional input left blank.
"""

from __future__ import annotations

import pytest

TEMPLATE = (
    '{% role "system" %}'
    "{% if inputs.situation %}in: {{ inputs.situation }}{% else %}no situation{% endif %} "
    "{% if inputs.flag is none %}flag unset{% elif inputs.flag %}flag on{% else %}flag off{% endif %}"
    "{% endrole %}"
)


def _render(tmp_path, monkeypatch, inputs: dict) -> str:
    monkeypatch.setattr(
        "app.services.machine_settings.config_path",
        lambda: tmp_path / "machine_settings.yaml",
    )
    from app.services.ai.preview import PreviewRequest, build_preview
    from app.services.project_service import ProjectService

    service = ProjectService.created_at(tmp_path / "project", "Blanks")
    rendered, _ = build_preview(
        service,
        PreviewRequest(
            template_source=TEMPLATE,
            target_scene_id="",
            session_id=None,
            inputs=inputs,
            text_before="",
            text_after="",
            commit=False,
        ),
    )
    return "".join(m.text for m in rendered.messages)


def test_a_dropped_optional_input_is_the_undefined_error(tmp_path, monkeypatch):
    from app.services.ai.preview import PreviewError

    with pytest.raises(PreviewError) as ctx:
        _render(tmp_path, monkeypatch, {})
    assert ctx.value.kind == "undefined"
    assert "situation" in str(ctx.value)


def test_blank_optional_inputs_render_as_empty(tmp_path, monkeypatch):
    text = _render(tmp_path, monkeypatch, {"situation": "", "flag": None})
    assert "no situation" in text
    assert "flag unset" in text


@pytest.mark.parametrize(("flag", "expected"), [(True, "flag on"), (False, "flag off")])
def test_a_boolean_is_tri_state(tmp_path, monkeypatch, flag, expected):
    text = _render(tmp_path, monkeypatch, {"situation": "a storm", "flag": flag})
    assert "in: a storm" in text
    assert expected in text
