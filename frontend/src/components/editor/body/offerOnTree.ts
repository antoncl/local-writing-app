// Pure tree helpers for OfferOnPicker (#903, un-curated in #1199). Reuses
// `buildTree` — the shared schema→is-a-tree traversal behind the context picker
// (NodePickerConfigEditor / pickerTree.ts) — and layers offer_on's OWN selection
// model on top.
//
// The two models differ deliberately:
//   - The context picker stores concrete LEAVES; a parent checkbox toggles its
//     descendants.
//   - offer_on stores EXACT entry_type ids and matches is-a at READ time
//     (`promptOffersOn`). So selecting a parent stores the PARENT id itself, and
//     its descendants render as "covered" (offered via the ancestor) — never
//     re-stored. Storing the parent also covers subtypes added to the schema
//     later, which a leaf set would miss.
//
// Host filter (#1199). The read path (`promptOffersOn`) is fully general — any
// `offer_on` target surfaces + reviews, since #711 made the Conversations panel
// mount on EVERY node (self-hiding) and the entry-patch review overlay render for
// prose AND code bodies. So the picker's job is not to gate what is legal but to
// offer the targets that actually MOUNT a Conversations list — i.e. every
// entry_type whose class-level `opens_in` (inherited, like `has_body`/
// `body_shape`) resolves to `"editor"`: a NodeEditor always renders the metadata
// rail that hosts Conversations. `opens_in` is the single source of truth
// (replacing the old hardcoded `OFFER_ON_SECTIONS` curation) — everything else
// (`tree_container` / `board` / `dialog`) is a non-editor surface and stays out.
// An abstract type is kept regardless of its own `opens_in` (it's never a
// selectable leaf — only the "all of <kind>" grouping root for its concrete
// descendants); a concrete type is kept only when it resolves to `"editor"`.
//
// Rows are grouped by kind, one header per kind that has ≥1 eligible concrete
// type, in a stable order (lore/manuscript/plot/research/prompt, then any other
// kind alphabetically so a new kind still appears deterministically).

import type { MetadataSchema } from "@/lib/types";
import { buildTree, type SchemaNode } from "@/components/schema/pickerTree";

// Kinds in fixed render order first; any kind not listed here (a new schema
// kind, or one of the wider "editor" set like assistant/chat/view/project) is
// appended alphabetically by `orderedEligibleKinds` below.
const KIND_ORDER = ["lore", "manuscript", "plot", "research", "prompt"];

// Title-case a raw schema kind for the section header ("manuscript" → "Manuscript").
// No general kind→label table spans every kind here (assistant/chat/view/project
// included) — the existing ones (SCHEMA_KIND_META, NodePickerConfigEditor's KINDS)
// are narrower, purpose-built lists — so this stays a plain, deterministic fallback.
function kindLabel(kind: string): string {
  return kind.length === 0 ? kind : kind[0].toUpperCase() + kind.slice(1);
}

export type OfferOnState = "checked" | "covered" | "indeterminate" | "unchecked";

export type OfferOnRow =
  | { type: "header"; kind: string; label: string }
  | {
      type: "target";
      id: string;
      name: string;
      depth: number;
      // "checked"       — this exact id is in offer_on.
      // "covered"       — an ancestor is in offer_on; offered here via is-a, not
      //                   independently editable (the checkbox is on but disabled).
      // "indeterminate" — not itself on, but a descendant is directly selected.
      // "unchecked"     — none of the above.
      state: OfferOnState;
    };

function opensIn(schema: MetadataSchema, id: string): string {
  return schema.entry_types[id]?.opens_in ?? "editor";
}

function findNode(roots: SchemaNode[], id: string): SchemaNode | null {
  for (const root of roots) {
    if (root.id === id) return root;
    const hit = findNode(root.children, id);
    if (hit) return hit;
  }
  return null;
}

// All descendant ids (not self), skipping deprecated subtrees to match the render.
function descendantIds(node: SchemaNode, schema: MetadataSchema): string[] {
  const out: string[] = [];
  for (const child of node.children) {
    if (schema.entry_types[child.id]?.deprecated) continue;
    out.push(child.id, ...descendantIds(child, schema));
  }
  return out;
}

function hasSelectedDescendant(node: SchemaNode, schema: MetadataSchema, selection: Set<string>): boolean {
  for (const child of node.children) {
    if (schema.entry_types[child.id]?.deprecated) continue;
    if (selection.has(child.id)) return true;
    if (hasSelectedDescendant(child, schema, selection)) return true;
  }
  return false;
}

// Kinds with ≥1 eligible concrete type (opens_in === "editor" && !abstract),
// in stable render order.
function orderedEligibleKinds(schema: MetadataSchema): string[] {
  const kinds = new Set<string>();
  const eligible = new Set<string>();
  for (const def of Object.values(schema.entry_types ?? {})) {
    if (!def.kind) continue;
    kinds.add(def.kind);
    if (!def.abstract && !def.deprecated && (def.opens_in ?? "editor") === "editor") {
      eligible.add(def.kind);
    }
  }
  const known = KIND_ORDER.filter((k) => eligible.has(k));
  const rest = [...eligible].filter((k) => !KIND_ORDER.includes(k)).sort((a, b) => a.localeCompare(b));
  return [...known, ...rest];
}

// The depth-indented rows for one kind's is-a tree: abstract nodes are always
// kept (the "all of <kind>" grouping root and any intermediate abstract
// classes); concrete nodes are kept only when they resolve to `opens_in ===
// "editor"`. A pruned node is skipped but its children still recurse, at the
// next structural depth, so an editor descendant of a non-editor node isn't lost.
function kindRows(schema: MetadataSchema, kind: string, selection: Set<string>): OfferOnRow[] {
  const rows: OfferOnRow[] = [];
  const walk = (node: SchemaNode, depth: number, ancestorSelected: boolean): void => {
    if (schema.entry_types[node.id]?.deprecated) return;
    const keep = node.abstract || opensIn(schema, node.id) === "editor";
    let effectiveOn = ancestorSelected;
    if (keep) {
      const selected = selection.has(node.id);
      const covered = ancestorSelected;
      const state: OfferOnState = covered
        ? "covered"
        : selected
          ? "checked"
          : hasSelectedDescendant(node, schema, selection)
            ? "indeterminate"
            : "unchecked";
      rows.push({ type: "target", id: node.id, name: node.name, depth, state });
      effectiveOn = selected || covered;
    }
    for (const child of node.children) walk(child, depth + 1, effectiveOn);
  };
  for (const root of buildTree(schema, kind)) walk(root, 0, false);
  return rows;
}

// The grouped, depth-indented render list: a header row per eligible kind
// followed by its target rows.
export function offerOnRows(schema: MetadataSchema | null, offerOn: string[]): OfferOnRow[] {
  if (!schema) return [];
  const selection = new Set(offerOn);
  const rows: OfferOnRow[] = [];
  for (const kind of orderedEligibleKinds(schema)) {
    rows.push({ type: "header", kind, label: kindLabel(kind) });
    rows.push(...kindRows(schema, kind, selection));
  }
  return rows;
}

// Select `id`: add it and drop any now-redundant descendant entries (they are
// covered by this ancestor). Returns a new array.
export function selectTarget(offerOn: string[], schema: MetadataSchema | null, id: string): string[] {
  const next = new Set(offerOn);
  next.add(id);
  const kind = schema?.entry_types[id]?.kind;
  if (schema && kind) {
    const node = findNode(buildTree(schema, kind), id);
    if (node) {
      for (const descendant of descendantIds(node, schema)) next.delete(descendant);
    }
  }
  return [...next];
}

export function deselectTarget(offerOn: string[], id: string): string[] {
  return offerOn.filter((target) => target !== id);
}
