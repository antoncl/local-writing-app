// Metadata value + field-definition wire types. Extracted from types.ts to
// keep that barrel under the file-size cap; re-exported from `@/lib/types` so
// it stays the single import surface.

import type { NodePickerConfig } from "./pickerTypes";
import type { GroupMember } from "./schemaTypes";

export type MetadataValue = string | number | boolean | null | MetadataValue[] | { [key: string]: MetadataValue };

export type EntryMetadata = Record<string, MetadataValue>;

export type MetadataFieldType =
  | "text"
  | "long_text"
  | "number"
  | "boolean"
  | "date"
  | "select"
  | "multi_select"
  | "entity_ref"
  | "entity_ref_list"
  | "computed"
  | "color"
  | "list";

// The scalar item shapes a `list` field may declare via `item_type` (#698,
// ADR-0048 §6). Deliberately narrower than MetadataFieldType: the item_type
// sugar is a single scalar per item (nesting a list in a list is not a thing).
// Refs/tags are not item_type shapes — they enter through named item_group
// members instead (LIST_ITEM_GROUP_MEMBER_TYPES, ADR-0081). The const is the
// item_type picker's choices; the union derives from it so the two cannot
// drift. Mirrors the backend's LIST_ITEM_SCALAR_TYPES.
export const LIST_ITEM_SCALAR_TYPES = ["text", "long_text", "number", "boolean", "select", "color"] as const;
export type ListItemScalarType = (typeof LIST_ITEM_SCALAR_TYPES)[number];

// The types an item_group MEMBER may be (ADR-0081): the scalars above plus the
// reference types. Broader than the item_type sugar (which stays scalar-only)
// — a named group member can hold a reference, because its lifecycle reaches a
// nested value (a ref indexed / scrubbed / healed, like a top-level one). Used
// for group-shape filtering in the schema editor. Mirrors the backend
// LIST_ITEM_GROUP_MEMBER_TYPES. `tags` retired (ADR-0082 slice 2b) — a tag
// vocabulary is authored as `entity_ref_list` with `create_missing`.
export const LIST_ITEM_GROUP_MEMBER_TYPES = [
  ...LIST_ITEM_SCALAR_TYPES,
  "entity_ref",
  "entity_ref_list",
] as const;

// One choice in a select / multi_select field, or a select prompt input.
// Stored as `{value, label?, color?}`. Bare strings are accepted on the wire
// (the backend normalizes) but emitted as objects. A state the app holds
// rather than the author is not an option attribute — the FIELD declares it
// (`MetadataFieldDefinition.derived`, #1911).
export type SelectOption = {
  value: string;
  label?: string | null;
  color?: string | null;
};

/** A select state the app holds, never the author (#1911): the field takes
 * `value` on a node whenever the reference field `when_set` is set, and a
 * stale `value` is cleared when it is not. The backend healer applies it on
 * read and save; the rail never offers `value` and locks a row holding it;
 * a view filter or a param may still name it. */
export type DerivedSelectState = {
  value: string;
  when_set: string;
};

/** The option value a field's derived state holds, or null when it declares
 * none — the one reader every pick list and the rail's read-only gate use. */
export function derivedSelectValue(field: MetadataFieldDefinition | null | undefined): string | null {
  return field?.type === "select" && field.derived ? field.derived.value : null;
}

/** A required select (#1421): a select with a non-blank default. A blank value
 *  MEANS the default everywhere — the rail shows it, an edit back to it pops
 *  the key, Views and the selector roster read it (#1908). The one spelling. */
export function isRequiredSelect(
  field: MetadataFieldDefinition | null | undefined,
): field is MetadataFieldDefinition & { default: string } {
  return field?.type === "select" && typeof field.default === "string" && field.default !== "";
}

/** The value a select is in force with: the stored value, or — for a required
 *  select holding nothing (absent, "", or an empty list) — its default. */
export function effectiveSelectValue(field: MetadataFieldDefinition | null | undefined, raw: unknown): unknown {
  if (!isRequiredSelect(field)) return raw;
  const blank = raw == null || raw === "" || (Array.isArray(raw) && raw.length === 0);
  return blank ? field.default : raw;
}

export type MetadataFieldDefinition = {
  name: string;
  type: MetadataFieldType;
  options: SelectOption[];
  // For entity_ref / entity_ref_list — constrains which nodes the
  // picker offers. Shape mirrors PromptInputDefinition.target for
  // context_pick inputs, so entity_ref fields and prompt picks share
  // the same NodePicker config vocabulary.
  picker_config?: NodePickerConfig | null;
  computed?: Record<string, string> | null;
  // Optional Tabler icon name (without the `ti-` prefix), e.g. "shield-half".
  // Empty/undefined falls back to the default glyph for the field's type.
  // Display-only — the stable macro contract is the field key, not the icon.
  icon?: string | null;
  // Optional author help text: what the field is for (#1004). Shown as a rail
  // tooltip, and fed to the brainstorm/extraction model so it proposes
  // on-target values. Undefined = no description.
  description?: string | null;
  // Optional L1 section label. Fields sharing a `group` render under one
  // labelled header in the rail + type editor. Undefined = ungrouped.
  group?: string | null;
  // Set only on synthetic fields generated from an L2 group application
  // (= the source group id). Lets the UI render these as group-derived
  // (read-only, "from <group>") rather than own/inherited. Never persisted.
  group_origin?: string | null;
  // Optional initial value seeded onto new entries of any type that
  // carries this field (#38). Type-matched per `type`; computed fields
  // never carry a default.
  default?: MetadataValue | null;
  // A select state the app derives from a reference field (#1911) — see
  // `DerivedSelectState`. Selects only; `value` names one of `options`.
  derived?: DerivedSelectState | null;
  // Intrinsic (#116): value lives on the node's top-level front matter
  // (`id` / `title` / `entry_type`), not in `metadata`. Consumers read it
  // from the node property keyed by the field id — but prefer `category`
  // (below), the resolver-stamped single source of truth.
  intrinsic?: boolean;
  // Hidden by default from the per-node rail and Views field picker.
  hidden?: boolean;
  // Whether the AI may author this field's value on a brainstorm commit
  // (ADR-0059 §E). Default true (omitted on save when true); set false to mark
  // the field off-limits — the built-in `context_policy` ships false. Moot for
  // never-proposable types (computed / entity_ref / entity_ref_list).
  ai_proposable?: boolean;
  // Authorship category (ADR-0029 §D), stamped by the backend resolver on
  // every resolved field: `intrinsic` (identity triple, on `node.<key>`),
  // `computed` (app-produced, read-only), else `stored` (`metadata.<key>`).
  // The single signal every surface consults — never re-derive it from
  // `intrinsic` / `type === "computed"` / key membership on the frontend.
  category?: "stored" | "intrinsic" | "computed";
  // `list` fields only (#698, ADR-0048 §6): exactly one of item_group (a
  // MetadataGroupDefinition id — the item shape, kept nested) or item_type
  // (single-scalar sugar; values store as a flat scalar list, and a select
  // item reads its choices from this field's `options`).
  item_group?: string | null;
  item_type?: ListItemScalarType | null;
  // DERIVED (resolver-stamped, like `category`): the resolved item shape —
  // the group's members, or the item_type sugar normalized to a one-member
  // shape (key "value"). The widget and validation read ONLY this; never
  // send it back on save.
  item_members?: GroupMember[] | null;
  // DERIVED with item_members: true when the stamped shape is the scalar
  // sugar (flat storage). THE shape discriminator — never branch on
  // item_type, which a cross-layer conflict can leave set while the group
  // won the tie.
  item_scalar?: boolean | null;
};
