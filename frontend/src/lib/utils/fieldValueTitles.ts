// ADR-0091 §7 / #2133 — a reference VALUE renders as a title in the Propagate
// diff, never by the shape of the id: a value is a reference when today's
// schema types its field so (`entity_ref`, `entity_ref_list`, or a `list`
// field whose item_members include one of those — the ADR-0089 relationship-
// item shape), resolved through the SAME roster recipe MetadataPanel's rail
// uses (`buildRefResolver`). An id no roster knows renders as the id.
import { isRefField } from "@/lib/metadataTypes";
import type { GroupMember, MetadataSchema } from "@/lib/types";

/** `resolve` returns the title for an id, or `null` when no roster knows it —
 *  the caller (PropagateDiff) renders `null` as the id itself. */
export type TitleResolve = (id: string) => string | null;

/** Whether a field's VALUE is one or more node references, from its schema
 *  type alone. `null` for every other field type (never guessed from the
 *  id's shape). */
export function referenceFieldKind(
  schema: MetadataSchema | null,
  fieldId: string,
): "single" | "list" | null {
  const field = schema?.fields?.[fieldId];
  if (!field) return null;
  if (field.type === "entity_ref") return "single";
  if (field.type === "entity_ref_list") return "list";
  if (field.type === "list" && (field.item_members ?? []).some((member) => isRefField(member))) return "list";
  return null;
}

function idsLabel(value: unknown, resolve: TitleResolve): string {
  if (Array.isArray(value)) {
    return value.map((id) => idLabel(id, resolve)).join(", ");
  }
  return idLabel(value, resolve);
}

function idLabel(id: unknown, resolve: TitleResolve): string {
  const idString = String(id);
  return resolve(idString) ?? idString;
}

function memberLabel(
  member: GroupMember | undefined,
  value: unknown,
  resolve: TitleResolve,
): string {
  if (member && isRefField(member)) return idsLabel(value, resolve);
  return String(value);
}

/** A single (non-list) field VALUE, as the pane's non-list diff branch shows
 *  it: a reference resolves to its title (or the id, unresolved); anything
 *  else renders unchanged. `(none)` for a blank value, matching the pane's
 *  existing formatting. */
export function fieldValueLabel(
  schema: MetadataSchema | null,
  fieldId: string,
  value: unknown,
  resolve: TitleResolve,
): string {
  if (value === null || value === undefined || value === "") return "(none)";
  if (referenceFieldKind(schema, fieldId) === "single") return idLabel(value, resolve);
  return String(value);
}

/** One item of a LIST-shaped field value, as `listDiff`'s `itemLabel` callback
 *  (the compare key stays `listItemText`; this is display only). A plain
 *  `entity_ref_list` item is the id itself; an ADR-0089 relationship-item
 *  record composes its non-empty members, resolving any ref-typed member
 *  through the same roster, joined the way `listItemText` already reads such
 *  an item (" · "). */
export function listItemLabel(
  schema: MetadataSchema | null,
  fieldId: string,
  item: unknown,
  resolve: TitleResolve,
): string {
  const field = schema?.fields?.[fieldId];
  if (item !== null && typeof item === "object" && !Array.isArray(item)) {
    const members = field?.item_members ?? [];
    const memberByKey = new Map(members.map((member) => [member.key, member] as const));
    return Object.entries(item as Record<string, unknown>)
      .filter(([, v]) => v !== null && v !== undefined && v !== "")
      .map(([key, v]) => memberLabel(memberByKey.get(key), v, resolve))
      .join(" · ");
  }
  if (referenceFieldKind(schema, fieldId) === "list") return idLabel(item, resolve);
  return String(item);
}
