from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.base import (
    AIPolicy,
    MetadataValue,
    PromptInputType,
    SelectOption,
    _normalize_select_options,
)
from app.models_views import NodePickerConfig


class MetadataFieldDefinition(BaseModel):
    name: str
    type: Literal[
        "text",
        "long_text",
        "number",
        "boolean",
        "date",
        "select",
        "multi_select",
        "entity_ref",
        "entity_ref_list",
        "tags",
        "computed",
        "color",
    ]
    options: list[SelectOption] = Field(default_factory=list)
    picker_config: NodePickerConfig | None = None
    computed: dict[str, str] | None = None
    # Optional Tabler icon name (without the `ti-` prefix), e.g. "shield-half".
    # Empty/None falls back to the default glyph for the field's type
    # (see the metadata revision design). Display-only; the macro contract
    # is the field key, never the icon.
    icon: str | None = None
    # Optional L1 section label. Fields sharing a `group` render under one
    # labelled header in the rail + type editor. None = ungrouped.
    group: str | None = None
    # Set ONLY on synthetic fields generated from an L2 group application
    # (= the source group id). Never persisted; lets the UI render these as
    # group-derived (read-only, "from <group>") rather than own/inherited.
    group_origin: str | None = None
    # Optional initial value for newly-created entries (#38). When set,
    # `create_scene` / `create_lore_entry` / etc. pre-fill the entry's
    # metadata with this value. None = no default (the existing behaviour;
    # nothing is pre-filled). Type-matched per the field's `type`: boolean
    # fields persist `true` / `false`, number fields persist a number,
    # select fields persist the value (not the label), refs persist the
    # id (or list of ids for entity_ref_list). Computed fields never carry
    # a default — they're derived at read time.
    default: MetadataValue | None = None
    # Intrinsic (#116): the field's value lives on the node's TOP-LEVEL
    # front matter (`id` / `title` / `entry_type`), not in the `metadata`
    # dict. These are the identity triple every node carries; declaring them
    # as fields makes them visible to the field-inheritance hierarchy and
    # filterable/sortable in Views, without moving storage into metadata.
    # Consumers read the value from the node property keyed by the field id.
    intrinsic: bool = False
    # Display default: hide this field from the per-node rail and the Views
    # field picker unless a per-type override shows it. Used to keep `id`
    # out of sight by default (#116). Display-only — never affects storage
    # or filtering membership.
    hidden: bool = False
    # Authorship category (ADR-0029): who produces the value —
    # `intrinsic` (identity triple, lives on `node.<key>`),
    # `computed` (app-derived, read-only), else `stored` (`metadata.<key>`).
    # DERIVED, not authored: stamped by the schema resolver on read (None on
    # authored input); every surface consults it instead of re-deriving from
    # `intrinsic` / `type == "computed"` / key membership.
    category: Literal["stored", "intrinsic", "computed"] | None = None

    @field_validator("options", mode="before")
    @classmethod
    def _accept_bare_strings(cls, value: Any) -> Any:
        return _normalize_select_options(value)


class PromptInputDefinition(BaseModel):
    name: str = Field(min_length=1)
    type: PromptInputType = "text"
    label: str | None = None
    default: Any | None = None
    options: list[SelectOption] = Field(default_factory=list)
    required: bool = False

    @field_validator("options", mode="before")
    @classmethod
    def _accept_bare_strings(cls, value: Any) -> Any:
        return _normalize_select_options(value)
    # For entity_ref / entity_ref_list / context_pick inputs, `target`
    # carries a NodePickerConfig — the same shape MetadataFieldDefinition
    # uses for `picker_config`. Per decisions-inputs-fields-uniformity, all
    # three types share one picker-constraint vocabulary:
    #   {
    #     "kinds": ["scene", "lore", "snippet", "assistant"],
    #     "entry_types": {"lore": ["character", "location"]},  # optional, per kind
    #     "presets": ["full_outline", "full_text"],         # context_pick only
    #     "multiple": true,                                  # context_pick only
    #     "allow_target_marking": true,                      # context_pick only
    #   }
    # For entity_ref / entity_ref_list, cardinality is implied by the type
    # literal — any `multiple` field is ignored; presets and target marking
    # are not surfaced. See docs/context-picker.md.
    target: dict[str, Any] | None = None


class PromptContextStrategy(BaseModel):
    target: dict[str, Any] | None = None
    scan_surface: list[str] = Field(default_factory=list)
    output: dict[str, Any] | None = None


class PromptEntryTypeExtras(BaseModel):
    system_prompt: str | None = None
    model_class: str | None = None
    provider_policy: AIPolicy | None = None
    inputs: list[PromptInputDefinition] = Field(default_factory=list)
    context_strategy: PromptContextStrategy | None = None


class GroupMember(BaseModel):
    """One member field of a reusable group definition (L2 groups).

    `key` is the suffix combined with a GroupApplication.key_prefix to form
    the generated field's stable key (e.g. prefix "external_" + key "goal"
    → "external_goal"). The rest defines the generated field."""

    key: str
    name: str
    type: Literal[
        "text",
        "long_text",
        "number",
        "boolean",
        "date",
        "select",
        "multi_select",
        "entity_ref",
        "entity_ref_list",
        "tags",
        "color",
    ] = "text"
    icon: str | None = None
    options: list[SelectOption] = Field(default_factory=list)
    picker_config: NodePickerConfig | None = None
    # Same semantics as MetadataFieldDefinition.default (#38) — propagates
    # to each generated field at schema-resolution time, so every
    # application of the group seeds new entries with the same default.
    default: MetadataValue | None = None

    @field_validator("options", mode="before")
    @classmethod
    def _accept_bare_strings(cls, value: Any) -> Any:
        return _normalize_select_options(value)


class MetadataGroupDefinition(BaseModel):
    """A reusable group of fields, e.g. GMO = Goal / Motivation / Obstacle.

    Applied to entry types via GroupApplication. Fields resolve dynamically
    from the definition × application, so editing the definition propagates
    to every application (the "live" L2 model)."""

    name: str
    icon: str | None = None
    members: list[GroupMember] = Field(default_factory=list)


class GroupApplication(BaseModel):
    """An entry type's use of a reusable group, with a display label and a
    key prefix — e.g. GMO applied as External (external_) and Internal
    (internal_): two applications of one group, not six hand-made fields."""

    group_id: str
    label: str = ""
    key_prefix: str = ""


class FieldOverride(BaseModel):
    """Per-entry_type overlay on a field's presentation (#116). Lets a type
    relabel or hide a field it carries — own or inherited — without touching
    the shared field definition. `label` renames (e.g. `title` → "Name" on
    lore, "Title" on scene); `hidden` toggles the field out of the per-node
    rail and the Views picker. Both optional: an absent aspect falls back to
    the field def. Stored per layer on the type; merged down the parent chain
    (child wins) by the schema resolver, same as `display_order`."""

    label: str | None = None
    hidden: bool | None = None


class EntryTypeDefinition(BaseModel):
    name: str
    kind: str
    parent: str | None = None
    abstract: bool = False
    fields: list[str] = Field(default_factory=list)
    own_fields: list[str] = Field(default_factory=list)
    display_template: str = "{title}"
    has_body: bool = True
    body_editor: Literal["wysiwyg", "code"] = "wysiwyg"
    body_language: Literal["markdown", "jinja2", "plain"] = "markdown"
    # The body shape this entry type opens with in NodeEditor. None →
    # fall back to (none if !has_body, code if body_editor=="code",
    # else prose). Explicit values let new shapes (chat) declare
    # themselves without retrofitting has_body/body_editor semantics.
    # "view" routes to the Svelte Flow view designer (0.5.0 step 3, #80).
    # See decisions-node-editor-modularization + decisions-node-editor-body-spec.
    body_shape: Literal["prose", "code", "chat", "none", "view"] | None = None
    # Starter content for new entries of this type. Used by
    # create_prompt_entry as the initial body so authoring a
    # `roleplay` (or any future type with conventions worth showing off)
    # opens with a working template the author can adapt instead of a
    # blank page.
    default_body: str = ""
    # Per-entry inputs to seed onto new prompt entries of this type.
    # Mirrors `default_body`'s role for the inputs declaration — without
    # this, `roleplay`'s starter template would reference an
    # `input.character` that doesn't exist on a freshly-created prompt.
    default_inputs: list[PromptInputDefinition] = Field(default_factory=list)
    # Type-level color (machine palette swatch id). Resolves to a hex via
    # the machine palette. Child types inherit unless they set their own.
    # Entries of this type fall back to this color when they don't carry
    # an instance-level override. None = no color set; resolver walks
    # the parent chain, then the kind-default table, then yields null.
    color: str | None = None
    # The pre-inheritance color value (mirrors `own_fields` for the fields
    # list). The editor uses this to distinguish "color set on this type"
    # from "color inherited from parent" — letting authors clear their own
    # override without disturbing the parent's value. Computed by the
    # schema inheritance resolver; not authored directly.
    own_color: str | None = None
    # Soft-deprecation flag. Set on entry_types that are kept readable for
    # legacy projects but should not be offered when creating new entries.
    # Schemas keep their definition (so existing files still validate); UI
    # filters by this flag to hide the type from "Add entry" menus.
    deprecated: bool = False
    prompt: PromptEntryTypeExtras | None = None
    # Reusable group applications (L2). Each expands into generated prefixed
    # fields in the effective schema. Authored on the type; persisted as-is.
    group_applications: list[GroupApplication] = Field(default_factory=list)
    # Per-field presentation overrides (#116), keyed by field id. Relabel /
    # hide a field for this type without editing the shared field def. The
    # resolver merges parent overrides then this type's, so children inherit
    # and can refine. Consumers resolve a field's effective label / hidden
    # via this map (falling back to the field def).
    field_overrides: dict[str, FieldOverride] = Field(default_factory=dict)
    # The pre-merge overrides authored ON THIS TYPE (mirrors `own_fields` /
    # `own_color`). `field_overrides` above is the parent-merged result; this
    # is only what this layer set. ADR-0029 §I: the override editor reads /
    # writes THIS so editing one aspect (label) doesn't freeze the inherited
    # other aspect (hidden) into the child layer. Computed by the resolver;
    # not authored directly.
    own_field_overrides: dict[str, FieldOverride] = Field(default_factory=dict)


class MetadataSchema(BaseModel):
    version: int = 1
    entry_types: dict[str, EntryTypeDefinition] = Field(default_factory=dict)
    fields: dict[str, MetadataFieldDefinition] = Field(default_factory=dict)
    # Reusable group definitions (L2), keyed by group id. Generated fields
    # from group_applications are injected into `fields` at resolution time.
    groups: dict[str, MetadataGroupDefinition] = Field(default_factory=dict)


class MetadataSchemaLayer(BaseModel):
    id: str
    label: str
    folder_path: str
    schema_path: str
    exists: bool = False


class MetadataSchemaLayers(BaseModel):
    layers: list[MetadataSchemaLayer] = Field(default_factory=list)


class MetadataDefinitionSource(BaseModel):
    layer_id: str
    layer_label: str
    schema_path: str | None = None
    built_in: bool = False


class MetadataSchemaOverview(BaseModel):
    effective_schema: MetadataSchema
    layers: list[MetadataSchemaLayer] = Field(default_factory=list)
    entry_type_sources: dict[str, MetadataDefinitionSource] = Field(default_factory=dict)
    field_sources: dict[str, MetadataDefinitionSource] = Field(default_factory=dict)


class UpsertMetadataFieldRequest(BaseModel):
    layer_id: str = Field(min_length=1)
    field_id: str = Field(min_length=1)
    field: MetadataFieldDefinition
    entry_type: str = "scene:scene"
    allow_existing: bool = True
    # Explicit old-value → new-value rename map for select/multi_select
    # options, computed client-side keyed by each option's original value.
    # Reorder-safe (positional pairing would mis-rename on reorder). Values
    # no longer present in the field's options are cleared from entries.
    option_migration: dict[str, str] | None = None


class UpsertMetadataEntryTypeRequest(BaseModel):
    layer_id: str = Field(min_length=1)
    entry_type_id: str = Field(min_length=1)
    entry_type: EntryTypeDefinition
    allow_existing: bool = True


class DeleteMetadataEntryTypeRequest(BaseModel):
    entry_type_id: str = Field(min_length=1)


class MoveMetadataFieldRequest(BaseModel):
    field_id: str = Field(min_length=1)
    target_layer_id: str = Field(min_length=1)
    entry_type: str = "scene:scene"


class RenameMetadataFieldRequest(BaseModel):
    old_field_id: str = Field(min_length=1)
    new_field_id: str = Field(min_length=1)
    entry_type: str = "scene:scene"


class DeleteMetadataFieldRequest(BaseModel):
    field_id: str = Field(min_length=1)
    entry_type: str = "scene:scene"


class UpsertMetadataGroupRequest(BaseModel):
    layer_id: str = Field(min_length=1)
    group_id: str = Field(min_length=1)
    group: MetadataGroupDefinition
    allow_existing: bool = True


class DeleteMetadataGroupRequest(BaseModel):
    group_id: str = Field(min_length=1)


class SetGroupApplicationsRequest(BaseModel):
    layer_id: str = Field(min_length=1)
    entry_type_id: str = Field(min_length=1)
    applications: list[GroupApplication] = Field(default_factory=list)


class SetFieldOrderRequest(BaseModel):
    layer_id: str = Field(min_length=1)
    entry_type_id: str = Field(min_length=1)
    # Desired order of the type's own field ids (must be a permutation of the
    # fields currently defined on the type at this layer).
    field_order: list[str] = Field(default_factory=list)


class SetFieldOverrideRequest(BaseModel):
    """Set / clear a per-type field presentation override (#116). `field_key`
    must be a member of the type's resolved fields. `label` / `hidden` are
    each tri-state: a value sets it, `null` clears that aspect. When both
    resolve to empty the override entry is dropped from the layer."""

    layer_id: str = Field(min_length=1)
    entry_type_id: str = Field(min_length=1)
    field_key: str = Field(min_length=1)
    label: str | None = None
    hidden: bool | None = None
