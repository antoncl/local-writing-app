// Body tab strip (#2010): every `multiple` reference field (`entity_ref_list`,
// excluding a tag-vocabulary list — #2007's own mono line) of an entry type
// becomes its own tab beside the body, so a full list surfaces alongside the
// prose/fields instead of only as a rail pill row. Pure builder — no Svelte
// imports — mirrors `bodySections.ts` (#2009)'s shape: a schema/entryType walk
// in declared field order, no state of its own.
//
// ADR-0089 Amendment 1 (#2100): a field's Section (`field.group`, an L1
// rail/type-editor header — see `buildSchemaFieldSections`) now ALSO keys its
// body tab — fields sharing a Section merge into one tab instead of each
// getting its own.
import { isTagListField } from "@/lib/utils/pickerCreate";
import { effectiveFieldLabel, effectiveFieldHidden } from "@/lib/utils/schemaTypeHelpers";
import { keyedListKeyMember } from "@/lib/editor-core/keyedList";
import type { BodyShape, EntryMetadata, MetadataSchema } from "@/lib/types";

export type BodyTab = {
  id: "body" | `list:${string}`;
  kind: "body" | "list";
  label: string;
  // The list field(s) rendered in this tab — one for a blank-Section field's
  // own fallback tab, several for a shared Section's merged tab. Empty for
  // the leading "body"/"details" tab.
  fieldIds: string[];
  // A populated list's member count, summed across `fieldIds`; undefined
  // when every member field is empty (the tab shows the label alone) and for
  // the "body" tab.
  count?: number;
};

/** The tab id a collection field belongs to (ADR-0089 Amendment 1, #2100):
 *  its Section (`field.group`, trimmed) when non-blank — every field sharing
 *  that Section shares this id, merging into one tab — else the field's own
 *  id as a fallback tab (a blank-Section field rendering inline in Body
 *  instead is a separate, later slice — out of scope here). Shared by
 *  `buildBodyTabs` and the rail jump (NodeEditor's `goToList`) so the strip
 *  and the jump target can never disagree. `entryType` is accepted for
 *  signature symmetry with `effectiveFieldLabel` — `group` is a global
 *  field-def property, not per-type overridable, so it goes unused today. */
export function tabIdForField(
  schema: MetadataSchema | null | undefined,
  entryType: string | null | undefined,
  fieldId: string,
): string {
  const group = (schema?.fields[fieldId]?.group ?? "").trim();
  return group ? `list:group:${group}` : `list:${fieldId}`;
}

/** Every `entity_ref_list` field of `entryType`, plus every reference-keyed
 *  `list` field (ADR-0089 §6 — the key outranks the prose gate), that earns
 *  its own body tab — schema order, tag lists / hidden / intrinsic fields
 *  excluded. Shared by `buildBodyTabs` and the rail (`fieldRowModel.ts`'s
 *  `listsInBody` gate). */
export function listTabFieldIds(
  schema: MetadataSchema | null | undefined,
  entryType: string | null | undefined,
): string[] {
  if (!schema || !entryType) return [];
  const fieldIds = schema.entry_types[entryType]?.fields ?? [];
  const out: string[] = [];
  for (const id of fieldIds) {
    const field = schema.fields[id];
    if (!field || (field.type !== "entity_ref_list" && !keyedListKeyMember(field))) continue;
    if (field.intrinsic) continue;
    if (isTagListField(field, schema)) continue;
    if (effectiveFieldHidden(schema, entryType, id)) continue;
    out.push(id);
  }
  return out;
}

/** The strip's tabs for one open node: a leading "Body" (or, for the `none`
 *  shape, "Details" — the rail-as-pane content that IS that node's body) tab,
 *  then one tab per list field's `tabIdForField` bucket, in first-appearance
 *  order (mirrors `buildSchemaFieldSections`'s grouping) — several fields
 *  sharing a Section land in one tab, `fieldIds` in schema order. Empty (no
 *  strip at all) when the entry type declares no list fields — today's
 *  rendering, unchanged. */
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
      ? { id: "body", kind: "body", label: "Details", fieldIds: [] }
      : { id: "body", kind: "body", label: "Body", fieldIds: [] },
  ];
  const tabById = new Map<string, BodyTab>();
  for (const id of listFieldIds) {
    const tabId = tabIdForField(schema, entryType, id);
    const value = metadata?.[id];
    const count = Array.isArray(value) ? value.length : 0;
    let tab = tabById.get(tabId);
    if (!tab) {
      const group = (schema!.fields[id]?.group ?? "").trim();
      tab = {
        id: tabId as `list:${string}`,
        kind: "list",
        label: group || effectiveFieldLabel(schema!, entryType!, id),
        fieldIds: [],
        count: undefined,
      };
      tabById.set(tabId, tab);
      tabs.push(tab);
    }
    tab.fieldIds.push(id);
    if (count > 0) tab.count = (tab.count ?? 0) + count;
  }
  return tabs;
}
