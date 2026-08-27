// Shared search semantics for the node/entry search boxes (ADR-0074 slice 3,
// #1468). Two surfaces search entries — the context picker and the Lore pane —
// and they must agree on what a query *means*, above all the app-wide `#`
// tag-restrictor: `#heist` restricts the match to tags on both. This module is
// the one place that parses a query and matches an entry's tags/aliases, so the
// two surfaces share the convention rather than each re-implementing it.
//
// Field breadth differs by surface and is deliberately NOT unified here: the
// picker matches title + tags + aliases; the Lore pane keeps its broader
// plain-query match (title + body + all metadata) and only borrows the `#`
// branch. What's shared is the *meaning* of a query, not every field it scans.

import { splitCommaList } from "@/lib/utils/tags";

export interface ParsedSearch {
  /** The search text, lower-cased and trimmed; empty means "no active filter". */
  needle: string;
  /** True when the query led with `#` — restrict the match to tags. */
  tagOnly: boolean;
}

/** Parse a raw search-box value. A leading `#` is the tag-restrictor. */
export function parseSearchQuery(raw: string | null | undefined): ParsedSearch {
  const trimmed = (raw ?? "").trim();
  if (trimmed.startsWith("#")) {
    return { needle: trimmed.slice(1).trim().toLowerCase(), tagOnly: true };
  }
  return { needle: trimmed.toLowerCase(), tagOnly: false };
}

/** Whether the box holds an active query (a bare `#` still counts as typing). */
export function isSearchActive(raw: string | null | undefined): boolean {
  return (raw ?? "").trim().length > 0;
}

type LooseMetadata = Record<string, unknown> | null | undefined;

/** Read a tags metadata field — a string[] or a comma-joined string. */
export function readTags(metadata: LooseMetadata): string[] {
  const raw = metadata?.tags;
  if (Array.isArray(raw)) return raw.map((t) => String(t).trim()).filter(Boolean);
  if (typeof raw === "string") return splitCommaList(raw);
  return [];
}

/** Read lore aliases — a string[] under `metadata.aliases`. Aliases are a lore
 * convention; other kinds return []. */
export function readAliases(metadata: LooseMetadata): string[] {
  const raw = metadata?.aliases;
  if (!Array.isArray(raw)) return [];
  return raw.map((a) => String(a).trim()).filter(Boolean);
}

export interface SearchFields {
  title: string;
  tags?: string[];
  aliases?: string[];
}

/** Does a candidate match the parsed query?
 *  - empty needle → matches (no active filter)
 *  - `#…` (tagOnly) → any tag contains the needle
 *  - plain → title | tags | aliases contains the needle
 *  All comparisons are case-insensitive; `parsed.needle` is already lower-cased. */
export function matchesEntry(fields: SearchFields, parsed: ParsedSearch): boolean {
  const { needle, tagOnly } = parsed;
  if (!needle) return true;
  const tagHit = (fields.tags ?? []).some((t) => t.toLowerCase().includes(needle));
  if (tagOnly) return tagHit;
  return (
    fields.title.toLowerCase().includes(needle) ||
    tagHit ||
    (fields.aliases ?? []).some((a) => a.toLowerCase().includes(needle))
  );
}
