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
  promptSurfaceFor,
  effectivePromptInputs,
  findPromptEntry,
  promptOnAccept,
  characterIdFromInputValue,
  resolutionSceneIdFromInputs,
} from "@/lib/editor-core/promptResolution";
import {
  inlineHandler,
  type InlineDestination,
  type InlineGathered,
  type InlineHost,
  type OutputRun,
} from "@/lib/editor-core/outputHandlers";
import { splitInteriority, visibleExternal } from "@/lib/editor-core/interiority";
import type {
  ChatUsage,
  DocumentKind,
  EditableDocument,
  PromptEntrySummary,
} from "@/lib/types";

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
  // The private interiority split off the last completed generation (ADR-0070),
  // held between stream-done and accept so it can be stamped onto the beat's
  // character mark. Null when the run carried no interiority.
  #pendingInternal: string | null = null;

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
    this.#pendingInternal = null;
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
      const x = coords.left - frameBounds.left + editorFrame.scrollLeft;
      // The toolbar renders ABOVE the suggestion's first line so it never
      // occludes the prose (#1275). Clipping by `.editor-wrap`'s `overflow: auto`
      // happens at the scroll box's VISIBLE edges, so the room-above test is on
      // the line's viewport-relative offset (as updateSelectionMenu's
      // `hasRoomAbove` does), not the content-space one; when there's no room,
      // flip below the line. `y` stays content-space (the toolbar is absolute in
      // the scroll content). 40px is a conservative one-row toolbar height + gap.
      const viewportTop = coords.top - frameBounds.top;
      const TOOLBAR_CLEARANCE = 40;
      const placeBelow = viewportTop < TOOLBAR_CLEARANCE;
      this.toolbarPosition = {
        x,
        y: placeBelow
          ? coords.bottom - frameBounds.top + editorFrame.scrollTop
          : viewportTop + editorFrame.scrollTop,
        placement: placeBelow ? "below" : "above",
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
    // The prompt's type may DECLARE an accept-time mark-stamp (#954): roleplay
    // stamps the `character` mark from its `character` input. Read off the declared
    // capability, not an `entry_type == roleplay` branch.
    const onAccept = promptOnAccept(promptCtx, lastEntry);
    const characterId =
      range && onAccept
        ? characterIdFromInputValue(this.#lastInvokedInputs[onAccept.fromInput])
        : null;
    if (range) {
      let chain = editor.chain().focus().setTextSelection(range).unsetMark("aiSuggestion");
      if (characterId && onAccept) {
        // ADR-0070: bind the beat's private interiority to the same character
        // mark, so it rides with the beat (and dies with it on rewind).
        const internal = this.#pendingInternal ?? "";
        chain = chain.setMark(onAccept.mark, { characterId, internal });
      }
      chain.setTextSelection(range.to).run();
    }
    this.#persistAcceptedInvocation(lastEntry, characterId);
    this.suggestionId = null;
    this.meta = null;
    this.#suggestionOriginal = null;
    this.#anchorPos = null;
    this.#pendingInternal = null;
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
    this.#pendingInternal = null;
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
    if (!editor || !scene || this.generating || this.#deps.getDocumentKind() !== "manuscript") return;
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
    const ctx = this.#deps.getPromptCtx();
    const surface = promptSurfaceFor(ctx, entry);
    if (surface === "cursor" || surface === "selection") {
      const run: OutputRun = { entry, inputs, assistantId, scene };
      const host = this.#inlineHost(run, surface);
      const gathered = await inlineHandler.produce(host);
      if (!gathered) return;
      this.error = null;
      this.#anchorPos = gathered.from;
      this.generating = true;
      this.#lastInvokedEntryId = entry.id;
      this.#lastInvokedInputs = inputs;
      this.#lastInvokedAssistantId = assistantId;
      this.updateToolbarPosition();
      await inlineHandler.apply(gathered, host);
      return;
    }
    // A `conversation` surface (ADR-0065) — an `extract_to_node` brainstorm or a
    // handler-less `general` chat — opens in a chat. Only a prompt with no
    // context_strategy at all (a snippet, or a misconfigured type) can't be invoked here.
    if (surface === "conversation") {
      this.#lastInvokedEntryId = entry.id;
      this.#lastInvokedInputs = inputs;
      this.#lastInvokedAssistantId = assistantId;
      this.#deps.onOpenChat({ entry, inputs, sceneId: scene.id, assistantId });
      return;
    }
    this.error = `Prompt "${entry.title}" has no output handler and can't be invoked here.`;
    this.updateToolbarPosition();
  }

  // Build the inline handler's host for one run — the seam between the registered
  // handler and this controller's streaming primitive + error surface.
  #inlineHost(run: OutputRun, destination: InlineDestination): InlineHost {
    return {
      destination,
      getEditor: () => this.#deps.getEditor(),
      setError: (message, anchor) => {
        this.error = message;
        if (anchor !== undefined) this.#anchorPos = anchor;
        this.updateToolbarPosition();
      },
      streamInline: (gathered) => this.#streamInline(gathered, run),
    };
  }

  // The inline handler's `apply`: stream the generation at the gathered
  // destination behind the aiSuggestion mark. It stays a method here because the
  // stream is bound to this controller's reactive state (the pending mark, the
  // revert-original buffer, telemetry) — the handler delegates to it. Behaviour is
  // the pre-ADR-0065 inline stream verbatim: only the source now arrives as
  // `gathered`, and the destination test reads `gathered.destination`.
  async #streamInline(gathered: InlineGathered, run: OutputRun): Promise<void> {
    const editor = this.#deps.getEditor();
    if (!editor) return;
    const { from, to, selectionText, textBefore, textAfter, destination } = gathered;
    const { entry, inputs, assistantId, scene } = run;

    // A beat-marking prompt (roleplay, via on_accept) may deliver two parts —
    // visible prose then `[[interiority]]` then private inner state (ADR-0070).
    // Only the external part is ever rendered; the internal is stashed for accept.
    const carriesInteriority = Boolean(promptOnAccept(this.#deps.getPromptCtx(), entry));
    this.#pendingInternal = null;

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
      if (destination === "selection") {
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
          const visible = carriesInteriority ? visibleExternal(accumulated) : accumulated;
          this.#renderStreamingSuggestion(startPos, visible, suggestionId);
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
              if (destination === "selection" && this.#suggestionOriginal) {
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
        // Split the completed output into the visible beat and its private
        // interiority (ADR-0070). Non-roleplay runs carry no interiority, so
        // `external` is the whole text and `internal` is empty.
        const { external, internal } = carriesInteriority
          ? splitInteriority(accumulated)
          : { external: accumulated, internal: "" };
        this.#pendingInternal = carriesInteriority ? internal : null;
        if (!external.trim()) {
          this.error = "Model returned empty output.";
        } else if (lastMeta) {
          this.meta = {
            provider: lastMeta.provider,
            model: lastMeta.model,
            latency_ms: lastMeta.latency_ms,
            truncated: lastMeta.truncated,
            wordCount: countWords(external),
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
