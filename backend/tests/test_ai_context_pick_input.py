"""The new `context_pick` prompt input type. v1 backend slice:
PromptInputDefinition accepts the new type literal and round-trips its
`target` payload (kinds/entry_types/presets/multiple) through Pydantic
validation and prompt-entry save/read.

Per docs/context-picker.md. ADR-0060 §2 delivers the render-time wrapping the
v1 slice deferred: a picked `context_pick` value reaches the template as a
`list[EntryRef]` (bind-layer coercion), so `{% for p in inputs.x %}{{ use(p) }}`
iterates refs and selects every pick (Journey A).
"""

from __future__ import annotations

import json

from app.models import PromptInputDefinition


def test_context_pick_input_validates_with_kinds_and_presets():
    spec = PromptInputDefinition.model_validate(
        {
            "name": "reference_scenes",
            "type": "context_pick",
            "label": "Reference scenes",
            "required": False,
            "target": {
                "kinds": ["scene", "lore"],
                "entry_types": {"lore": ["lore:character", "lore:location"]},
                "presets": ["full_outline"],
                "multiple": True,
            },
        }
    )
    assert spec.type == "context_pick"
    assert spec.target is not None
    assert spec.target["kinds"] == ["scene", "lore"]
    assert spec.target["presets"] == ["full_outline"]
    assert spec.target["entry_types"]["lore"] == ["lore:character", "lore:location"]


def test_context_pick_input_allows_empty_target():
    # Author may be saving a draft mid-config; backend doesn't reject
    # missing target. Frontend validation gates the user-friendly path.
    spec = PromptInputDefinition.model_validate(
        {
            "name": "scenes",
            "type": "context_pick",
        }
    )
    assert spec.type == "context_pick"
    assert spec.target is None


def test_context_pick_input_default_multiple_is_unspecified():
    # `multiple` lives inside the `target` dict; we don't normalise it
    # backend-side in v1. Frontend defaults true and writes explicitly.
    spec = PromptInputDefinition.model_validate(
        {
            "name": "scenes",
            "type": "context_pick",
            "target": {"kinds": ["scene"]},
        }
    )
    assert spec.target == {"kinds": ["scene"]}


def test_context_pick_roundtrips_through_prompt_save(tmp_path, monkeypatch):
    # Hit the prompt save/read path so a context_pick input survives a
    # full file round-trip (front-matter YAML, _parse_prompt_inputs
    # tolerance). Uses the same harness as test_assistants.
    monkeypatch.setattr(
        "app.services.machine_settings.config_path",
        lambda: tmp_path / "machine_settings.yaml",
    )
    from app.models import SavePromptEntryRequest
    from app.services.project_service import ProjectService

    service = ProjectService.created_at(tmp_path / "project", "Demo")
    assert service.current_project().title == "Demo"
    created = service.create_prompt_entry(
        type("R", (), {"title": "Pick demo", "entry_type": "prompt:snippet"})()
    )
    request = SavePromptEntryRequest(
        title="Pick demo",
        body="Body",
        base_revision=created.revision,
        entry_type="prompt:snippet",
        metadata={},
        inputs=[
            PromptInputDefinition(
                name="reference_scenes",
                type="context_pick",
                label="Reference scenes",
                target={
                    "kinds": ["scene"],
                    "presets": ["full_outline"],
                    "multiple": True,
                },
            )
        ],
    )
    saved = service.save_prompt_entry(created.id, request)
    assert saved.inputs[0].type == "context_pick"
    assert saved.inputs[0].target == {
        "kinds": ["scene"],
        "presets": ["full_outline"],
        "multiple": True,
    }

    reread = service.read_prompt_entry(saved.id)
    assert reread.inputs[0].type == "context_pick"
    assert reread.inputs[0].target["presets"] == ["full_outline"]


def test_context_pick_input_iterates_as_entry_ref_list(tmp_path, monkeypatch):
    # ADR-0060 §2 Journey A: a context_pick value travels as a JSON string of
    # picked refs; the bind layer coerces it to a list[EntryRef] so the template
    # can loop it and `use()` each pick. `entry(inputs.x)` still yields the first
    # pick (it takes [0]). This is the traversal that could not be done in v1.
    monkeypatch.setattr(
        "app.services.machine_settings.config_path",
        lambda: tmp_path / "machine_settings.yaml",
    )
    from app.models import CreateLoreEntryRequest
    from app.services.ai.preview import PreviewRequest, build_preview
    from app.services.project_service import ProjectService

    service = ProjectService.created_at(tmp_path / "project", "Picks")
    alpha = service.create_lore_entry(
        CreateLoreEntryRequest(title="Alpha", entry_type="lore:note")
    )
    beta = service.create_lore_entry(
        CreateLoreEntryRequest(title="Beta", entry_type="lore:note")
    )
    picks = json.dumps(
        [
            {"id": alpha.id, "kind": "lore", "title": "Alpha"},
            {"id": beta.id, "kind": "lore", "title": "Beta"},
        ]
    )
    rendered, _ = build_preview(
        service,
        PreviewRequest(
            template_source=(
                '{% role "system" %}'
                "count={{ inputs.picks | length }} "
                "first={{ entry(inputs.picks).title }} "
                "{% for p in inputs.picks %}{{ use(p) }}{% endfor %}"
                "{% endrole %}"
            ),
            target_scene_id="",
            session_id=None,
            inputs={"picks": picks},
            text_before="",
            text_after="",
            commit=False,
        ),
    )
    text = "".join(m.text for m in rendered.messages)
    # inputs.picks is a real list (length 2), each item a usable EntryRef.
    assert "count=2" in text
    # entry(inputs.picks) → the FIRST pick.
    assert "first=Alpha" in text
    # {% for p in inputs.picks %}{{ use(p) }} selected BOTH picks, in order.
    assert rendered.used_node_ids == [alpha.id, beta.id]
    assert rendered.lore_invoked is True
