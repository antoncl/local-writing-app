// Lift the chat roster to EvalNodes for the Chats pane and the view designer
// preview. A `ChatSessionSummary` becomes a real EvalNode by placing its
// non-intrinsic fields in `metadata`, where field access reads them (ADR-0029
// §D): `subject` (what the chat is about) and `seed_committing` (whether the
// prompt that seeded it declares a `commit` — i.e. it is a brainstorm, ADR-0054).
//
// `seed_committing` is **derived at render, never stored** — it is a pure
// function of the `prompt_entry_id` the chat already carries, resolved through
// the prompt roster. That keeps ADR-0051 §3 intact (no stored conversation-type
// facet): the seeding prompt distinguishes a brainstorm chat from a normal one,
// and this just makes that distinction filterable without persisting anything.
// Since a brainstorm and a plain chat now share the `chat_panel` disposition
// (ADR-0054 S2), it is the `commit`, not the kind, that tells them apart.

import type { ChatSessionSummary, MetadataSchema, PromptEntrySummary } from "@/lib/types";
import type { EvalNode } from "@/lib/views/evaluateView";
import { promptDeclaresCommit, type PromptResolutionContext } from "@/lib/editor-core/promptResolution";

// The metadata key the "Openable chats" built-in view filters on, and the marker
// value stamped on a committing (brainstorm) chat — a non-committing chat gets "".
export const SEED_COMMITTING_FIELD = "seed_committing";
export const SEED_COMMITTING_MARKER = "commit";

export type ChatEvalNode = ChatSessionSummary &
  EvalNode & { metadata: { subject: string; seed_committing: string } };

export function chatSummariesToEvalNodes(
  sessions: ChatSessionSummary[],
  promptEntries: PromptEntrySummary[],
  schema: MetadataSchema | null,
): ChatEvalNode[] {
  // promptDeclaresCommit only reads ctx.metadataSchema; the rest satisfy the type.
  const ctx: PromptResolutionContext = {
    metadataSchema: schema,
    promptEntries,
    loreEntries: [],
    availableScenes: [],
  };
  const byId = new Map(promptEntries.map((entry) => [entry.id, entry]));
  return sessions.map((session): ChatEvalNode => {
    const prompt = session.prompt_entry_id ? byId.get(session.prompt_entry_id) : undefined;
    // Unresolved (freeform, or a prompt with no commit) → "", which the blacklist
    // treats as openable — the safe default.
    const seed = prompt && promptDeclaresCommit(ctx, prompt) ? SEED_COMMITTING_MARKER : "";
    // Computed key ties the written metadata key to the same constant the
    // Openable view's predicate reads — the type below must stay a literal (TS),
    // but the runtime key can't drift from the filter.
    return { ...session, metadata: { subject: session.subject ?? "", [SEED_COMMITTING_FIELD]: seed } };
  });
}
