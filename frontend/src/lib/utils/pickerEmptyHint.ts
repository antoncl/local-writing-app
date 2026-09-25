// #2215 — the picker's empty state is field-worded, not prompt-worded, when
// it's opened for a metadata field / group member rather than a prompt input
// (NodePickerPopover keeps its original copy unless a caller overrides it via
// `NodePickerEmptyHint`). Two builders, matching the two authoring contexts
// GroupsManagerDialog and the field editor cover: a top-level field points
// the writer at "the field's definition"; a reusable-group member names the
// group (when known) or falls back to "its group's definition".

import type { NodePickerEmptyHint } from "@/lib/pickerTypes";
import type { MetadataFieldDefinition, MetadataSchema } from "@/lib/types";

const TITLE = "This field can't point at anything yet";

export function fieldEmptyHint(): NodePickerEmptyHint {
  return {
    title: TITLE,
    detail: "Its targets aren't set. Choose what it can reference in the field's definition.",
  };
}

export function groupMemberEmptyHint(groupName: string | null | undefined, memberName: string): NodePickerEmptyHint {
  const where = groupName
    ? `the group's definition: Reusable groups → ${groupName} → ${memberName}`
    : "its group's definition (Reusable groups)";
  return {
    title: TITLE,
    detail: `Its targets aren't set. Choose what it can reference in ${where}.`,
  };
}

// A rail row's hint. A field generated from an applied reusable group
// (`group_origin`, never persisted) has no definition of its own to fix — its
// targets live on the group member — so it names the group; any other field
// points at its own definition.
export function railFieldEmptyHint(
  field: Pick<MetadataFieldDefinition, "name" | "group_origin">,
  schema: MetadataSchema | null,
): NodePickerEmptyHint {
  if (!field.group_origin) return fieldEmptyHint();
  return groupMemberEmptyHint(schema?.groups?.[field.group_origin]?.name ?? null, field.name);
}
