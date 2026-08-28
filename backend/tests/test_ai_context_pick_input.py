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


def test_use_of_whole_pick_list_selects_every_pick(tmp_path, monkeypatch):
    # #1466: `use()` on a multi-select context_pick is the natural spelling —
    # `use(inputs.picks)` must select EVERY pick, matching the explicit loop
    # form above, not silently keep only the first (the old `_coerce_entry_ref`
    # `[0]` collapse, which `entry()` still relies on and this must not disturb).
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
                '{% role "system" %}{% do use(inputs.picks) %}{% endrole %}'
            ),
            target_scene_id="",
            session_id=None,
            inputs={"picks": picks},
            text_before="",
            text_after="",
            commit=False,
        ),
    )
    # The whole list — both picks recorded, in order — same as the explicit loop.
    assert rendered.used_node_ids == [alpha.id, beta.id]
    assert rendered.lore_invoked is True


def test_json_array_of_scalars_is_not_coerced(tmp_path, monkeypatch):
    # ADR-0060 §2: the bind-layer coercion keys on the picker SHAPE (a JSON list
    # of dicts), not merely a `[...]`-looking string. A plain text input whose
    # value is a JSON array of scalars must reach the template as the string —
    # not silently become an (empty) list[EntryRef], which would break
    # `{{ inputs.x }}`.
    monkeypatch.setattr(
        "app.services.machine_settings.config_path",
        lambda: tmp_path / "machine_settings.yaml",
    )
    from app.services.ai.preview import PreviewRequest, build_preview
    from app.services.project_service import ProjectService

    service = ProjectService.created_at(tmp_path / "project", "Picks")
    rendered, _ = build_preview(
        service,
        PreviewRequest(
            template_source=(
                '{% role "system" %}'
                "len={{ inputs.notes | length }} val={{ inputs.notes }}"
                "{% endrole %}"
            ),
            target_scene_id="",
            session_id=None,
            inputs={"notes": '["a", "b"]'},
            text_before="",
            text_after="",
            commit=False,
        ),
    )
    text = "".join(m.text for m in rendered.messages)
    # Left as the raw string: `| length` is the 10-char string length and the
    # literal renders — NOT coerced to a 0-length EntryRef list.
    assert "len=10" in text
    assert 'val=["a", "b"]' in text


def _sample_structure():
    from app.models import StructureDocument, StructureNode

    # root → Act A → [scene s_a1, scene s_a2]; standalone scene s_b.
    return StructureDocument(
        root=StructureNode(
            id="root",
            type="root",
            title="Manuscript",
            children=[
                StructureNode(
                    id="A",
                    type="manuscript:act",
                    title="Act One",
                    children=[
                        StructureNode(id="A1", type="manuscript:scene", title="Open", scene_id="s_a1"),
                        StructureNode(id="A2", type="manuscript:scene", title="Mid", scene_id="s_a2"),
                    ],
                ),
                StructureNode(id="B", type="manuscript:scene", title="Standalone", scene_id="s_b"),
            ],
        )
    )


class _StructureStub:
    """A minimal project_service exposing only read_structure, tracking calls."""

    def __init__(self, document):
        self._document = document
        self.reads = 0

    def read_structure(self):
        self.reads += 1
        return self._document


def test_expand_container_picks_expands_containers_to_ordered_scenes():
    # ADR-0074 slice 4a: a picked manuscript CONTAINER (act/chapter/root)
    # materializes to its ordered descendant scenes; the ref carries the
    # structure-node id, which find_node resolves to a container (no scene_id).
    from app.services.ai.preview import _expand_container_picks

    stub = _StructureStub(_sample_structure())
    # An act → its two scenes, in reading order.
    assert _expand_container_picks(stub, [{"id": "A", "kind": "manuscript"}]) == [
        {"id": "s_a1", "kind": "manuscript"},
        {"id": "s_a2", "kind": "manuscript"},
    ]
    # The root → every scene in reading order.
    assert _expand_container_picks(stub, [{"id": "root", "kind": "manuscript"}]) == [
        {"id": "s_a1", "kind": "manuscript"},
        {"id": "s_a2", "kind": "manuscript"},
        {"id": "s_b", "kind": "manuscript"},
    ]


def test_expand_container_picks_passes_scenes_and_others_through():
    # A leaf scene (its ref id is the scene_id — find_node misses, so it isn't a
    # container), a non-manuscript pick, and an unresolved manuscript id all pass
    # untouched. The unknown id has no entry_type, so it opens the structure but
    # resolves to nothing and passes through.
    from app.services.ai.preview import _expand_container_picks

    stub = _StructureStub(_sample_structure())
    items = [
        {"id": "s_a1", "kind": "manuscript", "entry_type": "manuscript:scene", "title": "Open"},
        {"id": "l1", "kind": "lore", "title": "A note"},  # non-manuscript
        {"id": "ghost", "kind": "manuscript"},  # deleted / unknown
    ]
    assert _expand_container_picks(stub, items) == items


def test_container_pick_materializes_to_its_scenes_end_to_end(tmp_path, monkeypatch):
    # ADR-0074 slice 4a+4b together: a picked manuscript CONTAINER (here an act,
    # the shape the tri-state tree emits) reaches the template as its ordered
    # descendant scenes — proving the frontend's container ref round-trips
    # through the real build_preview path against a real manuscript, which the
    # isolated 4a unit test (a stub structure) could not.
    monkeypatch.setattr(
        "app.services.machine_settings.config_path",
        lambda: tmp_path / "machine_settings.yaml",
    )
    from app.models import CreateStructureNodeRequest
    from app.services.ai.preview import PreviewRequest, build_preview
    from app.services.project_service import ProjectService

    service = ProjectService.created_at(tmp_path / "project", "Picks")
    structure = service.create_structure_node(
        CreateStructureNodeRequest(title="Act One", entry_type="manuscript:act")
    )
    act = next(c for c in structure.root.children if c.type == "manuscript:act")
    for title in ("The Departure", "The Arrival"):
        service.create_structure_node(
            CreateStructureNodeRequest(title=title, entry_type="manuscript:scene", parent_id=act.id)
        )
    doc = service.read_structure()
    act_node = next(c for c in doc.root.children if c.id == act.id)
    scene_ids = [c.scene_id for c in act_node.children]
    assert len(scene_ids) == 2

    # The container ref the tree stores: the act's structure-node id + type.
    picks = json.dumps([{"id": act.id, "kind": "manuscript", "entry_type": "manuscript:act", "title": "Act One"}])
    rendered, _ = build_preview(
        service,
        PreviewRequest(
            template_source=(
                '{% role "system" %}'
                "count={{ inputs.picks | length }} "
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
    # The single act pick expanded to both scenes, in reading order.
    assert "count=2" in text
    assert rendered.used_node_ids == scene_ids


def test_tag_selector_pick_materializes_to_tagged_lore_end_to_end(tmp_path, monkeypatch):
    # ADR-0074 slice 5: a picked TAG (a selector pick, the shape the picker emits
    # — `{kind, expr: intersect[tagged, union[type...]]}`) reaches the template as
    # its member lore entries, resolved on the backend from the stored expr — NOT
    # a frontend id handoff (#447). This is the bug from the field report: the tag
    # resolved to 9 docs in the picker but 0 reached the prompt.
    monkeypatch.setattr(
        "app.services.machine_settings.config_path",
        lambda: tmp_path / "machine_settings.yaml",
    )
    from app.models import CreateLoreEntryRequest, SaveLoreEntryRequest
    from app.services.ai.preview import PreviewRequest, build_preview
    from app.services.project_service import ProjectService

    service = ProjectService.created_at(tmp_path / "project", "Picks")

    def make(title, entry_type, tags):
        entry = service.create_lore_entry(CreateLoreEntryRequest(title=title, entry_type=entry_type))
        return service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title=title,
                body=f"Body of {title}.",
                base_revision=entry.revision,
                entry_type=entry_type,
                metadata={"tags": tags},
            ),
        )

    # Two match the tag AND a type in the union; one has the wrong tag; one is
    # tagged but a type outside the union. Roster order = title-sorted.
    hit_note = make("Aetheria", "lore:note", ["World-building"])
    hit_loc = make("Boundary", "lore:location", ["World-building"])
    make("Cassini", "lore:note", ["Real-world"])  # wrong tag
    make("Delta", "lore:character", ["World-building"])  # tagged, type not in union

    picks = json.dumps(
        [
            {
                "id": "tag:lore:World-building",
                "kind": "tag",
                "title": "World-building",
                "selector": {
                    "kind": "lore",
                    "expr": {
                        "intersect": [
                            {"tagged": "World-building"},
                            {"union": [{"type": "lore:note"}, {"type": "lore:location"}]},
                        ]
                    },
                },
            }
        ]
    )
    rendered, _ = build_preview(
        service,
        PreviewRequest(
            template_source=(
                '{% role "system" %}'
                "count={{ inputs.picks | length }} "
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
    # The single tag pick expanded to exactly the two matching lore entries, in
    # roster order — not 0 (the bug), not the wrong-tag/wrong-type entries.
    assert "count=2" in text
    assert rendered.used_node_ids == [hit_note.id, hit_loc.id]
    assert rendered.lore_invoked is True


def test_tag_pick_lore_reaches_the_send_lore_tiers_end_to_end(tmp_path, monkeypatch):
    # The FAITHFUL reproduction (field report): the real chat renders lore via
    # `{% do use(inputs.lore) %}{{ use_lore() }}` — use_lore() emits nothing; the
    # lore the model actually receives is the send-path tier block computed from
    # `used_node_ids` (_preview_lore_tiers -> _relevant_lore_ids -> _format_lore_block).
    # A tag pick must land its tagged docs in THAT block, not merely in
    # used_node_ids. Asserting used_node_ids alone (the earlier tests) missed this.
    monkeypatch.setattr(
        "app.services.machine_settings.config_path",
        lambda: tmp_path / "machine_settings.yaml",
    )
    from app.models import CreateLoreEntryRequest, SaveLoreEntryRequest
    from app.services.ai.preview import PreviewRequest, build_preview
    from app.services.project_service import ProjectService

    service = ProjectService.created_at(tmp_path / "project", "Picks")

    def make(title, entry_type, tags):
        entry = service.create_lore_entry(CreateLoreEntryRequest(title=title, entry_type=entry_type))
        return service.save_lore_entry(
            entry.id,
            SaveLoreEntryRequest(
                title=title,
                body=f"BODY_OF_{title}",
                base_revision=entry.revision,
                entry_type=entry_type,
                metadata={"tags": tags},
            ),
        )

    hit = make("Aetheria", "lore:note", ["World-building"])
    make("Cassini", "lore:note", ["Real-world"])  # wrong tag — must NOT appear

    picks = json.dumps(
        [
            {
                "id": "tag:lore:World-building",
                "kind": "tag",
                "title": "World-building",
                "selector": {
                    "kind": "lore",
                    "expr": {
                        "intersect": [
                            {"tagged": "World-building"},
                            {"union": [{"type": "lore:note"}]},
                        ]
                    },
                },
            }
        ]
    )
    rendered, _ = build_preview(
        service,
        PreviewRequest(
            template_source='{% role "system" %}{% do use(inputs.lore) %}{{ use_lore() }}{% endrole %}',
            target_scene_id="",
            session_id=None,
            inputs={"lore": picks},
            text_before="",
            text_after="",
            commit=False,
        ),
    )
    assert rendered.lore_invoked is True
    assert rendered.used_node_ids == [hit.id]
    # The real payload: the lore block the model receives must carry the tagged doc.
    lore_block = (rendered.send_lore_stable or "") + (rendered.send_lore_volatile or "")
    assert "Aetheria" in lore_block, f"tagged doc missing from send lore: {lore_block!r}"
    assert "Cassini" not in lore_block


def test_expand_container_picks_skips_structure_read_for_scene_only_picks():
    # The perf gate (the preview re-renders on a debounce): a prompt that picks
    # only scenes (each tagged manuscript:scene) never loads the structure.
    from app.services.ai.preview import _expand_container_picks

    stub = _StructureStub(_sample_structure())
    scenes_and_lore = [
        {"id": "s_a1", "kind": "manuscript", "entry_type": "manuscript:scene"},
        {"id": "s_b", "kind": "manuscript", "entry_type": "manuscript:scene"},
        {"id": "l1", "kind": "lore"},
    ]
    assert _expand_container_picks(stub, scenes_and_lore) == scenes_and_lore
    assert stub.reads == 0
