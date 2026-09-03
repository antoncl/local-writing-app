// The one home for the `split(",").map(trim).filter(Boolean)` idiom (#247/#704):
// a comma-joined value → trimmed, non-empty tokens, order preserved, NO de-dupe.
// Callers that want set semantics layer a de-dupe on top — the policy is not the
// same everywhere (tags de-dupe case-insensitively; collection membership, whose
// items are case-sensitive identifiers, keeps `Alpha`/`alpha` distinct), so the
// split and the de-dupe are separate steps rather than one baked-in helper.
export function splitCommaList(raw: string | null | undefined): string[] {
  if (raw == null || raw === "") return [];
  const out: string[] = [];
  for (const item of String(raw).split(",")) {
    const token = item.trim();
    if (token) out.push(token);
  }
  return out;
}

// De-dupe an already-tokenised list, trimming and dropping empties, first
// occurrence wins. `identity` maps each token to the key set-membership compares
// on — the ONE knob the two set policies differ by (#725):
//   - default (the token itself) → CASE-SENSITIVE: for reference-like lists whose
//     items are identifiers (`entity_ref_list`, collection membership), where
//     `Alpha` and `alpha` are two distinct members;
//   - a lowercasing identity → CASE-INSENSITIVE: for controlled vocabularies
//     (`tags`, `multi_select` options), where case is presentation, not identity.
// A value with duplicates (hand-edited YAML, an importer — pre-1.0 has no
// normalization) must NOT reach a keyed `{#each}`, which throws
// `each_key_duplicate`, NOR be persisted, since a member twice is one member.
export function dedupeList(
  items: string[],
  identity: (token: string) => string = (token) => token,
): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    const token = item.trim();
    if (!token) continue;
    const key = identity(token);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(token);
  }
  return out;
}

// The case-folding identity for controlled vocabularies (tags, multi_select).
export const foldCaseInsensitive = (token: string): string => token.toLowerCase();

// De-dupe under the TAG set policy: case-insensitive, first spelling wins.
export function dedupeTags(tags: string[]): string[] {
  return dedupeList(tags, foldCaseInsensitive);
}

// Canonical parser for a comma-joined tag string → an ordered, de-duplicated
// list (#247). Prefer this over hand-rolling the split + de-dupe.
export function parseTagList(raw: string | null | undefined): string[] {
  return dedupeTags(splitCommaList(raw));
}
