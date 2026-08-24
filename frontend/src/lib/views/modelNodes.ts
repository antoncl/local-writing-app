// Lift a provider's model catalogue to EvalNodes for the assistant model
// picker (ADR-0073 S3). A model is an external, ephemeral catalogue row — not a
// project node — so this mirrors the Chats-pane lift (`chatSummariesToEvalNodes`):
// each `AIModelInfo` becomes a real EvalNode by placing its filter/group/badge
// facets in `metadata`, and the picker renders it through the app's own View
// machinery (`ViewNodeList`/`evaluateView`) instead of a bespoke <select>. The
// `evaluateView` engine is a pure function of `(spec, supplied nodes)`, so no
// project node-index, persistence, or API is involved.

import type { AIModelInfo, MetadataSchema, ViewSpec } from "@/lib/types";
import type { EvalNode } from "@/lib/views/evaluateView";
import { kindUniverseExpr } from "@/lib/views/evaluateView";

// The synthetic kind + root FQN the model universe carries. `descendants_of` is
// seed-inclusive (it seeds the family with the root FQN itself), so lifting each
// model to this exact entry_type makes the roster match WITHOUT a schema — the
// same schema-less path the Chats built-ins lean on (`chat:base`). There is no
// backend `ai_model` schema; the picker's universe is supplied in-memory.
export const MODEL_KIND = "ai_model";
export const MODEL_ENTRY_TYPE = `${MODEL_KIND}:base`;

// Metadata keys the fixed view groups/filters on. `family` drives the grouping;
// the rest ride along for badges and possible future facet params (ADR-0073
// leaves the exact facet set to implementation).
export const MODEL_FAMILY_FIELD = "family";
export const MODEL_TIER_FIELD = "tier";
export const MODEL_FREE_FIELD = "free";

export type ModelEvalNode = AIModelInfo &
  EvalNode & {
    entry_type: typeof MODEL_ENTRY_TYPE;
    metadata: {
      family: string;
      tier: string;
      free: boolean;
      capabilities: string[];
      context: number;
      price: number | null;
    };
  };

// Lift the catalogue to grouped/faceted EvalNodes. `title` = the model's display
// name (what the row shows); `id` carries through as the node identity the
// picker emits on click. Facets go in `metadata`, where field access reads them
// (ADR-0029 §D), so the fixed view can group by `family`.
export function modelInfoToEvalNodes(models: readonly AIModelInfo[]): ModelEvalNode[] {
  return models.map((m) => ({
    ...m,
    entry_type: MODEL_ENTRY_TYPE,
    title: m.display_name,
    metadata: {
      [MODEL_FAMILY_FIELD]: m.family,
      [MODEL_TIER_FIELD]: m.tier,
      [MODEL_FREE_FIELD]: m.free,
      capabilities: m.capabilities,
      context: m.context_window,
      price: m.cost_in_per_mtok ?? null,
    },
  }));
}

// The fixed, read-only view the picker renders through: the whole model roster
// in catalogue order, grouped by family (alphabetical group labels). A fixed
// built-in spec, exactly like the Chats/Prompts defaults — the view designer is
// not exposed for the model list (ADR-0073 anti-goal). The roster comes from
// `kindUniverseExpr` (not a hardcoded FQN) so it resolves the `ai_model:base`
// root the same way every other built-in resolves its kind root.
export function modelPickerView(schema?: MetadataSchema | null): ViewSpec {
  return {
    kind: MODEL_KIND,
    expr: kindUniverseExpr(MODEL_KIND, schema),
    sort: { by: "manual" },
    group_by: [{ field: MODEL_FAMILY_FIELD, order: "label" }],
  };
}
