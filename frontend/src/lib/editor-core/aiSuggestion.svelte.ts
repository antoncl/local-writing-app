// AiSuggestionController — the inline AI-suggestion pipeline for a single
// prose editor. ProseBodyView owns the TipTap editor, slash menu, selection
// toolbar and TODO marks; this controller owns everything to do with firing a
// prompt and streaming its output into the document as a pending suggestion:
// the in-flight `aiSuggestion` mark, the accept / revert / retry flow, the
// floating toolbar position, and the per-invocation telemetry write.
//
// It is an INSTANCE (one per editor), not a singleton — its `$state` lives on
// the class so the host can read it reactively (`ai.generating`, `ai.error`,
// `ai.toolbarPosition`, ...). The host injects live accessors for the editor /
// scene / prompt context (which change per pane) plus cost sinks and the two
// outbound callbacks; everything pure comes in as a plain module import.

import type { Editor } from "@tiptap/core";
import { api } from "@/lib/api";
import { countWords } from "@/lib/utils/wordCount";
import type { AiSuggestionMeta, AiToolbarPosition } from "@/lib/editor-core/aiToolbar";
import {
  type PromptResolutionContext,
  effectiveOutputKind,
  effectivePromptInputs,
  findPromptEntry,
  isRoleplayPromptEntry,
  characterIdFromInputValue,
  resolutionSceneIdFromInputs,
} from "@/lib/editor-core/promptResolution";
import type {
  ChatUsage,
  DocumentKind,
  EditableDocument,
  PromptEntrySummary,
} from "@/lib/types";

// How much surrounding prose to send as context for a revise (replace_selection).
const REVISE_CONTEXT_CHARS = 600;

export interface AiSuggestionDeps {
  // Live editor / document accessors (per-pane, change over the controller's life).
  getEditor: () => Editor | null;
  getEditorFrame: () => HTMLElement | undefined;
  getScene: () => EditableDocument | null;
  getDocumentKind: () => DocumentKind;
  getPromptCtx: () => PromptResolutionContext;
  // Cost sinks — the host keeps the bindable `$state` props and writes through.
  onInvocationCost: (cost: number) => void;
  addCharacterCost: (characterId: string, cost: number) => void;
  // Outbound callbacks (forwarded from ProseBodyView's props).
  onRequestInputsDialog: (payload: { entry: PromptEntrySummary }) => void;
  onOpenChat: (payload: {
    entry: PromptEntrySummary;
    inputs: Record<string, unknown>;
    sceneId: string | null;
    assistantId: string;
  }) => void;
}

export class AiSuggestionController {
  // Reactive state the host's markup binds to. v1 supports a single pending
  // suggestion at a time.
  generating = $state(false);
  error: string | null = $state(null);
  suggestionId: string | null = $state(null);
  meta: AiSuggestionMeta | null = $state(null);
  toolbarPosition: AiToolbarPosition = $state({ x: 0, y: 0, visible: false });

  // Non-reactive bookkeeping.
  #nextSuggestionId = 1;
  #suggestionOriginal: string | null = null;
  #anchorPos: number | null = null;
  #lastInvokedEntryId: string | null = null;
  #lastInvokedInputs: Record<string, unknown> = {};
  #lastInvokedAssistantId = "";

  #deps: AiSuggestionDeps;

  constructor(deps: AiSuggestionDeps) {
    this.#deps = deps;
  }

  // Drop any pending suggestion state — called when the host changes documents.
  reset(): void {
    this.suggestionId = null;
    this.meta = null;
    this.#suggestionOriginal = null;
    this.#anchorPos = null;
    this.error = null;
    this.toolbarPosition = { x: 0, y: 0, visible: false };
  }

  // ---------- AI inline suggestion ----------
  updateToolbarPosition(): void {
    const editor = this.#deps.getEditor();
    const editorFrame = this.#deps.getEditorFrame();
    if (!editor || !editorFrame) {
      if (this.toolbarPosition.visible) this.toolbarPosition = { x: 0, y: 0, visible: false };
      return;
    }
    let pos: number | null = null;
    if (this.suggestionId) {
      const range = this.#findSuggestionRange(this.suggestionId);
      if (range) pos = range.from;
    } else if (this.#anchorPos !== null) {
      const docSize = editor.state.doc.content.size;
      pos = Math.max(0, Math.min(this.#anchorPos, docSize));
    }
    if (pos === null) {
      if (this.toolbarPosition.visible) this.toolbarPosition = { x: 0, y: 0, visible: false };
      return;
    }
    try {
      const coords = editor.view.coordsAtPos(pos);
      const frameBounds = editorFrame.getBoundingClientRect();
      this.toolbarPosition = {
        x: coords.left - frameBounds.left + editorFrame.scrollLeft,
        y: coords.top - frameBounds.top + editorFrame.scrollTop,
        visible: true,
      };
    } catch {
      this.toolbarPosition = { x: 0, y: 0, visible: false };
    }
  }

  dismissError(): void {
    this.error = null;
    this.#anchorPos = null;
    this.toolbarPosition = { x: 0, y: 0, visible: false };
  }

  #findSuggestionRange(suggestionId: string): { from: number; to: number } | null {
    const editor = this.#deps.getEditor();
    if (!editor) return null;
    let from = -1;
    let to = -1;
    editor.state.doc.descendants((node, pos) => {
      if (!node.isText) return true;
      const has = node.marks.some(
        (m) => m.type.name === "aiSuggestion" && m.attrs.suggestionId === suggestionId,
      );
      if (has) {
        if (from === -1) from = pos;
        to = pos + node.nodeSize;
      }
      return true;
    });
    return from === -1 ? null : { from, to };
  }

  #renderStreamingSuggestion(startPos: number, fullText: string, suggestionId: string): void {
    const editor = this.#deps.getEditor();
    if (!editor) return;
    type Inline = { type: "text"; text: string } | { type: "hardBreak" };
    const paragraphs = fullText
      .split(/\n{2,}/)
      .map((para) => {
        const content: Inline[] = [];
        const lines = para.split(/\n/);
        lines.forEach((line, i) => {
          if (i > 0) content.push({ type: "hardBreak" });
          if (line) content.push({ type: "text", text: line });
        });
        return { type: "paragraph", content };
      })
      .filter((p) => p.content.length > 0);
    if (paragraphs.length === 0) return;
    const existing = this.#findSuggestionRange(suggestionId);
    const from = existing ? existing.from : startPos;
    const to = existing ? existing.to : startPos;
    editor
      .chain()
      .setTextSelection({ from, to })
      .deleteRange({ from, to })
      .insertContent(paragraphs)
      .run();
    const endPos = editor.state.selection.from;
    editor
      .chain()
      .setTextSelection({ from, to: endPos })
      .setMark("aiSuggestion", { suggestionId })
      .setTextSelection(endPos)
      .run();
    this.updateToolbarPosition();
  }

  accept(): void {
    const editor = this.#deps.getEditor();
    if (!editor || !this.suggestionId) return;
    const promptCtx = this.#deps.getPromptCtx();
    const range = this.#findSuggestionRange(this.suggestionId);
    const lastEntry = findPromptEntry(promptCtx, this.#lastInvokedEntryId);
    const characterId =
      range && isRoleplayPromptEntry(promptCtx, lastEntry)
        ? characterIdFromInputValue(this.#lastInvokedInputs.character)
        : null;
    if (range) {
      let chain = editor.chain().focus().setTextSelection(range).unsetMark("aiSuggestion");
      if (characterId) {
        chain = chain.setMark("character", { characterId });
      }
      chain.setTextSelection(range.to).run();
    }
    this.#persistAcceptedInvocation(lastEntry, characterId);
    this.suggestionId = null;
    this.meta = null;
    this.#suggestionOriginal = null;
    this.#anchorPos = null;
    this.error = null;
    this.toolbarPosition = { x: 0, y: 0, visible: false };
  }

  #persistAcceptedInvocation(
    entry: PromptEntrySummary | null,
    characterId: string | null,
  ): void {
    // Telemetry write — the `cost` computed field on the scene and the
    // per-character cost row in the footer both project from this log.
    // Fire-and-forget; a failed POST shouldn't block accept.
    const scene = this.#deps.getScene();
    if (!scene || !this.meta) return;
    const meta = this.meta;
    const cost = meta.cost_usd;
    if (characterId && typeof cost === "number") {
      // Optimistic per-character rollup. The next scene-load reconciles
      // against the backend; for this session we trust the local write.
      this.#deps.addCharacterCost(characterId, cost);
    }
    api
      .aiAppendInvocation({
        prompt_entry_id: entry?.id ?? this.#lastInvokedEntryId ?? "",
        prompt_entry_type: entry?.entry_type ?? "",
        scene_id: scene.id,
        character_id: characterId ?? "",
        provider: meta.provider ?? "",
        model: meta.model ?? "",
        usage: meta.usage ?? null,
        cost_usd: meta.cost_usd ?? null,
      })
      .catch((err) => {
        console.warn("Failed to persist AI invocation telemetry:", err);
      });
  }

  revert(): void {
    const editor = this.#deps.getEditor();
    if (!editor || !this.suggestionId) return;
    const range = this.#findSuggestionRange(this.suggestionId);
    if (range) {
      if (this.#suggestionOriginal !== null) {
        editor
          .chain()
          .focus()
          .setTextSelection(range)
          .deleteSelection()
          .insertContent(this.#suggestionOriginal)
          .run();
      } else {
        editor.chain().focus().deleteRange(range).run();
      }
    }
    this.suggestionId = null;
    this.meta = null;
    this.#suggestionOriginal = null;
    this.#anchorPos = null;
    this.error = null;
    this.toolbarPosition = { x: 0, y: 0, visible: false };
  }

  async retry(): Promise<void> {
    const editor = this.#deps.getEditor();
    if (!this.suggestionId || this.generating || !editor) return;
    const wasRevision = this.#suggestionOriginal !== null;
    const original = this.#suggestionOriginal;
    const range = this.#findSuggestionRange(this.suggestionId);
    const entry = findPromptEntry(this.#deps.getPromptCtx(), this.#lastInvokedEntryId);
    if (!entry) {
      this.error = "Original prompt is no longer available.";
      return;
    }

    this.revert();

    if (wasRevision && original && range) {
      const restoredTo = range.from + original.length;
      editor.chain().focus().setTextSelection({ from: range.from, to: restoredTo }).run();
    }
    await this.runPromptEntry(entry, this.#lastInvokedInputs, this.#lastInvokedAssistantId);
  }

  // ---------- Prompt invocation pipeline ----------
  async runPromptEntry(
    entry: PromptEntrySummary,
    prefilledInputs?: Record<string, unknown>,
    assistantId: string = "",
  ): Promise<void> {
    const editor = this.#deps.getEditor();
    const scene = this.#deps.getScene();
    if (!editor || !scene || this.generating || this.#deps.getDocumentKind() !== "scene") return;
    if (this.suggestionId) {
      this.error = "Accept or revert the pending suggestion before generating another.";
      return;
    }
    const declared = effectivePromptInputs(entry);
    if (declared.length > 0 && !prefilledInputs) {
      this.#deps.onRequestInputsDialog({ entry });
      return;
    }
    await this.runPromptEntryWithInputs(entry, prefilledInputs ?? {}, assistantId);
  }

  async runPromptEntryWithInputs(
    entry: PromptEntrySummary,
    inputs: Record<string, unknown>,
    assistantId: string = "",
  ): Promise<void> {
    const editor = this.#deps.getEditor();
    const scene = this.#deps.getScene();
    if (!editor || !scene) return;
    const outputKind = effectiveOutputKind(this.#deps.getPromptCtx(), entry);
    if (outputKind === "chat_panel") {
      this.#lastInvokedEntryId = entry.id;
      this.#lastInvokedInputs = inputs;
      this.#lastInvokedAssistantId = assistantId;
      this.#deps.onOpenChat({ entry, inputs, sceneId: scene.id, assistantId });
      return;
    }
    if (outputKind !== "append_to_body" && outputKind !== "replace_selection") {
      this.error = `Output kind "${outputKind ?? "(unset)"}" is not yet supported for inline dispatch.`;
      this.updateToolbarPosition();
      return;
    }

    let selectionText: string | undefined;
    let textBefore: string;
    let textAfter: string;
    let from: number;
    let to: number;

    if (outputKind === "replace_selection") {
      const sel = editor.state.selection;
      from = sel.from;
      to = sel.to;
      if (from === to) {
        this.#anchorPos = from;
        this.error = "Select text to revise.";
        this.updateToolbarPosition();
        return;
      }
      selectionText = editor.state.doc.textBetween(from, to, "\n\n", " ");
      if (!selectionText.trim()) {
        this.#anchorPos = from;
        this.error = "Select non-empty text to revise.";
        this.updateToolbarPosition();
        return;
      }
      const docSize = editor.state.doc.content.size;
      const beforeStart = Math.max(0, from - REVISE_CONTEXT_CHARS);
      const afterEnd = Math.min(docSize, to + REVISE_CONTEXT_CHARS);
      textBefore = editor.state.doc.textBetween(beforeStart, from, "\n\n", " ");
      textAfter = editor.state.doc.textBetween(to, afterEnd, "\n\n", " ");
    } else {
      from = editor.state.selection.from;
      to = from;
      const docSize = editor.state.doc.content.size;
      textBefore = editor.state.doc.textBetween(0, from, "\n\n", " ");
      textAfter = editor.state.doc.textBetween(from, docSize, "\n\n", " ");
    }

    this.error = null;
    this.#anchorPos = from;
    this.generating = true;
    this.#lastInvokedEntryId = entry.id;
    this.#lastInvokedInputs = inputs;
    this.#lastInvokedAssistantId = assistantId;
    this.updateToolbarPosition();

    const suggestionId = `ai-${this.#nextSuggestionId++}`;
    let startPos = from;
    let streamingActive = false;
    let accumulated = "";
    let lastMeta: {
      provider: string;
      model: string;
      latency_ms: number;
      truncated: boolean;
      usage?: ChatUsage | null;
      cost_usd?: number | null;
    } | null = null;
    let streamErrored = false;

    const ensureStreamingStarted = () => {
      if (streamingActive || !editor) return;
      if (outputKind === "replace_selection") {
        const currentText = editor.state.doc.textBetween(from, to, "\n\n", " ");
        if (currentText !== selectionText) {
          this.error = "Document changed during the AI call. Re-select the text and retry.";
          streamErrored = true;
          return;
        }
        editor.chain().focus().setTextSelection({ from, to }).deleteSelection().run();
        startPos = editor.state.selection.from;
        this.#suggestionOriginal = selectionText!;
      } else {
        startPos = editor.state.selection.from;
      }
      this.suggestionId = suggestionId;
      streamingActive = true;
    };

    try {
      for await (const ev of api.aiGenerateStream({
        template_source: entry.body,
        target_scene_id: scene.id,
        session_id: scene.id,
        inputs,
        resolution_scene_id: resolutionSceneIdFromInputs(entry, inputs),
        text_before: textBefore,
        text_after: textAfter,
        ...(selectionText !== undefined ? { selection: selectionText } : {}),
        ...(assistantId ? { assistant_id: assistantId } : {}),
        commit: false,
      })) {
        if (ev.type === "delta") {
          accumulated += ev.text;
          ensureStreamingStarted();
          if (streamErrored) break;
          if (!editor) break;
          this.#renderStreamingSuggestion(startPos, accumulated, suggestionId);
        } else if (ev.type === "done") {
          lastMeta = {
            provider: ev.provider,
            model: ev.model,
            latency_ms: ev.latency_ms,
            truncated: ev.truncated,
            usage: ev.usage ?? null,
            cost_usd: ev.cost_usd ?? null,
          };
        } else if (ev.type === "error") {
          this.error = ev.error || "Unknown error";
          streamErrored = true;
          if (streamingActive && editor) {
            const range = this.#findSuggestionRange(suggestionId);
            if (range) {
              if (outputKind === "replace_selection" && this.#suggestionOriginal) {
                editor
                  .chain()
                  .setTextSelection({ from: range.from, to: range.to })
                  .deleteSelection()
                  .insertContent(this.#suggestionOriginal)
                  .run();
              } else {
                editor
                  .chain()
                  .setTextSelection({ from: range.from, to: range.to })
                  .deleteSelection()
                  .run();
              }
            }
            this.suggestionId = null;
            this.#suggestionOriginal = null;
          }
        }
      }
      if (!streamErrored) {
        if (!accumulated.trim()) {
          this.error = "Model returned empty output.";
        } else if (lastMeta) {
          this.meta = {
            provider: lastMeta.provider,
            model: lastMeta.model,
            latency_ms: lastMeta.latency_ms,
            truncated: lastMeta.truncated,
            wordCount: countWords(accumulated),
            usage: lastMeta.usage,
            cost_usd: lastMeta.cost_usd,
          };
          if (typeof lastMeta.cost_usd === "number") {
            this.#deps.onInvocationCost(lastMeta.cost_usd);
          }
          this.#anchorPos = null;
        }
      }
    } catch (e) {
      this.error = (e as Error).message;
    } finally {
      this.generating = false;
      this.updateToolbarPosition();
    }
  }
}
