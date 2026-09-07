// Node-picker config wire types. Extracted from types.ts to keep that barrel
// under the file-size cap; re-exported from `@/lib/types` so it stays the
// single import surface.

import type { ViewSource } from "./viewTypes";

// Shape carried in PromptInputDefinition.target when type === "context_pick",
// and in entity_ref fields' `picker_config`. Split into membership (`sources`:
// one ViewSpec-or-ref per kind, unioned) and mechanics (ADR-0023). Read the
// legacy `{kinds, entryTypes}` subset via `pickerMembership()` in
// lib/utils/pickerSources.ts — there is no evaluator in 0.5.0 step 1.
export type NodePickerConfig = {
  sources?: ViewSource[];
  presets?: ("full_outline" | "full_text")[];
  multiple?: boolean;
  // When true, the runtime picker shows a ★ toggle on each picked
  // scene chip. The author opts in per input — it tells template code
  // that `scene` may be bound to one of the picked scenes. Single ★ per
  // input is enforced by the picker UI.
  allow_target_marking?: boolean;
  // ADR-0082 §2: offer "Create ‹x›" when the typed name resolves to no
  // candidate. Permitted only when `sources` resolves to exactly one
  // concrete entry type.
  create_missing?: boolean;
};

// What ends up in inputs.<name> for a context_pick input — a list of
// these light refs. Bodies are NOT carried; they're materialized
// server-side at template render time. `target: true` on a scene
// ref marks it as the implicit `scene` binding for the prompt's
// template (NC-style ★ target). Only one ref per input can be the
// target; the picker UI enforces single-selection.
//
// A ref is one of two things (ADR-0074): a concrete MEMBER pick
// (kind manuscript/lore/…, resolved directly by the backend), or a
// SELECTOR (kind "tag"/"view") that carries a `selector` ViewSource
// expanded frontend-side to its current members at invocation
// (ADR-0025/Amendment 1 — no backend evaluator). A selector never
// reaches the wire unexpanded.
export type NodePickerRef = {
  id: string;
  kind: "manuscript" | "lore" | "snippet" | "assistant" | "research" | "plot" | "preset" | "tag" | "view";
  title: string;
  entry_type?: string;
  target?: boolean;
  // Present only on a selector ref (kind "tag"/"view"): the ViewSource
  // whose evaluation yields the selector's live members. Slice 5 stores
  // the resolved ViewSpec inline so expansion is self-contained (roster +
  // evaluateView), not dependent on a cross-surface view load.
  selector?: ViewSource;
};
