// ADR-0078 promotion wire types. Extracted from types.ts to keep that barrel
// under the file-size cap; re-exported from `@/lib/types` so it stays the
// single import surface.

// ADR-0078 §2/§9: a layer a node here may be promoted INTO — a declared
// ancestor project of the open project. `GET /api/promotion/targets` returns
// these outermost-first, so the nearest ancestor (the usual pick) is last.
export type PromotionTarget = {
  layer_id: string;
  label: string;
};

// A field value that will NOT travel with a promoted node — it stays in the
// origin as a layer override because it would leak origin-local structure
// into the destination (ADR-0078 §4).
export type PromotionStayItem = {
  field: string;
  reason: string;
};

// A field an ANCESTOR layer's override will write once the promoted node is
// inherited again (#1857): owned, the node ignored it; promoted, it folds.
export type PromotionFoldItem = {
  field: string;
  // Label of the layer whose override applies.
  layer: string;
  // Title of the cascaded include member it applies to, or null for the
  // promoted node itself.
  node: string | null;
};

// The dry-run preview of a promotion (ADR-0078 §9), returned by both the
// preview and (implicitly) the commit endpoint — the same partition backs
// both, so what the author confirms is what runs.
export type PromotionPlan = {
  destination: PromotionTarget;
  travels: string[];
  stays_in_origin: PromotionStayItem[];
  invisible_at_destination: string[];
  // The include-closure cascaded up with the node (ADR-0078 §6): a prompt's
  // `{% include %}`d snippets, by title. Always empty for lore.
  also_promoted: string[];
  // Dynamic references that travel and re-resolve at the destination rather
  // than move (ADR-0078 §5): a prompt's context_pick/scene_ref inputs, named.
  // Always empty for lore.
  resolves_differently: string[];
  // Non-null when the promotion is REFUSED (ADR-0078 §6, e.g. an unfollowable
  // dynamic include, or a hard-dependency owned by an intermediate ancestor)
  // — the dialogue shows it and disables commit.
  blocked_reason: string | null;
  // Staged mutation sets pinned to a promoted lore node (ADR-0078 §7):
  // surfaced, not cascaded — they keep working from the origin and are
  // promoted separately. Titles; empty unless the node has pinned staged sets.
  related: string[];
  // Fields an ancestor layer's override will write once the node is inherited
  // again (#1857) — the value on screen changes on commit, so the plan says so.
  folds_after_promotion: PromotionFoldItem[];
};
