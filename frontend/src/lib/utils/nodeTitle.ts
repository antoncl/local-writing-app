import type { MetadataSchema, StructureNode } from "@/lib/types";

// The one resolver for a node's DISPLAY title — the `getTitle` the type
// hierarchy would hand us if the app were object-oriented. Every surface that
// shows a manuscript node's label (the tree, editor tabs, plot-board columns)
// funnels through here instead of re-implementing the template, so the
// reorder-live `{number}` shows up the same way everywhere.
//
// Fills `{title}` from `title` and every other `{field}` from `metadata` (which
// must already carry any computed values, e.g. the `number` counter). Absent
// fields render empty; the result is trimmed so a missing placeholder (a node
// with no number yet) leaves no stray gap.
export function applyDisplayTemplate(
  entryType: string,
  title: string,
  metadata: Record<string, unknown> | null | undefined,
  schema: MetadataSchema | null | undefined,
): string {
  const template = schema?.entry_types?.[entryType]?.display_template ?? "{title}";
  return template
    .replace(/\{(\w+)\}/g, (_match, field: string) => {
      if (field === "title") return title;
      const value = metadata?.[field];
      return value !== undefined && value !== null ? String(value) : "";
    })
    .trim();
}

// Resolve a structure node straight from the tree: merge its stored `metadata`
// with the backend-injected `computed_metadata` (where the live `number` lives),
// then apply the template. `titleOverride` lets a caller substitute an unsaved
// draft title (an in-flight rename) without losing the number.
export function structureNodeTitle(
  node: StructureNode,
  schema: MetadataSchema | null | undefined,
  titleOverride?: string,
): string {
  const metadata = { ...(node.metadata ?? {}), ...(node.computed_metadata ?? {}) };
  return applyDisplayTemplate(node.type, titleOverride ?? node.title, metadata, schema);
}
