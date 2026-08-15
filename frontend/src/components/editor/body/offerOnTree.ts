// Pure tree helpers for OfferOnPicker (#903). Reuses `buildTree` — the shared
// schema→is-a-tree traversal behind the context picker (NodePickerConfigEditor /
// pickerTree.ts) — and layers offer_on's OWN selection model on top.
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
// Host filter. The read path (`promptOffersOn`) is fully general — any `offer_on`
// target surfaces + reviews, since #711 made the Conversations panel mount on EVERY
// node (self-hiding) and the entry-patch review overlay render for prose AND code
// bodies. So there is no dead-target bug left to defend against; this picker CURATES
// the ergonomic common targets rather than gating what is legal. It offers the
// body-authoring kinds — those with a prose or code body a commit prompt can rewrite
// through the run-diff review: ALL of `lore`, the `manuscript:scene` / `plot:card` /
// `plot:plotline` subtrees, and ALL of `prompt` (meta-prompting, #711). Reachable
// only by hand-authoring `offer_on` in the .md: containers (acts/chapters, plot
// boards/templates — siblings of the host roots, so anchoring each section at its
// root excludes them structurally), and body-less kinds (assistant / research:topic,
// whose field-only review has no body diff to render). Plotlines joined in S7b.

import type { MetadataSchema } from "@/lib/types";
import { buildTree, type SchemaNode } from "@/components/schema/pickerTree";

// The host sections, in render order. `rootId: null` = the whole kind (e.g. lore);
// otherwise the section is the subtree anchored at that host type.
export const OFFER_ON_SECTIONS: { kind: string; rootId: string | null }[] = [
  { kind: "lore", rootId: null },
  { kind: "manuscript", rootId: "manuscript:scene" },
  { kind: "plot", rootId: "plot:card" },
  { kind: "plot", rootId: "plot:plotline" },
  { kind: "prompt", rootId: null },
];

export type OfferOnState = "checked" | "covered" | "indeterminate" | "unchecked";

export type OfferOnRow = {
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

// The host roots for one section: the whole kind, or the subtree at `rootId`.
function sectionRoots(schema: MetadataSchema, kind: string, rootId: string | null): SchemaNode[] {
  const kindRoots = buildTree(schema, kind);
  if (rootId === null) return kindRoots;
  const node = findNode(kindRoots, rootId);
  return node ? [node] : [];
}

// The flat, depth-indented render list across all host sections. Abstract types
// are KEPT (an abstract root like `lore:base` is the natural "all lore" target,
// and the built-in revise-entry already targets it); deprecated types are dropped.
export function offerOnRows(schema: MetadataSchema | null, offerOn: string[]): OfferOnRow[] {
  if (!schema) return [];
  const selection = new Set(offerOn);
  const rows: OfferOnRow[] = [];
  const walk = (node: SchemaNode, depth: number, ancestorSelected: boolean): void => {
    if (schema.entry_types[node.id]?.deprecated) return;
    const selected = selection.has(node.id);
    const covered = ancestorSelected;
    const state: OfferOnState = covered
      ? "covered"
      : selected
        ? "checked"
        : hasSelectedDescendant(node, schema, selection)
          ? "indeterminate"
          : "unchecked";
    rows.push({ id: node.id, name: node.name, depth, state });
    const effectiveOn = selected || covered;
    for (const child of node.children) walk(child, depth + 1, effectiveOn);
  };
  for (const section of OFFER_ON_SECTIONS) {
    for (const root of sectionRoots(schema, section.kind, section.rootId)) walk(root, 0, false);
  }
  return rows;
}

// Select `id`: add it and drop any now-redundant descendant entries (they are
// covered by this ancestor). Returns a new array.
export function selectTarget(offerOn: string[], schema: MetadataSchema | null, id: string): string[] {
  const next = new Set(offerOn);
  next.add(id);
  if (schema) {
    for (const section of OFFER_ON_SECTIONS) {
      const node = findNode(buildTree(schema, section.kind), id);
      if (node) {
        for (const descendant of descendantIds(node, schema)) next.delete(descendant);
        break;
      }
    }
  }
  return [...next];
}

export function deselectTarget(offerOn: string[], id: string): string[] {
  return offerOn.filter((target) => target !== id);
}
