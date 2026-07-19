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

import type {
  EntryTypeDefinition,
  MetadataFieldDefinition,
  MetadataSchema,
  MetadataSchemaLayer,
} from "@/lib/types";

// The schema's kind universe (a Node's "class"). Narrower than the wider
// DocumentKind, which also covers chat / snippet / structure_node — none
// of which have their own schema-type tree.
export type SchemaKind = "scene" | "lore" | "research" | "prompt" | "assistant" | "project";

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
