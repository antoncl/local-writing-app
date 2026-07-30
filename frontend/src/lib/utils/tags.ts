import type { ScopedTag } from "@/lib/types";

// Canonical parser for a comma-joined tag string → an ordered, de-duplicated
// list (#247). Tags are a set: the same tag twice is one tag, and a value that
// arrives with exact or case duplicates (hand-edited YAML, an importer, another
// writer — pre-1.0 has no normalization) must NOT reach a keyed `{#each}`, which
// throws `each_key_duplicate`. De-dupe is case-insensitive; the first spelling
// wins. Prefer this over hand-rolling `split(",").map(trim).filter(Boolean)`.
export function parseTagList(raw: string | null | undefined): string[] {
  if (raw == null || raw === "") return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of String(raw).split(",")) {
    const tag = item.trim();
    if (!tag) continue;
    const key = tag.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(tag);
  }
  return out;
}

// The one home for "what colour is this tag?" — a lowercased-name → swatch-id
// map built from the known-tags roster (#247). Every chip render site holds
// `knownTags`, so they map through this rather than re-deriving a `.find()` each.
// A one-off lookup is `tagColorMap(tags).get(name.toLowerCase()) ?? null`.
export function tagColorMap(knownTags: ScopedTag[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const tag of knownTags) {
    if (tag.color) map.set(tag.name.toLowerCase(), tag.color);
  }
  return map;
}
