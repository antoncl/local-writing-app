/**
 * The text a list review renders (ADR-0096 §6, S3): markdown built, not
 * passed through, so a title or member value that happens to look like
 * markdown syntax ("1. Setup", "# x", "*x*") reads as literal text once it
 * goes through `renderDiffRuns`/`sceneMarkdownToHtml`.
 *
 * Pure and tested standalone — `ListReviewSection.svelte` is the one caller.
 */
import { itemRecord, isBlankMemberValue } from "@/lib/utils/listCompare";
import { visibleItemMembers } from "@/lib/editor-core/listItemIdentity";
import type { GroupMember, MetadataFieldDefinition, MetadataValue } from "@/lib/types";

/** Escape the ASCII punctuation that would otherwise read as markdown syntax
 *  once the text is rendered — a title like "1. Setup", "# x", "*x*", "- x",
 *  "> x", "[x](y)" or "<b>" must render as those literal characters. Inline
 *  markers (`*_`` `[` `]` `<`) are escaped wherever they appear; a
 *  line-leading list/heading/blockquote marker is escaped only at the start
 *  of its line, so escaping does not spuriously double up (an already-escaped
 *  inline `*` doesn't need its leading-marker rule applied too). */
export function escapeMarkdown(text: string): string {
  return text
    .split("\n")
    .map((line) => {
      let escaped = line.replace(/\\/g, "\\\\").replace(/[*_`[\]<]/g, "\\$&");
      escaped = escaped.replace(/^(\s{0,3})(\d{1,9})([.)])/, "$1$2\\$3");
      escaped = escaped.replace(/^(\s{0,3})([-+#>])/, "$1\\$2");
      return escaped;
    })
    .join("\n");
}

/** The item shape's title member — its first `text` member other than the
 *  identity member (already excluded by `visibleItemMembers`) — or null for a
 *  scalar list (titled by its bare value, handled separately by `itemTitle`)
 *  or a group with no `text` member. */
export function titleMemberKey(field: MetadataFieldDefinition): string | null {
  if (field.item_scalar) return null;
  const member = visibleItemMembers(field).find((m) => m.type === "text");
  return member?.key ?? null;
}

/** An item's title, RAW (not markdown-escaped — callers that render it
 *  through markdown, `itemMarkdown`/`orderMarkdown`, escape it themselves; a
 *  quiet unchanged-item line renders it as plain text and must not see
 *  backslashes). A scalar list's item IS its value; a group-shaped item's
 *  title is its title member's value, or positional ("Item N") absent one or
 *  a group with none declared. */
export function itemTitle(field: MetadataFieldDefinition, item: MetadataValue, index: number): string {
  const record = itemRecord(field, item);
  if (field.item_scalar) return displayScalar(record.value);
  const key = titleMemberKey(field);
  const raw = key ? record[key] : undefined;
  if (raw === undefined || raw === null || raw === "") return `Item ${index + 1}`;
  return displayScalar(raw);
}

function displayScalar(value: MetadataValue | undefined): string {
  if (value === null || value === undefined) return "";
  return typeof value === "string" ? value : String(value);
}

/** A member's display text: the default applied to an absent value, a
 *  boolean as "Yes"/"No", a select/multi_select as its option's label(s), an
 *  entity_ref(_list) as its target's title (`resolveTitle`) falling back to
 *  the raw id, an array joined ", ", an empty value as "—". Always
 *  markdown-escaped — every caller renders it through markdown. */
export function memberDisplayText(
  member: GroupMember,
  value: MetadataValue | undefined,
  resolveTitle?: (id: string) => string | null,
): string {
  const effective = value === undefined || value === null ? (member.default ?? null) : value;
  if (effective === null || effective === "" || (Array.isArray(effective) && effective.length === 0)) return "—";
  if (typeof effective === "boolean") return effective ? "Yes" : "No";
  if (member.type === "select" || member.type === "multi_select") {
    const label = (raw: MetadataValue): string => {
      const option = (member.options ?? []).find((o) => o.value === String(raw));
      return option?.label ?? String(raw);
    };
    const text = Array.isArray(effective) ? effective.map(label).join(", ") : label(effective);
    return escapeMarkdown(text);
  }
  if (member.type === "entity_ref" || member.type === "entity_ref_list") {
    const name = (id: MetadataValue): string => resolveTitle?.(String(id)) ?? String(id);
    const text = Array.isArray(effective) ? effective.map(name).join(", ") : name(effective);
    return escapeMarkdown(text);
  }
  if (Array.isArray(effective)) return escapeMarkdown(effective.map((v) => String(v)).join(", "));
  return escapeMarkdown(String(effective));
}

/** One item rendered whole (§6: additions, removals, an edited item's title
 *  line): its escaped title in bold, then each non-empty visible member other
 *  than the title member, under its escaped name — a `long_text` member as
 *  its own markdown (unescaped: it is already prose, and escaping it would
 *  turn the writer's own formatting into literal asterisks), any other
 *  member as its escaped display text. Blank lines separate the blocks so
 *  each renders as its own markdown block. A scalar list's item is its title
 *  alone — nothing else to show. */
export function itemMarkdown(
  field: MetadataFieldDefinition,
  item: MetadataValue,
  index: number,
  resolveTitle?: (id: string) => string | null,
): string {
  const blocks = [`**${escapeMarkdown(itemTitle(field, item, index))}**`];
  if (!field.item_scalar) {
    const record = itemRecord(field, item);
    const titleKey = titleMemberKey(field);
    for (const member of visibleItemMembers(field)) {
      if (member.key === titleKey) continue;
      const raw = record[member.key];
      if (isBlankMemberValue(raw)) continue;
      const body =
        member.type === "long_text"
          ? typeof raw === "string"
            ? raw
            : String(raw)
          : memberDisplayText(member, raw, resolveTitle);
      blocks.push(`*${escapeMarkdown(member.name || member.key)}*\n\n${body}`);
    }
  }
  return blocks.join("\n\n");
}

/** The order unit's two stacked blocks (§6): a numbered list of escaped
 *  titles, one number per item, in the order given. */
export function orderMarkdown(titles: string[]): string {
  return titles.map((title, index) => `${index + 1}. ${escapeMarkdown(title)}`).join("\n");
}
