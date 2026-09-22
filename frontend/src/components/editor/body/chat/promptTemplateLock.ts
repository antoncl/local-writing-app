// First-send template render (#2129, extracted from ChatBodyView's
// renderAndLockPromptTemplate — the source of truth for the shape). Called
// from sendChat right before the first user turn ships, when the chat is
// bound to a prompt that hasn't been rendered yet. After a successful lock the
// preset is locked (the caller assigns the returned system prompt; a
// non-empty one gates re-rendering on every later send).
import { api } from "@/lib/api";
import { resolutionSceneIdFromInputs } from "@/lib/editor-core/promptResolution";
import type { PromptEntrySummary } from "@/lib/types";

export interface PromptTemplateLock {
  systemPrompt: string;
  loreEnabled: boolean;
  usedNodeIds: string[];
  usedNodeHints: Record<string, string>;
  fieldContractStored: Record<string, unknown>[];
  initialTurns: { role: "user" | "assistant"; content: string }[];
}

export type PromptTemplateLockResult =
  | { ok: true; lock: PromptTemplateLock }
  | { ok: false; error: string };

/** Render + lock a prompt template for the chat's first send. `inputs` is the
 * already-coerced+expanded input set (chatInputs.ts' templateInputsFromDrafts);
 * `subject` is the chat's bound subject. Pure — no component state read or
 * written; the caller assigns the six locked fields on success. */
export async function lockPromptTemplate(
  entry: PromptEntrySummary,
  { subject, inputs }: { subject: string; inputs: Record<string, unknown> },
): Promise<PromptTemplateLockResult> {
  try {
    const preview = await api.aiPreview({
      template_source: entry.body,
      // ADR-0051 S5: the chat's scene comes from its subject (backend-derived),
      // not a stored target_scene_id. An explicit scene_ref input still wins.
      target_scene_id: "",
      subject,
      inputs,
      resolution_scene_id: resolutionSceneIdFromInputs(entry, inputs),
      commit: false,
    });
    // Render errors come back as 200 + preview.error from /api/ai/preview
    // (exploratory endpoint). At first-send we DO want to surface them —
    // the user is committing to a model call that won't have a valid prompt.
    if (preview.error) {
      return { ok: false, error: `Couldn't render prompt template: ${preview.error.message}` };
    }
    const messages = preview.messages ?? [];
    const flatten = (blocks: { text: string }[]) => blocks.map((b) => b.text).join("");
    const systemBlocks = messages.filter((m) => m.role === "system").map((m) => flatten(m.blocks));
    const initialTurns = messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role as "user" | "assistant", content: flatten(m.blocks) }));
    return {
      ok: true,
      lock: {
        systemPrompt: systemBlocks.join("\n\n"),
        // ADR-0057 §2: capture the execution-derived lore gate from this lock
        // render. Whether the template actually called relevant_lore() decides
        // whether the send path injects any lore; persisted with the system
        // prompt via the caller's very next persistActiveChat.
        loreEnabled: preview.lore_enabled ?? false,
        usedNodeIds: preview.used_node_ids ?? [],
        usedNodeHints: preview.used_node_hints ?? {},
        fieldContractStored: preview.field_contract_stored ?? [],
        initialTurns,
      },
    };
  } catch (e) {
    return { ok: false, error: `Couldn't render prompt template: ${(e as Error).message}` };
  }
}
