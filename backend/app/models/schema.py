from __future__ import annotations

from typing import Any, Final, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.base import (
    MetadataValue,
    PromptInputType,
    SelectOption,
    _normalize_select_options,
)
from app.models_views import NodePickerConfig

# The single catalog of scalar types a list item may be (#698) — the Literal
# is the source, the frozenset its runtime mirror (via get_args, so the two
# cannot drift). The schema-integrity member check is the POSITIVE form of
# this same catalog: a group member type outside it cannot be an item shape.
ListItemScalarType = Literal["text", "long_text", "number", "boolean", "select", "color"]
LIST_ITEM_SCALAR_TYPES: Final[frozenset[str]] = frozenset(get_args(ListItemScalarType))


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
        "list",
    ]
    options: list[SelectOption] = Field(default_factory=list)
    picker_config: NodePickerConfig | None = None
    computed: dict[str, str] | None = None
    # `list` fields (#698 / ADR-0048 §6): an ordered list whose item shape is
    # EITHER a named group (`item_group` = a MetadataGroupDefinition id — the
    # group consumed nested, the second consumption mode beside application
    # flattening) OR a single scalar (`item_type` — sugar, normalized to a
    # one-member shape before validation/UI; values stored as a flat YAML
    # scalar sequence, the way multi_select stores). Exactly one of the two
    # must be set when type == "list"; both must be absent otherwise. A
    # select-typed item_type reads its choices from this field's `options`.
    # v1 keeps entity_ref / entity_ref_list / tags OUT of item shapes — the
    # read-side healers only walk top-level values, and a half-healed nested
    # ref would be a silent mis-link (enforced at schema-integrity time for
    # item_group; by the Literal below for item_type).
    item_group: str | None = None
    item_type: ListItemScalarType | None = None
    # DERIVED, not authored (the `category` pattern): the resolved item shape
    # for list fields — the named group's members, or the item_type sugar
    # normalized to a one-member shape (key "value", options seeded from this
    # field's `options`). Stamped by the schema resolver on read; None on
    # authored input; never persisted. Validation and the UI read ONLY this,
    # so both consume one internal model regardless of how the shape was
    # declared.
    item_members: list[GroupMember] | None = None
    # DERIVED like `item_members`: True when the stamped shape is the
    # item_type sugar (items store flat scalars), False when it is a group
    # (items store member-keyed maps). This — never `item_type is not None` —
    # is the shape discriminator every consumer must read: on a cross-layer
    # both-keys conflict the resolver's tie-break decides, and a consumer
    # keying on the raw declaration would take the losing side.
    item_scalar: bool | None = None
    # Optional Tabler icon name (without the `ti-` prefix), e.g. "shield-half".
    # Empty/None falls back to the default glyph for the field's type
    # (see the metadata revision design). Display-only; the macro contract
    # is the field key, never the icon.
    icon: str | None = None
    # Optional author-facing help text: what the field is FOR (#1004). Shown as
    # a tooltip on the field in the rail, and — the load-bearing half — fed to
    # the brainstorm / extraction model so it proposes on-target values instead
    # of guessing a field's meaning from its label. None = no description.
    description: str | None = None
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
    # Whether the AI may author this field's value on a brainstorm commit
    # (ADR-0059 §E). Default True — the flag is an opt-out for author-owned
    # fields (e.g. the built-in `context_policy`, a cost/visibility knob a
    # commit should never set), not a re-permissioning of the schema. Set per
    # layer by redefining the field, the same reach `description` has. For every
    # field that reaches the model through the `"fields"` object (all stored
    # fields + `title`) this feeds the single `is_proposable_field` predicate;
    # `body` travels as a top-level key, so it enforces the flag at its own two
    # sites instead (§E).
    ai_proposable: bool = True
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

    # The exactly-one-of item_group / item_type rule is deliberately NOT a
    # model validator: layers merge field definitions by key union, so an
    # ancestor's item_group plus a child's item_type can legitimately meet in
    # one merged def — a raising validator would turn that authoring conflict
    # into an unreadable schema (500 on every read). Like the computed-
    # settings rule, it is a soft, reportable schema-integrity error
    # (`_validate_metadata_schema_definition`), and the resolver breaks the
    # tie deterministically (item_group wins) so reads stay serviceable.


class PromptInputDefinition(BaseModel):
    name: str = Field(min_length=1)
    type: PromptInputType = "text"
    label: str | None = None
    default: Any | None = None
    options: list[SelectOption] = Field(default_factory=list)
    required: bool = False
    # A launch-set input the strip should not author: its value is chosen by how
    # the chat was opened (e.g. the entry_type an AI new-entry brainstorm drafts,
    # ADR-0046 §6.4), not typed by the user. Still declared, so it is forwarded
    # into the template's `input.*` namespace; only its strip widget is skipped.
    hidden: bool = False

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


class PromptCommit(BaseModel):
    """The optional commit capability of an `extract_to_node` prompt (ADR-0054 §2 /
    ADR-0065).

    Present ⇒ the conversation gains a Commit button that extracts its result to
    the target node as a reviewable patch. `review` is how that result is reviewed
    (`visual_diff` = per-run adopt against the current entry; `replace` = a plain
    current→proposed swap). `target` (ADR-0063 S1) is the entry_type FQN the
    commit *creates* — declaring it makes the chat a create brainstorm for that
    type regardless of how it was launched; unset ⇒ today's behaviour (revise
    the seeded `entry`, or create the launch's `entry_type`). Frontend-only
    dispatch fields (ADR-0065): the backend parses and passes this whole block
    through unread and unvalidated, so `review`/`target` are kept lenient
    (`str`, not a `Literal`) — a hand-edited layer stays readable either way.

    `fields` — the old static allow-list of what the commit extracts — retired
    with ADR-0067 S2: a prompt now narrows what it extracts by authoring its
    own `field_contract` loop (registered fields, read back at commit), not a
    schema-declared list."""

    review: str = "visual_diff"
    target: str | None = None


class PromptOnAccept(BaseModel):
    """The accept-time mark-stamp of an inline prompt (#954, Lever 2).

    Present ⇒ accepting the streamed suggestion wraps it in the named TipTap
    `mark`, keyed to the lore id pulled from the context_pick input named by
    `from_input`. This is what makes `roleplay` a *declared* capability rather
    than a hardcoded `entry_type == prompt:roleplay` branch: the mark it stamps
    (`character`) and the input it reads (`character`) are named here, on the
    type, exactly as `commit` names its capability. Meaningful only under the
    `inline` handler — a frontend-only dispatch field (ADR-0065): the backend
    parses and passes it through unread, so nothing here rejects it under a
    different handler; the frontend simply never reads it there. Kept lenient
    (`str`) like the rest."""

    mark: str = ""
    from_input: str = ""


class PromptOutput(BaseModel):
    """Which OutputHandler runs a prompt's result (ADR-0065), plus its optional
    commit (`extract_to_node`) or accept-time mark-stamp (`inline`).

    `handler` is the registry key — `inline` (stream a suggestion into the prose
    editor) or `extract_to_node` (a brainstorm chat whose commit becomes a reviewable
    node patch) — or unset for no handler: a `general` prompt whose response stays in
    the conversation, and `snippet`. It replaces the old `output.kind` disposition —
    `kind` named WHERE the output landed and source/review/activation all derived from
    it; the handler now owns that behaviour and the key just names which one.
    `destination` is the inline sub-choice — `cursor` (continue at the caret, the old
    `append_to_body`) or `selection` (replace the selection, the old
    `replace_selection`); meaningful only under `inline`. Frontend-owned dispatch
    (ADR-0065): the backend parses this whole block and `model_dump`s it straight
    through — it does not validate `handler`/`destination` at rest. The frontend
    handler registry (`OutputHandlerKey` / editor-core) owns the closed
    vocabulary and fails closed on an unknown value — a prompt with an
    unrecognized `handler` resolves to no surface, so it simply isn't invocable,
    not a save-time rejection. Kept `str` here (not a `Literal`) so a hand-edited
    or forward-authored layer never 500s on read. `commit` is meaningful only
    under `extract_to_node`, and `on_accept` only under `inline`; nothing on the
    backend enforces that pairing — the frontend's authoring UI
    (PromptOutputEditor) is what keeps them from co-existing.
    `headless` (ADR-0062 Am.2) is orthogonal to `handler` — "no chat loop", not "no
    interaction": a headless run still gathers required inputs and still presents
    its result for review, it just skips the back-and-forth conversation. Modelled
    three-valued (`bool | None`, not `bool = False`) so front matter stays tidy —
    `_prompt_front_matter_extra` serialises via `model_dump(exclude_none=True)`, so
    `None` is dropped and only `headless: true` ever lands on disk. No runtime
    consumer yet — an honest forward-declaration (D3 authors it; the
    `{extract_to_node, headless}` run path arrives later)."""

    handler: str = ""
    destination: str = ""
    commit: PromptCommit | None = None
    on_accept: PromptOnAccept | None = None
    headless: bool | None = None


class PromptContextStrategy(BaseModel):
    output: PromptOutput | None = None


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
    # Built-in machinery groups (e.g. the plot-board beat/link shapes) set this
    # so the authoring UI hides them from the reusable-group pickers — they are
    # consumed by feature code by id, never meant for a user to apply or edit.
    # User-defined groups leave it False.
    system: bool = False


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
    # Class-level, inherited down the parent chain (like has_body/body_shape).
    # The surface a node of this type opens in: "editor" = a NodeEditor with a
    # metadata rail (the only surface that can host a Conversations list / be
    # an offer_on target); "tree_container", "board", "dialog" are non-editor
    # surfaces. Default "editor" — most entry_types open in a NodeEditor.
    opens_in: Literal["editor", "tree_container", "board", "dialog"] = "editor"
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
    # Type-level Tabler icon name (without the `ti-` prefix), the mnemonic twin
    # of `color` and the same treatment fields/groups already carry (#316).
    # Child types inherit unless they set their own; entries fall back to it.
    # None = no icon set; the resolver walks the parent chain, then yields null.
    icon: str | None = None
    # The pre-inheritance icon value (mirrors `own_color`). The editor uses this
    # to distinguish "icon set on this type" from "icon inherited from parent".
    # Computed by the schema inheritance resolver; not authored directly.
    own_icon: str | None = None
    # Soft-deprecation flag. Set on entry_types that are kept readable for
    # legacy projects but should not be offered when creating new entries.
    # Schemas keep their definition (so existing files still validate); UI
    # filters by this flag to hide the type from "Add entry" menus.
    deprecated: bool = False
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
    # Frozen: a resolved schema is immutable value data, and the
    # resolved-definitions cache (#394) hands the *same* instance to every
    # consumer of `read_metadata_schema`. Reassigning a top-level field would
    # corrupt that shared instance for all of them; `frozen` makes it an error.
    # (Nested dict mutation is not blocked by pydantic here — the read-only
    # contract for that is stated on `read_metadata_schema`.)
    model_config = ConfigDict(frozen=True)

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
    entry_type: str = "manuscript:scene"
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
    entry_type: str = "manuscript:scene"


class RenameMetadataFieldRequest(BaseModel):
    old_field_id: str = Field(min_length=1)
    new_field_id: str = Field(min_length=1)
    entry_type: str = "manuscript:scene"


class DeleteMetadataFieldRequest(BaseModel):
    field_id: str = Field(min_length=1)
    entry_type: str = "manuscript:scene"


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
