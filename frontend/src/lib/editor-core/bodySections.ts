// Body Sections (#2009): every `long_text` field of an entry type renders as a
// headed section stacked under the prose body (`BodySections.svelte`) instead
// of a rail editor. Pure builder — no Svelte imports — so it's unit-testable
// without mounting anything. Grouping mirrors MetadataPanel's L1 section model
// (`buildSections` in MetadataPanel.svelte): an ungrouped long_text is its own
// single-field group (`group: null`, rendered as an H2); fields sharing a
// `group` collect under that group in first-appearance order (rendered as an
// H2 group heading with an H3 per field). A group ALWAYS renders its heading,
// even with a single member field (#2009 decided) — unlike the rail's own
// section model, which only heads a block once there is more than one.
import { effectiveFieldHidden, effectiveFieldLabel } from "@/lib/utils/schemaTypeHelpers";
import { keyedListKeyMember } from "@/lib/editor-core/keyedList";
import type { MetadataFieldDefinition, MetadataSchema, MetadataValue } from "@/lib/types";
import type { GroupMember } from "@/lib/schemaTypes";

export type BodySectionField = { id: string; label: string };

/** One rendered block: `group: null` is a single ungrouped field (H2 = the
 *  field's own label); a named group is `label` = the group name, heading an
 *  H2 with one H3 per member field. */
export type BodySectionGroup = { group: string | null; label: string | null; fields: BodySectionField[] };

export function buildBodySections(
  schema: MetadataSchema | null | undefined,
  entryType: string | null | undefined,
): BodySectionGroup[] {
  if (!schema || !entryType) return [];
  const fieldIds = schema.entry_types[entryType]?.fields ?? [];
  const groups: BodySectionGroup[] = [];
  const groupIndex = new Map<string, number>();
  for (const id of fieldIds) {
    const field = schema.fields[id];
    if (!field || field.type !== "long_text") continue;
    // The body field itself (and any other intrinsic) is never a section —
    // it's the prose above, not metadata.
    if (field.intrinsic) continue;
    if (effectiveFieldHidden(schema, entryType, id)) continue;
    const label = effectiveFieldLabel(schema, entryType, id);
    const groupName = (field.group ?? "").trim() || null;
    if (groupName === null) {
      groups.push({ group: null, label, fields: [{ id, label }] });
      continue;
    }
    let index = groupIndex.get(groupName);
    if (index === undefined) {
      index = groups.length;
      groupIndex.set(groupName, index);
      groups.push({ group: groupName, label: groupName, fields: [] });
    }
    groups[index].fields.push({ id, label });
  }
  return groups;
}

// ---- Repeating sections (#2043) --------------------------------------------
// A `list` field whose item shape carries a long_text member is material too:
// it renders as a headed section AFTER the long_text sections, one sub-section
// per item, the item's long_text members as stacked editors and its other
// members as rail rows (an item is a node editor in miniature). A list of
// scalar items (follow_ups) is a fact list and stays in the rail. The rule
// reads the resolver-stamped `item_members` (never `item_type`, which the
// resolver may have overridden — metadataTypes.ts), so the scalar sugar
// `item_type: long_text` (one member keyed "value") qualifies the same way.

/** Whether this field is a list whose items carry prose — the one rule the
 *  section builder, the rail's index row and the body renderer all share.
 *  ADR-0089 §6: a reference-keyed list (`keyedListKeyMember`) is a
 *  reference-list tab regardless of its members, even a `long_text` one —
 *  the key outranks the prose gate. */
export function listHasProseItems(field: MetadataFieldDefinition | null | undefined): boolean {
  if (keyedListKeyMember(field)) return false;
  return !!field && field.type === "list" && (field.item_members ?? []).some((m) => m.type === "long_text");
}

export type BodyListSection = {
  id: string;
  label: string;
  /** The member whose value heads each item (the first `text` member), or null
   *  when the shape has none — then the item's ordinal is its heading. */
  titleKey: string | null;
  /** The item's long_text members, in shape order — each a stacked editor. */
  proseMembers: GroupMember[];
  /** Every other member (never the title, never prose) — the item's rail rows. */
  factMembers: GroupMember[];
};

export function buildBodyListSections(
  schema: MetadataSchema | null | undefined,
  entryType: string | null | undefined,
): BodyListSection[] {
  if (!schema || !entryType) return [];
  const fieldIds = schema.entry_types[entryType]?.fields ?? [];
  const sections: BodyListSection[] = [];
  for (const id of fieldIds) {
    const field = schema.fields[id];
    if (!listHasProseItems(field) || field!.intrinsic) continue;
    if (effectiveFieldHidden(schema, entryType, id)) continue;
    const members = field!.item_members ?? [];
    const title = members.find((m) => m.type === "text") ?? null;
    sections.push({
      id,
      label: effectiveFieldLabel(schema, entryType, id),
      titleKey: title?.key ?? null,
      proseMembers: members.filter((m) => m.type === "long_text"),
      factMembers: members.filter((m) => m.type !== "long_text" && m !== title),
    });
  }
  return sections;
}

/** The keyboard-bridge id of one item's one prose editor: unique across the
 *  document, stable while the item keeps its index. */
export function listItemEditorId(listId: string, index: number, memberKey: string): string {
  return `${listId}[${index}].${memberKey}`;
}

/** Whether `editorId` names a prose editor inside the list `listId` (#2052):
 *  the one place that knows the `list[index].member` shape besides the
 *  minter above. */
export function isListItemEditorId(listId: string, editorId: string): boolean {
  return editorId.startsWith(`${listId}[`);
}

/** The items of a list field's value: the stored array, or none when the value is
 *  absent or not an array. The one reading shared by every host of a list section
 *  (BodySections, the plot board's PlotBeatSections). */
export function listItemsOf(metadata: Record<string, MetadataValue>, listId: string): MetadataValue[] {
  const value = metadata[listId];
  return Array.isArray(value) ? (value as MetadataValue[]) : [];
}
