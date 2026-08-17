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
// Behavioural — the two phases the activation surface drives:
//   produce     inline → gather the scan source (identity generation);
//               extract → the second-pass extractor (ADR-0063).
//   apply       inline → stream at the destination behind the aiSuggestion mark;
//               extract → write the node's fields after the diff.
//
// produce/apply are typed on each CONCRETE handler, not the shared base: the two
// live on different activation surfaces (the prose editor vs the chat pane) with
// genuinely different hosts, so a single generic signature would only buy an
// `any`. The shared `OutputHandler` is the declarative bundle the registry holds
// and routing reads; a unified produce/apply base is left for S3, when the bases
// collapse and one loop drives both (YAGNI until then, per the ADR's minimality
// rule: the base earns a method only when ≥2 handlers share its exact shape).
//
// Slice: S2a registers `inline` (continuation / revise / roleplay) and routes the
// editor's inline dispatch through it. `extract_to_node` (the brainstorm commit)
// joins in S2b; retiring the `output.kind` enum + re-authoring the built-ins is S3.

import type { Editor } from "@tiptap/core";
import type { EditableDocument, PromptEntrySummary, PromptOutput } from "@/lib/types";

export type OutputHandlerKey = "inline" | "extract_to_node";
export type OutputSource = "scan" | "transcript";
export type OutputReview = "inline_mark" | "patch_diff";
export type OutputActivation = "inline" | "conversation";
// Where an inline handler writes. cursor vs selection is a DESTINATION sub-choice
// (append_to_body vs replace_selection), not two separate handlers (ADR-0065 §3).
export type InlineDestination = "cursor" | "selection";

// How much surrounding prose a revise (selection) sends as context. Lives with
// the gather it parameterises (moved here from the controller with the source
// gathering it belongs to).
export const REVISE_CONTEXT_CHARS = 600;

// The declarative bundle — what every handler IS. The registry holds these; the
// core reads them to route without branching on the old `output.kind`.
export interface OutputHandler {
  readonly key: OutputHandlerKey;
  readonly source: OutputSource;
  readonly review: OutputReview;
  readonly activation: OutputActivation;
}

// One invocation's identity, shared by both phases of an inline run.
export interface OutputRun {
  entry: PromptEntrySummary;
  inputs: Record<string, unknown>;
  assistantId: string;
  scene: EditableDocument;
}

// The gathered scan source — `produce`'s output for the inline handler. The
// destination rides along so `apply` (streaming) knows cursor-vs-selection
// without re-reading the kind.
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
// pending mark, accept/revert/retry, telemetry), so `apply` delegates to it
// rather than reimplementing it.
export interface InlineHost {
  getEditor(): Editor | null;
  setError(message: string, anchor?: number): void;
  streamInline(gathered: InlineGathered): Promise<void>;
}

export interface InlineOutputHandler extends OutputHandler {
  readonly key: "inline";
  // produce: gather the scan source for the destination. Returns null when the
  // gather can't proceed (e.g. an empty selection) — having already reported it
  // via host.setError, exactly as the old inline branch did.
  produce(host: InlineHost, destination: InlineDestination): InlineGathered | null;
  // apply: stream the generation at the destination behind the aiSuggestion mark.
  apply(gathered: InlineGathered, host: InlineHost): Promise<void>;
}

export const inlineHandler: InlineOutputHandler = {
  key: "inline",
  source: "scan",
  review: "inline_mark",
  activation: "inline",

  produce(host, destination) {
    const editor = host.getEditor();
    if (!editor) return null;
    if (destination === "selection") {
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
      return { destination, from, to, textBefore, textAfter, selectionText };
    }
    const from = editor.state.selection.from;
    const to = from;
    const docSize = editor.state.doc.content.size;
    const textBefore = editor.state.doc.textBetween(0, from, "\n\n", " ");
    const textAfter = editor.state.doc.textBetween(from, docSize, "\n\n", " ");
    return { destination, from, to, textBefore, textAfter };
  },

  apply(gathered, host) {
    return host.streamInline(gathered);
  },
};

// The registry — the single import-time seam (ADR-0058). A new output behaviour
// is a new handler object + one line here, never a new core branch.
const _REGISTRY: Partial<Record<OutputHandlerKey, OutputHandler>> = {
  [inlineHandler.key]: inlineHandler,
};

// The inline destination a kind implies (append → cursor, replace → selection).
// The one place the two inline `output.kind` values map to the destination
// sub-choice.
export function inlineDestinationFor(output: PromptOutput | null | undefined): InlineDestination {
  return output?.kind === "replace_selection" ? "selection" : "cursor";
}

// Route a prompt's output to its handler. S2a resolves only the inline behaviour
// (append_to_body / replace_selection); chat_panel and commit stay with their
// current consumers until extract_to_node registers in S2b. Returns null for
// anything this registry doesn't yet own.
export function outputHandlerFor(output: PromptOutput | null | undefined): OutputHandler | null {
  const kind = output?.kind;
  if (kind === "append_to_body" || kind === "replace_selection") {
    return _REGISTRY.inline ?? null;
  }
  return null;
}
