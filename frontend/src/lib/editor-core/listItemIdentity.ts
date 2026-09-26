// ADR-0096 §1: a list field's item shape may declare an identity member —
// the one member that identifies an item across two versions of the entry
// (a proposal, a snapshot). The resolver stamps the declaration onto the
// field as `item_identity` (metadataTypes.ts), alongside `item_members`. This
// module is the ONE place every consumer reads that declaration from — never
// re-derive identity from a member named `id`.
import type { GroupMember, MetadataFieldDefinition } from "@/lib/types";

/** The declared identity member's key, or null — for a scalar list
 *  (`item_scalar`: nothing to identify beyond the one synthetic member), a
 *  field that isn't a group-shaped `list` at all, or a group that declares
 *  no identity. */
export function itemIdentityKey(field: MetadataFieldDefinition | null | undefined): string | null {
  if (!field || field.type !== "list" || field.item_scalar) return null;
  return field.item_identity ?? null;
}

/** `item_members` with the identity member excluded — the shape every item
 *  editor renders. The identity member is machine-owned: never shown, never
 *  editable, never the title, and not counted toward the item shape's
 *  density/layout. Writes still preserve it (callers spread the existing
 *  item rather than rebuilding it from the visible members). */
export function visibleItemMembers(field: MetadataFieldDefinition | null | undefined): GroupMember[] {
  const members = field?.item_members ?? [];
  const identityKey = itemIdentityKey(field);
  return identityKey ? members.filter((member) => member.key !== identityKey) : members;
}
