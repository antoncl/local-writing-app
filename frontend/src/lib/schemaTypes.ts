// Metadata-schema (entry-type / group / layer) wire types. Extracted from
// types.ts to keep that barrel under the file-size cap; re-exported from
// `@/lib/types` so it stays the single import surface.

import type { MetadataFieldDefinition, MetadataFieldType, MetadataValue, SelectOption } from "./metadataTypes";
import type { NodePickerConfig } from "./pickerTypes";
import type { PromptInputDefinition } from "./promptTypes";

export type EntryBodyEditor = "wysiwyg" | "code";
export type EntryBodyLanguage = "markdown" | "jinja2" | "plain";
export type BodyShape = "prose" | "code" | "chat" | "none" | "view";

export type EntryTypeDefinition = {
  name: string;
  kind: string;
  parent?: string | null;
  abstract?: boolean;
  // Superseded types kept readable for legacy projects but filtered out of the
  // create menus (no longer offered for new-entry creation).
  deprecated?: boolean;
  fields: string[];
  own_fields?: string[];
  display_template?: string;
  has_body?: boolean;
  body_editor?: EntryBodyEditor;
  body_language?: EntryBodyLanguage;
  // None → fall back to (none if !has_body, code if body_editor=="code",
  // else prose). See decisions-node-editor-body-spec.
  body_shape?: BodyShape | null;
  // Class-level, inherited down the parent chain (like has_body/body_shape).
  // The surface a node of this type opens in: "editor" = a NodeEditor with a
  // metadata rail (the only surface that can host a Conversations list / be
  // an offer_on target); "tree_container"/"board"/"dialog" are non-editor
  // surfaces. Default "editor".
  opens_in?: "editor" | "tree_container" | "board" | "dialog";
  // Type-level palette swatch id. Inherits from parent unless set.
  // Resolves to a hex via the machine palette. See colors.ts.
  color?: string | null;
  // Pre-inheritance color — mirrors `own_fields`. Editor uses this to
  // distinguish "set on this type" from "inherited from parent".
  own_color?: string | null;
  // Type-level Tabler icon name (without the `ti-` prefix), the mnemonic twin
  // of `color` (#316). Inherits from parent unless set.
  icon?: string | null;
  // Pre-inheritance icon — mirrors `own_color`. Distinguishes "set on this
  // type" from "inherited from parent".
  own_icon?: string | null;
  default_body?: string;
  default_inputs?: PromptInputDefinition[];
  // Reusable group applications (L2). Each expands into generated prefixed
  // fields in the effective schema.
  group_applications?: GroupApplication[];
  // Per-field presentation overrides (#116), keyed by field id. Relabel / hide
  // a field for this type without touching the shared field def. Resolved down
  // the parent chain by the backend. Read effective label/hidden via the
  // schemaFields helpers, never off the map directly.
  field_overrides?: Record<string, FieldOverride>;
  // The type's OWN (pre-merge) overrides — mirrors `own_fields` / `own_color`
  // (ADR-0029 §I). `field_overrides` above is parent-merged; this is only what
  // this type authored. The override editor reads/writes THIS so editing one
  // aspect (label) doesn't freeze the inherited other aspect (hidden) into the
  // layer. Read-back only; writes still go through the field-override endpoint.
  own_field_overrides?: Record<string, FieldOverride>;
};

// Per-type presentation overlay on a field (#116). `label` renames it for the
// type; `hidden` toggles it out of the rail / picker. Absent aspect → fall
// back to the field def. `hidden: false` is meaningful — it un-hides a field
// the def hides by default (e.g. `id`).
export type FieldOverride = {
  label?: string | null;
  hidden?: boolean | null;
};

// One member of a reusable group definition (L2 groups). `key` is the
// suffix combined with a GroupApplication.key_prefix to form a generated
// field's stable key.
export type GroupMember = {
  key: string;
  name: string;
  type: MetadataFieldType;
  icon?: string | null;
  options?: SelectOption[];
  picker_config?: NodePickerConfig | null;
  // Default value propagated onto each generated field at schema-resolution
  // time, so every application of the group seeds new entries with the
  // same default (#38).
  default?: MetadataValue | null;
};

// A reusable group of fields (e.g. GMO = Goal/Motivation/Obstacle), applied
// to entry types via GroupApplication. Fields resolve dynamically, so
// editing the definition propagates to every application.
export type MetadataGroupDefinition = {
  name: string;
  icon?: string | null;
  members: GroupMember[];
  // Built-in machinery groups (plot-board beat/link shapes) set this so the
  // authoring UI hides them from the reusable-group pickers (#1003). Absent /
  // false on every user-defined group.
  system?: boolean;
};

// An entry type's use of a reusable group, with a display label + key prefix
// (e.g. GMO applied as External (external_) and Internal (internal_)).
export type GroupApplication = {
  group_id: string;
  label: string;
  key_prefix: string;
};

export type MetadataSchema = {
  version: number;
  entry_types: Record<string, EntryTypeDefinition>;
  fields: Record<string, MetadataFieldDefinition>;
  // Reusable group definitions keyed by group id (L2 groups).
  groups?: Record<string, MetadataGroupDefinition>;
  // Field ids that cascade down the manuscript structure, nearest-explicit-wins
  // (ADR-0079). Unioned up the layer chain; narration seeds [pov_mode, pov].
  cascade_fields?: string[];
};

export type MetadataSchemaLayer = {
  id: string;
  label: string;
  folder_path: string;
  schema_path: string;
  exists: boolean;
};

export type MetadataSchemaLayers = {
  layers: MetadataSchemaLayer[];
};

export type MetadataDefinitionSource = {
  layer_id: string;
  layer_label: string;
  schema_path?: string | null;
  built_in: boolean;
};

export type MetadataSchemaOverview = {
  effective_schema: MetadataSchema;
  layers: MetadataSchemaLayer[];
  entry_type_sources: Record<string, MetadataDefinitionSource>;
  field_sources: Record<string, MetadataDefinitionSource>;
};
