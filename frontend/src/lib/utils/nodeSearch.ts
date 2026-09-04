// A generic search filter for ViewNodeList consumers (#1816). A pane opts into
// the ViewNodeList search box by passing `searchPlaceholder` + a `filter`; this
// is the shared default filter so panes don't each re-implement one. It matches
// a query against a node's title, its aliases, and the TITLES of the tag nodes
// it references — reusing the query semantics in `entrySearch.ts` (the `#`
// tag-restrictor included), so every surface agrees on what a query means.
//
// It is field-AGNOSTIC about tags: since ADR-0082 a node's tags are tag nodes
// referenced by id somewhere in its metadata (`tags`, `assistant_tags`, or any
// future tag-ref field), so a node's tags are every metadata id the tag roster
// knows — non-tag refs aren't in the roster and drop out. That is what lets one
// filter serve the Assistants pane (`assistant_tags`) and any other kind without
// naming a field. A pane that needs broader or narrower matching (e.g. Lore's
// title + body + all-metadata plain match) passes its own `filter` instead.
import { matchesEntry, parseSearchQuery, readAliases } from "@/lib/utils/entrySearch";

interface SearchableNode {
  title?: string | null;
  metadata?: Record<string, unknown> | null;
}

/** Coerce one metadata field value to the id strings it may carry: a scalar ref
 *  id, an array of ids, or an array of member records keyed by `id`. */
function idsIn(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (!Array.isArray(value)) return [];
  const ids: string[] = [];
  for (const item of value) {
    if (typeof item === "string") ids.push(item);
    else if (item && typeof item === "object" && typeof (item as { id?: unknown }).id === "string") {
      ids.push((item as { id: string }).id);
    }
  }
  return ids;
}

/** Every tag-node title a node carries: scan its metadata for ids the tag roster
 *  knows and resolve each to its current title. Field-agnostic (ADR-0082). */
export function nodeTagTitles(
  metadata: Record<string, unknown> | null | undefined,
  tagTitleById: ReadonlyMap<string, string>,
): string[] {
  if (!metadata) return [];
  const titles: string[] = [];
  for (const value of Object.values(metadata)) {
    for (const id of idsIn(value)) {
      const title = tagTitleById.get(id);
      if (title) titles.push(title);
    }
  }
  return titles;
}

/** Build a ViewNodeList `filter` matching title + aliases + tag-node titles.
 *  `tagTitleById` is read once when the filter is built; rebuild it (e.g. via a
 *  `$derived`) when the tag roster changes so a rename reflects in search. */
export function makeNodeSearchFilter(
  tagTitleById: ReadonlyMap<string, string>,
): (node: SearchableNode, query: string) => boolean {
  return (node, query) =>
    matchesEntry(
      {
        title: node.title ?? "",
        tags: nodeTagTitles(node.metadata, tagTitleById),
        aliases: readAliases(node.metadata),
      },
      parseSearchQuery(query),
    );
}
