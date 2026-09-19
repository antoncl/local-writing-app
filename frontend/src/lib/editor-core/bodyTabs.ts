// Body tab strip (#2010): every `multiple` reference field (`entity_ref_list`,
// excluding a tag-vocabulary list — #2007's own mono line) of an entry type
// becomes its own tab beside the body, so a full list surfaces alongside the
// prose/fields instead of only as a rail pill row. Pure builder — no Svelte
// imports — mirrors `bodySections.ts` (#2009)'s shape: a schema/entryType walk
// in declared field order, no state of its own.
import { isTagListField } from "@/lib/utils/pickerCreate";
import { effectiveFieldHidden, effectiveFieldLabel } from "@/lib/utils/schemaTypeHelpers";
import type { BodyShape, EntryMetadata, MetadataSchema } from "@/lib/types";

export type BodyTab = {
  id: "body" | `list:${string}`;
  kind: "body" | "list";
  label: string;
  fieldId?: string;
  // A populated list's member count; undefined for an empty list (the tab
  // shows the label alone) and for the "body" tab.
  count?: number;
};

/** Every `entity_ref_list` field of `entryType` that earns its own body tab —
 *  schema order, tag lists / hidden / intrinsic fields excluded. Shared by
 *  `buildBodyTabs` and the rail (`fieldRowModel.ts`'s `listsInBody` gate). */
export function listTabFieldIds(
  schema: MetadataSchema | null | undefined,
  entryType: string | null | undefined,
): string[] {
  if (!schema || !entryType) return [];
  const fieldIds = schema.entry_types[entryType]?.fields ?? [];
  const out: string[] = [];
  for (const id of fieldIds) {
    const field = schema.fields[id];
    if (!field || field.type !== "entity_ref_list") continue;
    if (field.intrinsic) continue;
    if (isTagListField(field, schema)) continue;
    if (effectiveFieldHidden(schema, entryType, id)) continue;
    out.push(id);
  }
  return out;
}

/** The strip's tabs for one open node: a leading "Body" (or, for the `none`
 *  shape, "Details" — the rail-as-pane content that IS that node's body) tab,
 *  then one tab per list field in schema order. Empty (no strip at all) when
 *  the entry type declares no list fields — today's rendering, unchanged. */
export function buildBodyTabs(
  schema: MetadataSchema | null | undefined,
  entryType: string | null | undefined,
  bodyShape: BodyShape,
  metadata: EntryMetadata | null | undefined,
): BodyTab[] {
  const listFieldIds = listTabFieldIds(schema, entryType);
  if (listFieldIds.length === 0) return [];
  const tabs: BodyTab[] = [
    bodyShape === "none"
      ? { id: "body", kind: "body", label: "Details" }
      : { id: "body", kind: "body", label: "Body" },
  ];
  for (const id of listFieldIds) {
    const value = metadata?.[id];
    const count = Array.isArray(value) ? value.length : 0;
    tabs.push({
      id: `list:${id}`,
      kind: "list",
      label: effectiveFieldLabel(schema!, entryType!, id),
      fieldId: id,
      count: count > 0 ? count : undefined,
    });
  }
  return tabs;
}
