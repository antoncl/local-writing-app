// A reference-keyed list (ADR-0089 §1): a `list` field whose item shape
// carries EXACTLY ONE `entity_ref` member — that member is the item's KEY,
// one item per target. Mirrors `keyed_list_key` in
// `backend/app/services/project/metadata_refs.py:105-118` exactly, so the
// frontend and backend agree on which lists this class covers. Shared by the
// widget-routing gates (bodySections/bodyTabs/fieldRowModel, #2043/#2010's
// gates widened by ADR-0089 §6) and ReferenceListTab (the tab itself).
import { metadataValueDisplayString } from "@/lib/utils/schemaTypeHelpers";
import type { KeyedListShape } from "@/lib/editor-core/mutationListEdit";
import type { MetadataFieldDefinition, MetadataValue } from "@/lib/types";

/** The key member of a reference-keyed list, or null for every other field —
 *  a scalar list (`item_scalar`), a group with zero or two+ `entity_ref`
 *  members (no member is *the* key), or anything that isn't a group-shaped
 *  `list` at all (an `entity_ref_list` has no item shape to key). */
export function keyedListKeyMember(field: MetadataFieldDefinition | undefined | null): string | null {
  if (!field || field.type !== "list" || field.item_scalar) return null;
  const refKeys = (field.item_members ?? []).filter((member) => member.type === "entity_ref").map((member) => member.key);
  return refKeys.length === 1 ? refKeys[0] : null;
}

/** One list item's identity. A plain string item IS its id (today's
 *  `entity_ref_list` shape, and the scalar case in general); a folded record
 *  item's id is its key member's value, when that value is a non-empty
 *  string. Anything else — no key member on the field, a blank/non-string
 *  key (an orphaned item, ADR-0089 §9), a non-object non-string item — has
 *  no identity here. */
export function listItemKey(field: MetadataFieldDefinition | undefined | null, item: MetadataValue): string | null {
  if (typeof item === "string") return item;
  if (typeof item !== "object" || item === null || Array.isArray(item)) return null;
  const keyMember = keyedListKeyMember(field);
  if (!keyMember) return null;
  const key = (item as Record<string, MetadataValue>)[keyMember];
  return typeof key === "string" && key !== "" ? key : null;
}

/** The item's detail line (ADR-0089 §6): its NON-key members' display values,
 *  in `item_members` order, joined the one way (#698 — never a hand-rolled
 *  join). A `long_text` member contributes only its first line — the tab is
 *  not the item's full editor, the row's expansion is (BodyItemRows). */
export function itemMemberDetail(field: MetadataFieldDefinition | undefined | null, item: MetadataValue): string {
  const keyMember = keyedListKeyMember(field);
  if (!keyMember || typeof item !== "object" || item === null || Array.isArray(item)) return "";
  const record = item as Record<string, MetadataValue>;
  return (field?.item_members ?? [])
    .filter((member) => member.key !== keyMember)
    .map((member) => {
      const display = metadataValueDisplayString(record[member.key]);
      return member.type === "long_text" ? display.split("\n")[0] : display;
    })
    .filter(Boolean)
    .join(" · ");
}

/** A reference-keyed list's shape (ADR-0089 §5), read off the resolver-stamped
 *  `item_members`: the key member (empty string when the field isn't one —
 *  callers only reach here for an item row, where it always resolves) and
 *  every member's declared type, for `keyedListRowsFromEdit`'s member diff.
 *  Shared by the dialogs' chip/lock wiring, the authoring form's seeding, and
 *  the scrub-stop rewrite (`mutationStopEdit.ts`). A lib module, not a
 *  component's module script — moved here (#2074) so mutationStopEdit.ts can
 *  import it without importing a `.svelte` file's module script. */
export function keyedShapeFor(def: MetadataFieldDefinition): KeyedListShape {
  const memberTypes: Record<string, string> = {};
  for (const member of def.item_members ?? []) memberTypes[member.key] = member.type;
  return { keyMember: keyedListKeyMember(def) ?? "", memberTypes };
}
