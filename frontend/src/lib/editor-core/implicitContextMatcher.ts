// Regex-OR matcher for implicit-context detection (the in-editor variant
// of backend helpers.py:_alias_match). Per the perf benchmark at
// frontend/benchmarks/results.md, regex-OR beats Aho-Corasick by 2.6–4×
// at our scale; both implementations agree on hit positions.
//
// Word boundaries treat apostrophe as a word-extension character so
// "Bob" does not match inside "Bob's" (avoids common false positives in
// English possessives). Single matcher compiled per lore-set change,
// reused for every scan.

import type { LoreEntrySummary, MetadataSchema } from "@/lib/types";
import { resolveColor } from "@/lib/utils/colors";

export type MatchHit = {
  start: number;
  end: number;
  entryId: string;
  matchedText: string;
};

export type MatcherEntry = {
  id: string;
  title: string;
  preview: string;
  entryType: string;
  /** Resolved hex (instance → type → kind-default → null) for inline
   *  decoration coloring. Null when nothing resolves; CSS falls back. */
  colorHex: string | null;
};

/** Result of a compile: the matcher + a lookup table for hover content. */
export type CompiledMatcher = {
  scan(text: string): MatchHit[];
  lookup: Map<string, MatcherEntry>;
  isEmpty: boolean;
};

const RE_ESCAPE = /[.*+?^${}()|[\]\\]/g;
function escapeRegex(s: string): string {
  return s.replace(RE_ESCAPE, "\\$&");
}

/** Pull a string-array field from metadata (lore aliases live here). */
function readAliases(metadata: Record<string, unknown> | undefined): string[] {
  if (!metadata) return [];
  const raw = (metadata as Record<string, unknown>).aliases;
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((x): x is string => typeof x === "string" && x.trim().length > 0)
    .map((s) => s.trim());
}

function buildPreview(body: string, max = 120): string {
  if (!body) return "";
  const collapsed = body.replace(/\s+/g, " ").trim();
  if (collapsed.length <= max) return collapsed;
  return collapsed.slice(0, max - 1) + "…";
}

/** Build a matcher from the current lore set. Returns an empty matcher
 *  when the set is empty (caller can early-exit scans). */
export function compileMatcher(
  entries: LoreEntrySummary[],
  schema: MetadataSchema | null = null,
): CompiledMatcher {
  // Map name (lowercased) → id, sorted by name-length DESC. Length-desc
  // alternation makes the regex pick the longest match at a given start
  // (regex engines' leftmost-longest is contingent on alternation order).
  type NamedRef = { name: string; id: string };
  const refs: NamedRef[] = [];
  const lookup = new Map<string, MatcherEntry>();
  for (const entry of entries) {
    if (!entry.id || !entry.title) continue;
    const instanceColor = typeof entry.metadata?.color === "string" ? entry.metadata.color : null;
    const swatch = resolveColor(instanceColor, entry.entry_type, "lore", schema);
    lookup.set(entry.id, {
      id: entry.id,
      title: entry.title,
      preview: buildPreview(entry.body ?? ""),
      entryType: entry.entry_type ?? "",
      colorHex: swatch?.hex ?? null,
    });
    refs.push({ name: entry.title, id: entry.id });
    for (const alias of readAliases(entry.metadata as Record<string, unknown>)) {
      refs.push({ name: alias, id: entry.id });
    }
  }
  if (refs.length === 0) {
    return {
      scan: () => [],
      lookup,
      isEmpty: true,
    };
  }
  refs.sort((a, b) => b.name.length - a.name.length);

  // Dedup names so the same string doesn't appear twice in the alternation
  // (it'd just waste regex engine work). First-id-wins on collisions.
  const nameToId = new Map<string, string>();
  for (const r of refs) {
    const key = r.name.toLowerCase();
    if (!nameToId.has(key)) nameToId.set(key, r.id);
  }
  const escaped = [...nameToId.keys()].map(escapeRegex);
  // Apostrophe-aware boundaries: (?<![\w']) on the left and (?![\w']) on
  // the right treat ' as a word-character so "Bob" doesn't match in
  // "Bob's". Without these, JS's standard \b breaks inside possessives.
  const src = "(?<![\\w'])(" + escaped.join("|") + ")(?![\\w'])";
  const regex = new RegExp(src, "gi");

  return {
    isEmpty: false,
    lookup,
    scan(text: string): MatchHit[] {
      if (!text) return [];
      const hits: MatchHit[] = [];
      regex.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = regex.exec(text)) !== null) {
        const matched = m[1];
        const id = nameToId.get(matched.toLowerCase());
        if (!id) continue;
        hits.push({
          start: m.index,
          end: m.index + matched.length,
          entryId: id,
          matchedText: matched,
        });
      }
      return hits;
    },
  };
}
