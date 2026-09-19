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
import type { MetadataSchema } from "@/lib/types";

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
