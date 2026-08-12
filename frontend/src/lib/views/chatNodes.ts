// Lift the chat roster to EvalNodes for the Chats pane and the view designer
// preview. A `ChatSessionSummary` becomes a real EvalNode by placing its
// non-intrinsic fields in `metadata`, where field access reads them (ADR-0029
// §D): `subject` (what the chat is about) and `seed_output_kind` (the output
// kind of the prompt that seeded it — `chat_panel`, `entry_patch`, …).
//
// `seed_output_kind` is **derived at render, never stored** — it is a pure
// function of the `prompt_entry_id` the chat already carries, resolved through
// the prompt roster. That keeps ADR-0051 §3 intact (no stored conversation-type
// facet): the seeding prompt distinguishes a brainstorm chat from a normal one,
// and this just makes that distinction filterable without persisting anything.

import type { ChatSessionSummary, MetadataSchema, PromptEntrySummary } from "@/lib/types";
import type { EvalNode } from "@/lib/views/evaluateView";
import { effectiveOutputKind, type PromptResolutionContext } from "@/lib/editor-core/promptResolution";

// The metadata key the "Openable chats" built-in view filters on.
export const SEED_OUTPUT_KIND_FIELD = "seed_output_kind";

export type ChatEvalNode = ChatSessionSummary &
  EvalNode & { metadata: { subject: string; seed_output_kind: string } };

export function chatSummariesToEvalNodes(
  sessions: ChatSessionSummary[],
  promptEntries: PromptEntrySummary[],
  schema: MetadataSchema | null,
): ChatEvalNode[] {
  // effectiveOutputKind only reads ctx.metadataSchema; the rest satisfy the type.
  const ctx: PromptResolutionContext = {
    metadataSchema: schema,
    promptEntries,
    loreEntries: [],
    availableScenes: [],
  };
  const byId = new Map(promptEntries.map((entry) => [entry.id, entry]));
  return sessions.map((session): ChatEvalNode => {
    const prompt = session.prompt_entry_id ? byId.get(session.prompt_entry_id) : undefined;
    // Unresolved (freeform, or a prompt whose output kind can't be read) → "",
    // which the blacklist treats as openable — the safe default.
    const seed = prompt ? effectiveOutputKind(ctx, prompt) ?? "" : "";
    // Computed key ties the written metadata key to the same constant the
    // Openable view's predicate reads — the type below must stay a literal (TS),
    // but the runtime key can't drift from the filter.
    return { ...session, metadata: { subject: session.subject ?? "", [SEED_OUTPUT_KIND_FIELD]: seed } };
  });
}
