// Shared, pure helpers for the Detail Type editor (SchemaTypeEditor) and a
// handful of remaining callers in App.svelte. Extracted alongside the
// SchemaTypeEditor split (#14, second slice) so the component and the
// parent's API-touching handlers (saveSchemaField, applyGroupToType, …)
// both source the same definitions instead of duplicating them.
//
// Everything here is pure: schema/layer state is passed in as arguments
// rather than read from a closure, so the helpers work the same whether
// they're invoked from the component (where schema lives on props) or from
// App.svelte (where it lives on its own `let` bindings).

import { dedupeList, foldCaseInsensitive, splitCommaList } from "@/lib/utils/tags";
import type {
  EntryTypeDefinition,
  MetadataFieldDefinition,
  MetadataSchema,
  MetadataSchemaLayer,
  MetadataValue,
} from "@/lib/types";

// Whether a metadata value is "present" on an instance — i.e. the field carries
// a value, as opposed to being unset. `false` and `0` are present; `undefined`,
// `null`, `""` and an empty list are not. Used to tell a *set* boolean apart
// from a *cleared* one (#522): a two-state toggle otherwise renders "unset"
// identically to "off", which is the sharp case the clear-to-default gesture
// exists to fix. Pure so it can be unit-tested without a component.
export function isMetadataValuePresent(value: MetadataValue | undefined): boolean {
  if (Array.isArray(value)) return value.length > 0;
  return value !== undefined && value !== null && value !== "";
}

// ONE value → display-string rule (#698). Every review/display surface that
// hand-rolled `Array.join(", ")` rendered a list of RECORDS as
// "[object Object], [object Object]" — on exactly the surfaces where adopt /
// create decisions are made. Records render as their non-empty member values
// joined with " · " (the collapsed-row idiom), arrays join with ", ".
export function metadataValueDisplayString(value: MetadataValue | undefined): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) {
    return value
      .map((item) => metadataValueDisplayString(item))
      .filter(Boolean)
      .join(", ");
  }
  if (typeof value === "object") {
    return Object.values(value)
      .map((member) => metadataValueDisplayString(member))
      .filter(Boolean)
      .join(" · ");
  }
  return String(value);
}

// Coerce a metadata value into a clean string list: an array maps each item to a
// trimmed string (empties dropped); a scalar or comma-joined string tokenises
// through the canonical splitCommaList. The ONE home for "value → list" so the
// string and array coercions don't drift across call sites (#704/#722). No
// de-dupe here — that is a per-field-type policy layered on top by
// normalizeListFieldValue. Pure, so both are unit-tested without a component.
export function coerceStringList(value: MetadataValue | undefined): string[] {
  return Array.isArray(value)
    ? value.map((item) => String(item).trim()).filter(Boolean)
    : splitCommaList(String(value ?? ""));
}

// The SAVE-path normaliser for a list-shaped field value. Every set-typed list
// self-normalises on write, so a duplicate arriving from an importer or
// hand-edited YAML is de-duped on the way to disk, not only in the render (#704
// for tags; #725 generalised it to the siblings). The case policy differs by
// type and is deliberate, NOT a mechanical "dedupe everything":
//   - `tags` and `multi_select` are controlled vocabularies where case is
//     presentation → CASE-INSENSITIVE, first spelling wins. (The multi_select
//     toggle already MATCHES options case-insensitively, so the saved value must
//     fold the same way, else `Draft`/`draft` toggles as one but persists as two.)
//   - `entity_ref_list` items are entity identifiers (like collection membership)
//     → CASE-SENSITIVE: `Alpha` and `alpha` are two distinct refs.
// Any other field type is not set-shaped and passes through untouched.
export function normalizeListFieldValue(fieldType: string, value: MetadataValue): string[] {
  const items = coerceStringList(value);
  if (fieldType === "tags" || fieldType === "multi_select") return dedupeList(items, foldCaseInsensitive);
  if (fieldType === "entity_ref_list") return dedupeList(items);
  return items;
}

// The schema's kind universe (a Node's "class"). Narrower than the wider
// DocumentKind, which also covers chat / snippet / structure_node — none
// of which have their own schema-type tree.
export type SchemaKind = "scene" | "lore" | "research" | "prompt" | "assistant" | "project" | "plot";

// The UI metadata each kind-keyed surface needs: the Detail Types tab label,
// the tree's context heading, and the entry-type id to seed when a project has
// no type of that kind yet. `Record<SchemaKind, …>` makes this EXHAUSTIVE — a
// new SchemaKind fails to compile until it has a row here, which is the whole
// point: the per-kind ternaries this replaced (schemaFieldKind / heading /
// schemaTypeKind derivations in SchemaPanes) each silently defaulted an
// unlisted kind to "scene" or "lore", and adding `plot` missed three of them
// (#729). One table, one source of truth, one place to extend.
export interface SchemaKindMeta {
  label: string;
  heading: string;
  defaultType: string;
}
export const SCHEMA_KIND_META: Record<SchemaKind, SchemaKindMeta> = {
  scene: { label: "Scene", heading: "Scene Types", defaultType: "scene:scene" },
  lore: { label: "Lore", heading: "Lore Entry Types", defaultType: "lore:lore_note" },
  research: { label: "Research", heading: "Research Types", defaultType: "research:note" },
  prompt: { label: "Prompt", heading: "Prompt Types", defaultType: "prompt:base" },
  assistant: { label: "Assistant", heading: "Assistant Types", defaultType: "assistant:assistant" },
  project: { label: "Project", heading: "Project Types", defaultType: "project:project" },
  plot: { label: "Plot", heading: "Plot Types", defaultType: "plot:plotline" },
};

// The schema kinds in tab-strip display order (derived from the table's key
// order — insertion order for string keys).
export const SCHEMA_KINDS = Object.keys(SCHEMA_KIND_META) as SchemaKind[];

// Narrow an arbitrary entry-type `kind` string to a SchemaKind, or null. Use
// this wherever a value already meant to be a schema kind is read back off a
// definition — never a fall-through ternary that guesses a default.
export function asSchemaKind(kind: string | null | undefined): SchemaKind | null {
  // Object.hasOwn, NOT `in` — `in` walks the prototype chain, so a `kind` of
  // "constructor" / "toString" / "__proto__" would otherwise be accepted.
  return kind != null && Object.hasOwn(SCHEMA_KIND_META, kind) ? (kind as SchemaKind) : null;
}

// Map an editor DocumentKind to the SchemaKind whose type tree governs it.
// The editor opens plot via per-type documentKinds (`plot_template`, …) and
// scenes as `structure_node`, neither of which is a schema kind — so any
// schema-kind logic (Detail Types, "Edit type…") must resolve through here.
// Returns null for DocumentKinds with no schema tree (chat / snippet / view).
export function schemaKindForDocumentKind(documentKind: string): SchemaKind | null {
  if (documentKind === "structure_node") return "scene";
  if (documentKind.startsWith("plot")) return "plot";
  return asSchemaKind(documentKind);
}

// A field's effective display label, resolved against an ANCHOR entry type
// (#116, ADR-0029 §F). A per-type `field_overrides[key].label` on the anchor
// wins; otherwise the shared field def's `name`; otherwise the raw key. The
// anchor is the caller's choice: the rail / schema editor / NodeEditor pass the
// node's own `entry_type`; the kind-anchored Views picker passes the kind root
// (`kindRootEntryTypeId`), where cross-type conventions live. Overrides are
// already merged down the parent chain by the backend.
export function effectiveFieldLabel(
  schema: MetadataSchema | null,
  entryTypeId: string | null | undefined,
  fieldKey: string,
): string {
  const override = entryTypeId ? schema?.entry_types?.[entryTypeId]?.field_overrides?.[fieldKey] : undefined;
  const label = override?.label;
  if (typeof label === "string" && label.trim()) return label;
  return schema?.fields?.[fieldKey]?.name ?? fieldKey;
}

// Whether a field is hidden, resolved against an ANCHOR entry type (#116,
// ADR-0029 §F — see `effectiveFieldLabel` for the anchor convention). A
// per-type `field_overrides[key].hidden` (true OR false) wins over the field
// def's `hidden` default — so a type can un-hide a def-hidden field (e.g. `id`).
export function effectiveFieldHidden(
  schema: MetadataSchema | null,
  entryTypeId: string | null | undefined,
  fieldKey: string,
): boolean {
  const override = entryTypeId ? schema?.entry_types?.[entryTypeId]?.field_overrides?.[fieldKey] : undefined;
  if (override && typeof override.hidden === "boolean") return override.hidden;
  return Boolean(schema?.fields?.[fieldKey]?.hidden);
}

// The kind's root entry type — the anchor a kind-scoped surface (the Views
// picker) resolves per-type overrides against (ADR-0029 §F). Prefers the
// canonical `<kind>:base` abstract root (where built-in cross-type conventions
// like lore's `title → "Name"` sit); falls back to any type of the kind with no
// same-kind parent. Returns null if the kind has no types.
export function kindRootEntryTypeId(
  schema: MetadataSchema | null,
  kind: string,
): string | null {
  const entryTypes = schema?.entry_types ?? {};
  const canonical = `${kind}:base`;
  if (entryTypes[canonical]) return canonical;
  for (const [typeId, definition] of Object.entries(entryTypes)) {
    if (definition.kind !== kind) continue;
    const parent = definition.parent;
    if (!parent || entryTypes[parent]?.kind !== kind) return typeId;
  }
  return null;
}

// The local-key prefix a NEW sub-type nests its name-slug under (#600): the
// parent's local path (the FQN minus the `kind:` prefix), or "" when there is no
// parent or the parent is the kind's abstract root. So a top-level type stays
// flat (`lore:faction`, never `lore:base:faction`) while a sub-type of a
// concrete parent nests (`prompt:revise` → `prompt:revise:scene`). The colon is a
// pure naming separator — this drives the id it *rolls to*, not a validation
// invariant, so the author is free to reparent later without the id changing.
export function nestingLocalPrefix(
  schema: MetadataSchema | null,
  kind: string,
  parentFqn: string | null,
): string {
  if (!parentFqn || parentFqn === kindRootEntryTypeId(schema, kind)) return "";
  const prefix = `${kind}:`;
  return parentFqn.startsWith(prefix) ? parentFqn.slice(prefix.length) : "";
}

// --- entry_type-set field intersection (ADR-0031 §F) --------------------------
// The field roster a view node's picker offers is the fields present on EVERY
// member of its input set — a set-intersection over the concrete entry_types the
// input can contain (#215). This is group-aware by construction: each type's
// `fields` is its full inherited + group-applied list, so intersecting them keeps
// both vertically-inherited fields (a subtype family collapses to its base) AND
// horizontally-shared field-groups (unrelated types that apply the same group),
// while type-specific fields drop out. NOT a base-type/common-ancestor shortcut,
// which would be vertical-only and silently lose shared groups.

// The entry_types of a kind as `{ fqn, name }` options — the single roster the
// view designer (ViewBodyView) and the runtime param strip (viewParams) both
// offer, so the "which types does this kind expose" rule lives in one place.
// `includeAbstract` is for the `descendants_of` operator, whose root can be an
// abstract family head (e.g. `lore:base` = all lore); the default (concrete only)
// suits an exact `type` match and the intersection roster, where abstract types
// have no members.
export function kindEntryTypeOptions(
  schema: MetadataSchema | null,
  kind: string,
  includeAbstract = false,
): { fqn: string; name: string }[] {
  return Object.entries(schema?.entry_types ?? {})
    .filter(([, def]) => def.kind === kind && (includeAbstract || !def.abstract))
    .map(([fqn, def]) => ({ fqn, name: def.name }));
}

// All concrete (instantiable) entry_type FQNs of a kind — abstract types have no
// members, so they never constrain the intersection.
export function kindEntryTypeFqns(schema: MetadataSchema | null, kind: string): string[] {
  return kindEntryTypeOptions(schema, kind).map((o) => o.fqn);
}

// An entry_type FQN plus every concrete descendant (seed-inclusive), matching the
// `descendants_of` leaf's family semantics. Walks the parent chain downward.
export function descendantTypeFqns(schema: MetadataSchema | null, root: string): string[] {
  const entryTypes = schema?.entry_types ?? {};
  const out: string[] = [];
  const seen = new Set<string>();
  const walk = (fqn: string) => {
    if (seen.has(fqn)) return;
    seen.add(fqn);
    const def = entryTypes[fqn];
    if (def && !def.abstract) out.push(fqn);
    for (const [id, d] of Object.entries(entryTypes)) if (d.parent === fqn) walk(id);
  };
  walk(root);
  return out;
}

// The set-intersection of `fields` across a set of entry_type FQNs — the fields
// on every member. Empty input (no types) → empty set (a caller signals "fall
// back to the kind roster" separately). A single type → exactly its fields.
export function intersectFieldKeysOverTypes(schema: MetadataSchema | null, fqns: string[]): Set<string> {
  const entryTypes = schema?.entry_types ?? {};
  let acc: Set<string> | null = null;
  for (const fqn of fqns) {
    const fields = new Set(entryTypes[fqn]?.fields ?? []);
    if (acc === null) {
      acc = fields;
    } else {
      for (const k of [...acc]) if (!fields.has(k)) acc.delete(k);
    }
  }
  return acc ?? new Set<string>();
}

// Slugify a free-text label into a stable field/type id.
export function slugifyFieldId(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^[0-9]/, "field_$&");
}

// Suggest a key prefix for a group application from its label.
export function suggestPrefixFromLabel(label: string): string {
  const slug = slugifyFieldId(label);
  return slug ? `${slug}_` : "";
}

// Display name for a built-in or custom entry type.
export function nodeTypeDisplayName(
  typeId: string,
  definition: EntryTypeDefinition | undefined,
): string {
  if (typeId === "scene:scene") return "Scenes";
  if (typeId === "lore:base") return "Lore Entries";
  if (typeId === "prompt:base") return "Prompts";
  return definition?.name ?? typeId;
}

// Source-layer index (used as a CSS `--source-index`) for the colored
// badge that distinguishes system, project, and machine layers.
export function sourceLayerIndex(
  source: { layer_id: string; built_in: boolean } | undefined | null,
  layers: MetadataSchemaLayer[],
): number {
  if (!source || source.built_in) return 0;
  return Math.max(0, layers.findIndex((layer) => layer.id === source.layer_id) + 1);
}

// Short text for the source badge ("System" / layer label / "Unknown").
export function sourceBadgeLabel(
  source: { layer_label: string; built_in: boolean } | undefined | null,
): string {
  return source?.built_in ? "System" : (source?.layer_label ?? "Unknown");
}

// The type a given field is inherited from (its defining entry-type's
// display name) — for the "extends" jump label. Best-effort: the nearest
// ancestor whose own_fields includes the field.
export function inheritedFromLabel(
  entryTypeId: string,
  fieldId: string,
  schema: MetadataSchema | null,
): string {
  let cursor = schema?.entry_types[entryTypeId]?.parent ?? null;
  let guard = 0;
  while (cursor && guard < 20) {
    const def = schema?.entry_types[cursor];
    if (!def) break;
    if (Array.isArray(def.own_fields) ? def.own_fields.includes(fieldId) : def.fields?.includes(fieldId)) {
      return nodeTypeDisplayName(cursor, def);
    }
    cursor = def.parent ?? null;
    guard += 1;
  }
  return "parent";
}

// Display name for a group-derived field's origin marker.
export function groupOriginLabel(
  field: MetadataFieldDefinition,
  schema: MetadataSchema | null,
): string {
  if (field.group) return field.group;
  const def = field.group_origin ? schema?.groups?.[field.group_origin] : null;
  return def?.name ?? "group";
}

// L1 grouping for the type editor field rows. Ungrouped fields render
// first under no header, then each group in first-appearance order under
// its own section header. Preserves the underlying entry order so drag-
// reorder still operates on the stored sequence.
export type SchemaFieldSection = {
  group: string | null;
  entries: [string, MetadataFieldDefinition][];
};

export function buildSchemaFieldSections(
  entries: [string, MetadataFieldDefinition][],
): SchemaFieldSection[] {
  const ungrouped: [string, MetadataFieldDefinition][] = [];
  const groups = new Map<string, [string, MetadataFieldDefinition][]>();
  for (const entry of entries) {
    const group = (entry[1].group ?? "").trim();
    if (!group) {
      ungrouped.push(entry);
    } else {
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group)!.push(entry);
    }
  }
  const out: SchemaFieldSection[] = [];
  if (ungrouped.length) out.push({ group: null, entries: ungrouped });
  for (const [group, groupEntries] of groups) out.push({ group, entries: groupEntries });
  return out;
}

// One entry type as a flat option (id + display label + nesting depth).
export type NodeTypeOption = {
  id: string;
  label: string;
  depth: number;
  definition: EntryTypeDefinition;
};

// One entry type as a tree node for the Detail Types pane.
export type NodeTypeTreeNode = NodeTypeOption & {
  children: NodeTypeTreeNode[];
  // Field entries baked into the tree at build time so the recursive
  // renderNodeTypeCard snippet doesn't have to look them up via the
  // metadataSchema closure — see [[feedback-svelte5-reactivity-traps]]
  // trap 2: closures inside recursive snippets go stale after mutations
  // (a new field on a deep subtype didn't appear in its type's children
  // panel until a full reload).
  fieldEntries: [string, MetadataFieldDefinition][];
};

// Build the per-kind entry-type tree the Detail Types pane renders.
// Roots come first in a kind-specific order (the kind's canonical root —
// lore:base / prompt:base / research:base — or name-sorted for scene/
// assistant/project); children sort by display name. Each node bakes in its own
// field entries (see NodeTypeTreeNode).
export function buildNodeTypeTree(
  schema: MetadataSchema | null,
  kind: SchemaKind,
): NodeTypeTreeNode[] {
  const entryTypes = schema?.entry_types ?? {};
  const childrenByParent: Record<string, string[]> = {};
  const roots: string[] = [];
  for (const [typeId, definition] of Object.entries(entryTypes)) {
    if (definition.kind !== kind) continue;
    const parent = definition.parent;
    if (parent && entryTypes[parent]?.kind === kind) {
      childrenByParent[parent] = [...(childrenByParent[parent] ?? []), typeId];
    } else {
      roots.push(typeId);
    }
  }
  const compareByName = (left: string, right: string) =>
    nodeTypeDisplayName(left, entryTypes[left]).localeCompare(nodeTypeDisplayName(right, entryTypes[right]));
  for (const children of Object.values(childrenByParent)) {
    children.sort(compareByName);
  }
  const rootIds =
    kind === "lore" && entryTypes["lore:base"]
      ? ["lore:base"]
      : kind === "prompt" && entryTypes["prompt:base"]
        ? ["prompt:base"]
        : kind === "research" && entryTypes["research:base"]
          ? ["research:base"]
          : roots.sort(compareByName);
  const fieldsRegistry = schema?.fields ?? {};
  const buildNode = (typeId: string, depth: number): NodeTypeTreeNode | null => {
    const definition = entryTypes[typeId];
    if (!definition || definition.kind !== kind) return null;
    const children = (childrenByParent[typeId] ?? [])
      .map((childId) => buildNode(childId, depth + 1))
      .filter((child): child is NodeTypeTreeNode => Boolean(child));
    const fieldIds = definition.own_fields ?? definition.fields ?? [];
    const fieldEntries = fieldIds
      .map((fieldId): [string, MetadataFieldDefinition] | null => {
        const f = fieldsRegistry[fieldId];
        return f ? [fieldId, f] : null;
      })
      .filter((entry): entry is [string, MetadataFieldDefinition] => Boolean(entry));
    return {
      id: typeId,
      label: nodeTypeDisplayName(typeId, definition),
      depth,
      definition,
      children,
      fieldEntries,
    };
  };
  return rootIds.map((typeId) => buildNode(typeId, 0)).filter((node): node is NodeTypeTreeNode => Boolean(node));
}

// The Detail Types cascade as ONE pure step: the selected entry type resolves to
// its schema kind, and that single kind drives BOTH the tree roster AND the
// context heading. Extracted from SchemaPanes so this wiring is unit-testable —
// SchemaPanes is a headless RegionRegistrar controller (it registers render
// snippets with the workspace layout, it doesn't mount its own tree), so it
// can't be mounted to assert the rendered tree. Feeding a plot entry type here
// and asserting {kind:"plot", heading:"Plot Types", tree:[plot types]} is the
// guard for the exact path that shipped the Plot tab scoped to the Scene tree
// (#729). `entryTypeId` unknown → falls back to scene:scene → scene scope.
export interface SchemaScope {
  kind: SchemaKind;
  heading: string;
  tree: NodeTypeTreeNode[];
}
export function resolveSchemaScope(schema: MetadataSchema | null, entryTypeId: string): SchemaScope {
  const selected = schema?.entry_types[entryTypeId] ?? schema?.entry_types["scene:scene"];
  const kind = asSchemaKind(selected?.kind) ?? "scene";
  return { kind, heading: SCHEMA_KIND_META[kind].heading, tree: buildNodeTypeTree(schema, kind) };
}
