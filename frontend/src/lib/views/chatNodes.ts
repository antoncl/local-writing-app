// Lift the chat roster to EvalNodes for the Chats pane and the view designer
// preview. A `ChatSessionSummary` becomes a real EvalNode by placing its
// non-intrinsic fields in `metadata`, where field access reads them (ADR-0029
// §D): `subject` (what the chat is about) and `seed_disposition` (the disposition
// of the prompt that seeded it — "Chat" for a plain chat, "Revise entities" for a
// brainstorm, ADR-0054).
//
// `seed_disposition` is **derived at render, never stored** — it is a pure
// function of the `prompt_entry_id` the chat already carries, resolved through the
// prompt roster to the seed's disposition label. That keeps ADR-0051 §3 intact (no
// stored conversation-type facet): the seeding prompt distinguishes a brainstorm
// chat from a normal one, and this just makes that distinction filterable without
// persisting anything. It reuses the Prompts shelf's disposition vocabulary
// (`dispositionFor`) so a writer sees one set of labels across both panes (#960).

import type {
  ChatSessionSummary,
  MetadataFieldDefinition,
  MetadataSchema,
  PromptEntrySummary,
} from "@/lib/types";
import type { EvalNode } from "@/lib/views/evaluateView";
import type { PromptResolutionContext } from "@/lib/editor-core/promptResolution";
import {
  CHAT_DISPOSITION_LABEL,
  dispositionFor,
  REVISE_ENTITIES_DISPOSITION_LABEL,
} from "@/lib/views/promptNodes";

// The metadata key the "Openable chats" built-in view filters on — the seed
// prompt's disposition label, or "" for a freeform/unresolved chat.
export const SEED_DISPOSITION_FIELD = "seed_disposition";

// `seed_disposition` as a computed field the view designer offers (computedFields
// registry). Chats are seeded only by conversation prompts, so the reachable values
// are exactly the two conversation dispositions; a freeform/deleted-seed chat carries
// "" and simply matches neither. The lift stamps the value; this declares the field
// exists and its choices so the filter picker can select it.
export function seedDispositionFieldDef(): MetadataFieldDefinition {
  return {
    name: "Seeded by",
    type: "select",
    category: "computed",
    options: [{ value: CHAT_DISPOSITION_LABEL }, { value: REVISE_ENTITIES_DISPOSITION_LABEL }],
  };
}

export type ChatEvalNode = ChatSessionSummary &
  EvalNode & { metadata: { subject: string; seed_disposition: string } };

export function chatSummariesToEvalNodes(
  sessions: ChatSessionSummary[],
  promptEntries: PromptEntrySummary[],
  schema: MetadataSchema | null,
): ChatEvalNode[] {
  // dispositionFor reads only ctx.metadataSchema; the rest satisfy the type.
  const ctx: PromptResolutionContext = {
    metadataSchema: schema,
    promptEntries,
    loreEntries: [],
    availableScenes: [],
  };
  const byId = new Map(promptEntries.map((entry) => [entry.id, entry]));
  return sessions.map((session): ChatEvalNode => {
    const prompt = session.prompt_entry_id ? byId.get(session.prompt_entry_id) : undefined;
    // No resolved seed (freeform, or a deleted prompt) → "", which the "Openable
    // chats" blacklist treats as openable — the safe default.
    const seed = prompt ? dispositionFor(ctx, prompt).label : "";
    // Computed key ties the written metadata key to the same constant the Openable
    // view's predicate reads — the type above must stay a literal (TS), but the
    // runtime key can't drift from the filter.
    return { ...session, metadata: { subject: session.subject ?? "", [SEED_DISPOSITION_FIELD]: seed } };
  });
}
