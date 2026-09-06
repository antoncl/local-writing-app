// Kind label + ordering, seeded from `offerOnTree.ts` (#1844 / ADR-0085 §2 —
// the Search pane's kind grouping needed the same rule and this is the one
// home for it now). No general kind→label table spans every kind here
// (assistant/chat/view/project included) — the existing ones (SCHEMA_KIND_META,
// NodePickerConfigEditor's KINDS) are narrower, purpose-built lists — so this
// stays a plain, deterministic fallback.

// Kinds in fixed render order first; any kind not listed here (a new schema
// kind, or one of the wider "editor" set like assistant/chat/view/project) is
// appended alphabetically by `orderKinds` below.
export const KIND_ORDER = ["lore", "manuscript", "plot", "research", "prompt"];

// Title-case a raw kind for a section header ("manuscript" → "Manuscript").
export function kindLabel(kind: string): string {
  return kind.length === 0 ? kind : kind[0].toUpperCase() + kind.slice(1);
}

// `kinds`, ordered KIND_ORDER-first, then the rest alphabetically — the rule
// `offerOnTree.ts`'s `orderedEligibleKinds` applied to a schema's eligible
// kinds, generalised to any kind set (e.g. the kinds a Search response's hits
// actually carry).
export function orderKinds(kinds: Iterable<string>): string[] {
  const set = new Set(kinds);
  const known = KIND_ORDER.filter((kind) => set.has(kind));
  const rest = [...set].filter((kind) => !KIND_ORDER.includes(kind)).sort((a, b) => a.localeCompare(b));
  return [...known, ...rest];
}
