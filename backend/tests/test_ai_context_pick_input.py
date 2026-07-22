"""The new `context_pick` prompt input type. v1 backend slice:
PromptInputDefinition accepts the new type literal and round-trips its
`target` payload (kinds/entry_types/presets/multiple) through Pydantic
validation and prompt-entry save/read.

Per docs/context-picker.md. Render-time wrapping of picked items into
EntryRef lists is a follow-up — v1 leaves raw dicts in the template
so the picker can land end-to-end without coupling to helper changes.
"""

from __future__ import annotations

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
