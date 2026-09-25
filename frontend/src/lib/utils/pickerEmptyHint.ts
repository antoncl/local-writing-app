// #2215 — the picker's empty state is field-worded, not prompt-worded, when
// it's opened for a metadata field / group member rather than a prompt input
// (NodePickerPopover keeps its original copy unless a caller overrides it via
// `NodePickerEmptyHint`). Two builders, matching the two authoring contexts
// GroupsManagerDialog and the field editor cover: a top-level field points
// the writer at "the field's definition"; a reusable-group member names the
// group (when known) or falls back to "its group's definition".

import type { NodePickerEmptyHint } from "@/lib/pickerTypes";

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
