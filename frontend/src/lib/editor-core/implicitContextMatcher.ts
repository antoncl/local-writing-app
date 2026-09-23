// Regex-OR matcher for implicit-context detection (the in-editor variant
// of the backend's `name_matcher.py`). Per the perf benchmark at
// frontend/benchmarks/results.md, regex-OR beats Aho-Corasick by 2.6–4×
// at our scale; both implementations agree on hit positions.
//
// ADR-0075 §3: the boundary is the explicit ASCII class `[A-Za-z0-9_']`
// (not `\w`, which is ASCII-only in JS but Unicode in Python — the two
// engines would diverge on non-ASCII input) with an optional trailing
// possessive/enclitic (`'ll`/`'re`/`'ve`/`'s`/`'d`/`'`)
// consumed but excluded from the reported hit — so "Bob's" detects "Bob"
// while "O'Brien" still does not yield "Brien" (the apostrophe is inside
// the token, not a trailing clitic). Single matcher compiled per lore-set
// change, reused for every scan.

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
export function escapeRegex(s: string): string {
  return s.replace(RE_ESCAPE, "\\$&");
}

const SEPARATOR_RE = /[\s-]+/;
const SEPARATOR_RE_G = /[\s-]+/g;
const CLITIC = "(?:'ll|'re|'ve|'s|'d|')?";
const BOUNDARY_LEFT = "(?<![A-Za-z0-9_'])";
const BOUNDARY_RIGHT = "(?![A-Za-z0-9_'])";

// #2142 / ADR-0075 §3: an underscore run at a word edge (markdown emphasis,
// `_The Implant_` / `__strong__`) vs. an intra-word one (`snake_case`, an id)
// — see `maskEmphasisUnderscores` below.
const UNDERSCORE_RUN_RE = /_+/g;
const WORD_EDGE_RE = /[A-Za-z0-9]/;

/**
 * Replace every markdown-emphasis underscore in `text` with a space, same
 * length in, same length out (#2142) — mirrors the backend's
 * `mask_emphasis_underscores` (`name_matcher.py`) so the two ADR-0075
 * implementations stay level on every surface; this one scans raw markdown
 * text too (the editor's chat composer / prose surface), same as the
 * backend's raw-markdown scans.
 *
 * The boundary this matcher scans against is the explicit ASCII
 * `[A-Za-z0-9_']` (§3, unchanged by this), so `_The Implant_` has no
 * boundary before `T` or after `t` and never matches without masking first
 * — only the text handed to `scan` changes, at scan time.
 *
 * A run of one or more underscores is a delimiter — and masked to spaces —
 * when it sits at a word edge: preceded by start-of-text / whitespace /
 * punctuation and followed by `[A-Za-z0-9]` (an *opening* delimiter), or
 * preceded by `[A-Za-z0-9]` and followed by end-of-text / whitespace /
 * punctuation (a *closing* one); `__strong__`'s two-underscore runs count
 * the same way, by their outer edges. A run with a word character on BOTH
 * sides is intra-word — `snake_case`, an id — and is left alone; a run with
 * neither side touching a word character (an isolated `_` between
 * punctuation/whitespace) is left alone too, since it opens or closes
 * nothing.
 */
export function maskEmphasisUnderscores(text: string): string {
  if (!text) return text;
  let chars: string[] | null = null;
  UNDERSCORE_RUN_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = UNDERSCORE_RUN_RE.exec(text)) !== null) {
    const start = m.index;
    const end = start + m[0].length;
    const before = start > 0 ? text[start - 1] : "";
    const after = end < text.length ? text[end] : "";
    const beforeIsWord = before !== "" && WORD_EDGE_RE.test(before);
    const afterIsWord = after !== "" && WORD_EDGE_RE.test(after);
    if (beforeIsWord && afterIsWord) continue; // intra-word — not a delimiter
    if (!beforeIsWord && !afterIsWord) continue; // opens/closes nothing
    if (chars === null) chars = text.split("");
    for (let i = start; i < end; i++) chars[i] = " ";
  }
  return chars === null ? text : chars.join("");
}

/** Collapse space/hyphen runs to a single ASCII space, trim, lowercase — the
 *  shared dedup/lookup key (§3 rule 4). Matched text can now differ from the
 *  stored name (hyphen vs space), so id resolution can no longer key on raw
 *  matched text. */
function norm(s: string): string {
  return s.replace(SEPARATOR_RE_G, " ").trim().toLowerCase();
}

/** Split on `[\s-]+`, escape each token, rejoin with `[\s-]+` so space and
 *  hyphen are interchangeable in the compiled fragment (§3 rule 4);
 *  single-word names are unchanged. */
function buildFragment(name: string): string {
  const tokens = name.split(SEPARATOR_RE).filter((t) => t.length > 0);
  return tokens.map(escapeRegex).join("[\\s\\-]+").toLowerCase();
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
 *  when the set is empty (caller can early-exit scans).
 *
 *  `effectiveNames` (#61), when given, overrides an entry's matched name-set
 *  with its effective title + aliases as of a resolution scene — so a renamed
 *  entity is detected under its as-of-scene name in that scene's prose. The
 *  hover `lookup` still uses base title/preview/color (the card content). Entries
 *  absent from the map fall back to their base names. */
export function compileMatcher(
  entries: LoreEntrySummary[],
  schema: MetadataSchema | null = null,
  effectiveNames: Record<string, string[]> | null = null,
): CompiledMatcher {
  // Map norm(name) → id, sorted by (-length, norm(name), id) — a total order
  // independent of input order. Length-desc alternation makes the regex pick
  // the longest match at a given start (regex engines' leftmost-longest is
  // contingent on alternation order); the norm/id tie-break makes equal-length
  // collisions resolve identically on both sides regardless of entity-list
  // order (§3; the F1 fix).
  type NamedRef = { name: string; id: string };
  const refs: NamedRef[] = [];
  const lookup = new Map<string, MatcherEntry>();
  for (const entry of entries) {
    if (!entry.id || !entry.title) continue;
    // ADR-0075 §7 / slice 4: the highlight is a promise the entity will be in
    // the model's context, so it must not decorate entities the backend keeps
    // OUT of context — skip `never`/`manual_only`. `auto` (detected when named)
    // and `always` (always-included via `_always_included_lore_ids`) both DO
    // reach context, so both stay highlighted; unset defaults to `auto`. (This
    // is broader than the name-matcher's auto-only filter on purpose: `always`
    // reaches context by a different path, so highlighting it is a true promise.)
    const policy = entry.metadata?.context_policy;
    if (policy === "never" || policy === "manual_only") continue;
    const instanceColor = typeof entry.metadata?.color === "string" ? entry.metadata.color : null;
    const swatch = resolveColor(instanceColor, entry.entry_type, "lore", schema);
    lookup.set(entry.id, {
      id: entry.id,
      title: entry.title,
      preview: buildPreview(entry.body ?? ""),
      entryType: entry.entry_type ?? "",
      colorHex: swatch?.hex ?? null,
    });
    const effective = effectiveNames?.[entry.id];
    if (effective && effective.length > 0) {
      for (const name of effective) {
        if (name && name.trim()) refs.push({ name: name.trim(), id: entry.id });
      }
      continue;
    }
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
  refs.sort((a, b) => {
    if (b.name.length !== a.name.length) return b.name.length - a.name.length;
    const an = norm(a.name);
    const bn = norm(b.name);
    if (an !== bn) return an < bn ? -1 : 1;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });

  // Dedup by norm(name) so the same string doesn't appear twice in the
  // alternation (it'd just waste regex engine work). First-id-wins on
  // collisions, over the deterministic sort above.
  const nameToId = new Map<string, string>();
  const fragments: string[] = [];
  for (const r of refs) {
    const key = norm(r.name);
    if (nameToId.has(key)) continue;
    nameToId.set(key, r.id);
    fragments.push(buildFragment(r.name));
  }
  // ADR-0075 §3: explicit ASCII boundary (not \w, which is Unicode) with an
  // optional trailing possessive/enclitic consumed but excluded from the
  // capture group — "Bob's" detects "Bob"; "O'Brien" still does not yield
  // "Brien" (its apostrophe is inside the token, not a trailing clitic).
  const src = BOUNDARY_LEFT + "(" + fragments.join("|") + ")" + CLITIC + BOUNDARY_RIGHT;
  const regex = new RegExp(src, "gi");

  return {
    isEmpty: false,
    lookup,
    scan(text: string): MatchHit[] {
      if (!text) return [];
      // #2142: scan `maskEmphasisUnderscores(text)`, not `text` — same length,
      // so positions still address the original; `matchedText` is read back
      // from `text` too (masking never touches a capture group's own span,
      // only the underscores flanking it).
      const scanText = maskEmphasisUnderscores(text);
      const hits: MatchHit[] = [];
      regex.lastIndex = 0;
      let m: RegExpExecArray | null;
      while ((m = regex.exec(scanText)) !== null) {
        const start = m.index;
        const end = start + m[1].length;
        const matched = text.slice(start, end);
        const id = nameToId.get(norm(matched));
        if (!id) continue;
        hits.push({ start, end, entryId: id, matchedText: matched });
      }
      return hits;
    },
  };
}
