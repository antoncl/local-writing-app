// Lift the prompt roster to grouping-ready nodes for the Prompts pane, bucketed
// by DISPOSITION instead of leaf entry_type. A prompt's sub-type is an authoring
// detail; what a writer recognises is what the prompt DOES to the document — its
// disposition (ADR-0054 §1/§2): where the output lands, and whether it commits a
// reviewable patch. There are only five, so grouping on it collapses the
// one-prompt-per-sub-type clutter into five meaningful shelves (#951).
//
// `disposition` is DERIVED at render from the entry_type's context_strategy
// (effectiveOutputKind + promptDeclaresCommit), never stored — the same pattern
// as chatNodes' `seed_committing` and the Assistants default's `listed`. It goes
// in `metadata` so the prompt default view's `group_by: [{ field: "disposition" }]`
// can bucket on it through ordinary field access.

import type { EntryMetadata, MetadataSchema, PromptEntrySummary } from "@/lib/types";
import type { EvalNode } from "@/lib/views/evaluateView";
import {
  effectiveOutputKind,
  promptDeclaresCommit,
  type PromptResolutionContext,
} from "@/lib/editor-core/promptResolution";

// The metadata key the prompt default view groups on (evaluateView.ts +
// _default_view_spec must name the same key).
export const DISPOSITION_FIELD = "disposition";

// The five writer-facing dispositions, in shelf order. The label IS the bucket
// value: segmentForField labels a plain (non-option, non-reference) field bucket
// by its raw value, so no schema field or option map is needed. `rank` fixes the
// shelf order — the default view groups with no `order` (first-seen), and the lift
// below pre-clusters the roster by rank so first-seen == this order.
type Disposition = { readonly label: string; readonly rank: number };
const CONTINUE: Disposition = { label: "Continue", rank: 0 };
const REVISE_PROSE: Disposition = { label: "Revise prose", rank: 1 };
const CHAT: Disposition = { label: "Chat", rank: 2 };
const REVISE_ENTITIES: Disposition = { label: "Revise entities", rank: 3 };
const SNIPPETS: Disposition = { label: "Snippets", rank: 4 };

// Which shelf a prompt lands on, from its type's disposition (ADR-0054 §1/§2):
//   append_to_body → Continue · replace_selection → Revise prose ·
//   chat_panel + commit → Revise entities · chat_panel alone → Chat.
// No output kind means the prompt declares no invocation contract — which is the
// definition of a snippet (decisions-prompt-model) — so it, and any misconfigured
// concrete type (which likewise can't be invoked), shelves under Snippets.
export function dispositionFor(ctx: PromptResolutionContext, entry: PromptEntrySummary): Disposition {
  switch (effectiveOutputKind(ctx, entry)) {
    case "append_to_body":
      return CONTINUE;
    case "replace_selection":
      return REVISE_PROSE;
    case "chat_panel":
      return promptDeclaresCommit(ctx, entry) ? REVISE_ENTITIES : CHAT;
    default:
      return SNIPPETS;
  }
}

export type PromptGroupNode = PromptEntrySummary & EvalNode & { metadata: EntryMetadata };

// The Prompts pane's view universe: each roster summary with its disposition label
// stamped in `metadata`, clustered by disposition rank. The sort is stable, so a
// shelf keeps the caller's intra-shelf order (the roster arrives title-sorted today);
// it only guarantees shelves appear in rank order, which the default view's
// first-seen grouping then renders.
export function promptSummariesToGroupNodes(
  entries: PromptEntrySummary[],
  schema: MetadataSchema | null,
): PromptGroupNode[] {
  // effectiveOutputKind / promptDeclaresCommit read only ctx.metadataSchema; the
  // rest satisfy the type.
  const ctx: PromptResolutionContext = {
    metadataSchema: schema,
    promptEntries: entries,
    loreEntries: [],
    availableScenes: [],
  };
  return entries
    .map((entry) => ({ entry, disp: dispositionFor(ctx, entry) }))
    .sort((a, b) => a.disp.rank - b.disp.rank)
    .map(({ entry, disp }) => ({
      ...entry,
      metadata: { ...entry.metadata, [DISPOSITION_FIELD]: disp.label },
    }));
}
