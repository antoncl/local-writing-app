// outputHandlers.ts — the OutputHandler registry (ADR-0065).
//
// A prompt's output is NOT an axis of independent choices. The scan in
// ADR-0065 §Grounding shows `output.kind` is a *discriminator* whose values are
// a few fixed, correlated bundles — and `source` / `review` / `activation` all
// fall out of it. So each output behaviour is one registered handler (the
// ADR-0058 provider idiom: a value registered once, the call on the handler, not
// a scattered branch on the kind). The core looks the handler up and drives it;
// it never re-derives the bundle from the kind.
//
// ── The interface (grounded, not invented) ──────────────────────────────────
// Declarative bundle — the correlated facts a handler *is*:
//   key         the discriminator that replaces output.kind: inline | extract_to_node
//   source      what it reads: scan tokens (inline) | the transcript (extract)
//   review      how the result is reviewed: inline_mark | patch_diff
//   activation  what fires it: inline (slash / selection toolbar) | conversation (＋New)
// Behavioural — the two phases the core drives polymorphically:
//   produce(host)          run the transform → the thing to review (null = the
//                          produce can't proceed, having reported why via `host`).
//                          inline → gather the scan source; extract → the 2nd-pass
//                          extractor (ADR-0063).
//   apply(produced, host)  write it at the destination behind its review. inline →
//                          stream at cursor/selection behind the aiSuggestion mark;
//                          extract → publish the patch for the diff review.
//
// `produce`/`apply` live on the shared generic base `OutputHandler<Host, Produced>`
// — the two handlers have different hosts, so the base is generic over them, and
// each concrete handler binds its own (the ADR's minimality rule is met now that
// two handlers share the exact shape). The host carries the state-bound primitives
// (the streaming controller, the extraction + review publish); the handler is the
// registered dispatch seam.
//
// Slice: S2a registered `inline`; S2b added `extract_to_node` (the brainstorm
// commit) and lifted produce/apply onto the generic base; S3 retired the
// `output.kind` disposition enum for the stored `handler` key this file routes on,
// so `outputHandlerFor` is now a pure registry lookup.

import type { Editor } from "@tiptap/core";
import type {
  AIEntryPatch,
  EditableDocument,
  PromptEntrySummary,
  PromptOutput,
} from "@/lib/types";

export type OutputHandlerKey = "inline" | "extract_to_node";
export type OutputSource = "scan" | "transcript";
export type OutputReview = "inline_mark" | "patch_diff";
export type OutputActivation = "inline" | "conversation";
// Where an inline handler writes. cursor vs selection is a DESTINATION sub-choice
// (was append_to_body vs replace_selection), not two separate handlers (ADR-0065 §3).
export type InlineDestination = "cursor" | "selection";

// How much surrounding prose a revise (selection) sends as context. Lives with
// the gather it parameterises.
export const REVISE_CONTEXT_CHARS = 600;

// The generic base: the declarative bundle every handler IS, plus the two phases
// the core drives. `Host` is the state-bound surface a handler needs (an editor
// streaming controller, a chat's extraction + publish); `Produced` is what
// `produce` yields for review. `produce` may return null to abort (message
// already surfaced via the host).
export interface OutputHandler<Host = unknown, Produced = unknown> {
  readonly key: OutputHandlerKey;
  readonly source: OutputSource;
  readonly review: OutputReview;
  readonly activation: OutputActivation;
  produce(host: Host): Produced | null | Promise<Produced | null>;
  apply(produced: Produced, host: Host): void | Promise<void>;
}

// One invocation's identity, shared by both phases of an inline run.
export interface OutputRun {
  entry: PromptEntrySummary;
  inputs: Record<string, unknown>;
  assistantId: string;
  scene: EditableDocument;
}

// ── inline ──────────────────────────────────────────────────────────────────

// The gathered scan source — `produce`'s output for the inline handler. The
// destination rides along so `apply` (streaming) knows cursor-vs-selection.
export interface InlineGathered {
  destination: InlineDestination;
  from: number;
  to: number;
  textBefore: string;
  textAfter: string;
  selectionText?: string;
}

// What the inline handler needs from its activation surface (the
// AiSuggestionController). `streamInline` is the controller's streaming
// primitive — the stream stays bound to the controller's reactive state (the
// pending mark, accept/revert/retry, telemetry), so `apply` delegates to it.
export interface InlineHost {
  destination: InlineDestination;
  getEditor(): Editor | null;
  setError(message: string, anchor?: number): void;
  streamInline(gathered: InlineGathered): Promise<void>;
}

export const inlineHandler: OutputHandler<InlineHost, InlineGathered> = {
  key: "inline",
  source: "scan",
  review: "inline_mark",
  activation: "inline",

  produce(host) {
    const editor = host.getEditor();
    if (!editor) return null;
    if (host.destination === "selection") {
      const sel = editor.state.selection;
      const from = sel.from;
      const to = sel.to;
      if (from === to) {
        host.setError("Select text to revise.", from);
        return null;
      }
      const selectionText = editor.state.doc.textBetween(from, to, "\n\n", " ");
      if (!selectionText.trim()) {
        host.setError("Select non-empty text to revise.", from);
        return null;
      }
      const docSize = editor.state.doc.content.size;
      const beforeStart = Math.max(0, from - REVISE_CONTEXT_CHARS);
      const afterEnd = Math.min(docSize, to + REVISE_CONTEXT_CHARS);
      const textBefore = editor.state.doc.textBetween(beforeStart, from, "\n\n", " ");
      const textAfter = editor.state.doc.textBetween(to, afterEnd, "\n\n", " ");
      return { destination: "selection", from, to, textBefore, textAfter, selectionText };
    }
    const from = editor.state.selection.from;
    const to = from;
    const docSize = editor.state.doc.content.size;
    const textBefore = editor.state.doc.textBetween(0, from, "\n\n", " ");
    const textAfter = editor.state.doc.textBetween(from, docSize, "\n\n", " ");
    return { destination: "cursor", from, to, textBefore, textAfter };
  },

  apply(gathered, host) {
    return host.streamInline(gathered);
  },
};

// ── extract_to_node ─────────────────────────────────────────────────────────

// What the extract handler needs from the chat pane (the ChatCommitController).
// Both phases are bound to the controller's state (cost attribution, the
// cross-pane review store), so — as with inline's stream — they delegate to the
// host: `extract` runs the transcript through the second-pass extractor and
// returns the validated patch (null on failure, message already surfaced);
// `publish` hands the patch to its diff review.
export interface ExtractHost {
  extract(): Promise<AIEntryPatch | null>;
  publish(patch: AIEntryPatch): void | Promise<void>;
}

export const extractHandler: OutputHandler<ExtractHost, AIEntryPatch> = {
  key: "extract_to_node",
  source: "transcript",
  review: "patch_diff",
  activation: "conversation",
  produce: (host) => host.extract(),
  apply: (patch, host) => host.publish(patch),
};

// ── registry + routing ──────────────────────────────────────────────────────

// The registry — the single import-time seam (ADR-0058). A new output behaviour
// is a new handler object + one line here, never a new core branch.
const _REGISTRY: Record<OutputHandlerKey, OutputHandler> = {
  inline: inlineHandler as OutputHandler,
  extract_to_node: extractHandler as OutputHandler,
};

// The inline destination a prompt declares (unset defaults to cursor). A pure read
// of `output.destination` now that it is stored — it used to be implied by the
// append-vs-replace kind.
export function inlineDestinationFor(output: PromptOutput | null | undefined): InlineDestination {
  return output?.destination === "selection" ? "selection" : "cursor";
}

// Route a prompt's output to its handler — a pure registry lookup on `output.handler`
// (ADR-0065). The stored key names the handler directly, so there is no branch to keep
// in sync with the vocabulary: a new handler is a new registry entry, nothing here.
// An unset/unknown handler (a `general` chat, a `snippet`) has none, and the result
// stays in the conversation.
export function outputHandlerFor(output: PromptOutput | null | undefined): OutputHandler | null {
  const key = output?.handler as OutputHandlerKey | undefined;
  return (key && _REGISTRY[key]) || null;
}
