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
import type { Transaction } from "@tiptap/pm/state";
import type { EditorView } from "@tiptap/pm/view";
import { get } from "svelte/store";
import { api } from "@/lib/api";
import { assistantEntriesStore } from "@/lib/stores/assistants";
import { assistantForPrompt } from "@/lib/chat/assistantScope";
import type { AIStreamEvent } from "@/lib/api/core";
import { countWords } from "@/lib/utils/wordCount";
import { placeAiToolbar, type AiSuggestionMeta, type AiToolbarPosition } from "@/lib/editor-core/aiToolbar";
import {
  type PromptResolutionContext,
  promptSurfaceFor,
  effectivePromptInputs,
  findPromptEntry,
  promptOnAccept,
  characterIdFromInputValue,
  resolutionSceneIdFromInputs,
  promptOffersOn,
} from "@/lib/editor-core/promptResolution";
import { seedConversationInputs } from "@/components/editor/body/chat/chatInputs";
import {
  gatheredRequestFields,
  outputHandlerFor,
  type InlineDestination,
  type InlineGathered,
  type OutputHandler,
  type InlineHost,
  type OutputRun,
} from "@/lib/editor-core/outputHandlers";
import { editorCallback } from "@/lib/editor-core/editorCallback";
import { placeLineEdits } from "@/lib/editor-core/lineEdits";
import {
  acceptAllLineEdits,
  acceptCurrentLineEdit,
  currentLineEdit,
  currentLineNote,
  dismissAllLineNotes,
  dismissCurrentLineNote,
  editsKind,
  installFlags,
  installLineEdits,
  installLineNotes,
  keepReviewItem,
  lineEditState,
  lineNoteState,
  rejectAllFlags,
  rejectAllLineEdits,
  rejectCurrentLineEdit,
  setReviewView,
  stepLineEdit,
  stepLineNote,
  type ReviewView,
} from "@/lib/editor-core/lineEditSuggestions";
import { notesKind } from "@/lib/editor-core/reviewKinds/notes";
import { reviewState, stepReview } from "@/lib/editor-core/reviewKinds/core";
import { flagEntryNames, flagsNotice, placeSceneFlags, type SceneFlags } from "@/lib/editor-core/conversationFlags";
import { editKeepNote, keepFlag, noteKeepNote, type KeepWriters } from "@/lib/editor-core/keepFlag";
import { fetchLineNotes, noteNotice, type NotesDone } from "@/lib/editor-core/aiLineNotes";
import {
  hasMutationMarker,
  markerNotice,
  placeMutationMarkers,
} from "@/lib/editor-core/mutationMarkers";
import { joinAtCursor } from "@/lib/editor-core/cursorJoin";
import { splitInteriority, visibleExternal } from "@/lib/editor-core/interiority";
import type {
  ChatUsage,
  CheckedEntry,
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
  onRequestInputsDialog: (payload: {
    entry: PromptEntrySummary;
    prefilledDrafts?: Record<string, string>;
  }) => void;
  // Short user-facing note (e.g. "Placed 3 changes in the draft.").
  onNotice?: (message: string) => void;
  // Open a lore entry by id (a lore-check note's "Open entry").
  onOpenEntry?: (id: string) => void;
  // Keep a flag as a TODO (ADR-0099): the embedded-mark write (null when it
  // couldn't be made) and the file-TODO write (throws when it failed).
  keepWriters?: KeepWriters;
  onOpenChat: (payload: {
    entry: PromptEntrySummary;
    inputs: Record<string, unknown>;
    sceneId: string | null;
    assistantId: string;
  }) => void;
  // Persist every open pane's pending edits before the call reads project files
  // (#2596) — the template renders the scene, picks and lore from disk, and an
  // idle autosave may still be seconds away. Never throws.
  persistEdits?: () => Promise<void>;
}

// The dialog's draft strings for seeded natural-valued inputs: strings pass
// through, list shapes stringify (the encoding every input widget stores).
function draftsFromInputs(inputs: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(inputs).map(([name, value]) => [name, typeof value === "string" ? value : JSON.stringify(value)]),
  );
}

// Coalescing window for streamed-suggestion renders (#2428).
const RENDER_WINDOW_MS = 100;

export class AiSuggestionController {
  // Reactive state the host's markup binds to. v1 supports a single pending
  // suggestion at a time.
  generating = $state(false);
  error: string | null = $state(null);
  suggestionId: string | null = $state(null);
  meta: AiSuggestionMeta | null = $state(null);
  toolbarPosition: AiToolbarPosition = $state({ x: 0, y: 0, visible: false });
  // Pending line edits (#2460), for the review bar: how many are still to
  // review, the current one's 1-based place among them and its reason. Null
  // when no edit list is open.
  lineEdits: { remaining: number; index: number; currentReason: string } | null = $state(null);
  // Pending lore-check notes (ADR-0098), likewise: how many are left, the current
  // one's 1-based place, and the lore entries the check ran against. Null when no
  // note list is open. Only one review (edits OR notes) is open per editor.
  lineNotes: { remaining: number; index: number; checkedAgainst: CheckedEntry[] } | null = $state(null);
  // Flags placed from a conversation (ADR-0100): one review over both kinds, with
  // its own combined bar. Independent of lineEdits / lineNotes, which stay null.
  // `edits` = how many of the remaining are edits (Accept all shows only then).
  flags: { remaining: number; index: number; edits: number } | null = $state(null);
  // Which version an open edit review reads as (#2561), mirrored from the plugin
  // on every sync so the bar's A / S / B buttons and the Alt keys agree.
  lineEditView: ReviewView = $state("both");

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
  // Streaming-render throttle (#2428): at most one render per window while deltas
  // arrive. A setTimeout, not rAF - a hidden pane gets no frames. Cleared by
  // reset() / revert() / the stream's `finally`, so it can't fire on a dead suggestion.
  #renderTimer: ReturnType<typeof setTimeout> | null = null;
  // The open line-edit list (#2460): the revised range (kept current through the
  // writer's edits, for Retry) and the unsubscribe of the listener that tracks it.
  #lineEditRange: { from: number; to: number } | null = null;
  #stopWatchingLineEdits: (() => void) | null = null;
  // The entries the open note list's check ran against (shown in the footer).
  #checkedAgainst: CheckedEntry[] = [];
  // Bumped by reset(): a line-edits reply that arrives after it belongs to a
  // document the writer has left, and is discarded.
  #runEpoch = 0;
  // The running generation's abort handle (#2464): Cancel and Esc abort it.
  #abort: AbortController | null = null;
  // Flags whose Keep is in flight (a file TODO write), so a second click on the
  // same flag doesn't make a second TODO.
  #keeping = new Set<number>();
  // Set while `persistEdits` runs ahead of a call (#2596): bars a second run
  // meanwhile without showing "generating" for what is only a save.
  #persisting = false;

  #deps: AiSuggestionDeps;

  constructor(deps: AiSuggestionDeps) {
    this.#deps = deps;
  }

  // Drop any pending suggestion state — called when the host changes documents.
  reset(): void {
    this.#cancelRenderTimer();
    this.suggestionId = null;
    this.meta = null;
    this.#suggestionOriginal = null;
    this.#anchorPos = null;
    this.#pendingInternal = null;
    // Leaving the document also stops its generation (#2464): the reply would be
    // discarded anyway (the epoch below), and an abort is what frees the provider
    // instead of letting it finish a run nobody will see.
    this.#abort?.abort();
    this.#runEpoch += 1;
    const editor = this.#deps.getEditor();
    // Leave no orphaned edit decorations behind on the editor we're leaving. The
    // watcher goes first so this reject isn't booked as a resolved list (its
    // telemetry would land on whichever scene is current by now).
    this.#stopWatchingLineEdits?.();
    this.#stopWatchingLineEdits = null;
    if (editor && !editor.isDestroyed && lineEditState(editor.state).edits.length > 0) {
      rejectAllLineEdits(editor.view);
    }
    if (editor && !editor.isDestroyed && lineNoteState(editor.state).notes.length > 0) {
      dismissAllLineNotes(editor.view);
    }
    this.#closeLineEdits();
    this.error = null;
    this.toolbarPosition = { x: 0, y: 0, visible: false };
  }

  // Cancel the running generation (#2464). The run itself unwinds: a line-edit
  // run installs nothing, a stream restores the text it displaced.
  cancelGeneration(): void {
    this.#abort?.abort();
  }

  #cancelRenderTimer(): void {
    if (this.#renderTimer !== null) clearTimeout(this.#renderTimer);
    this.#renderTimer = null;
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
      // Clipping by `.editor-wrap`'s `overflow: auto` happens at the scroll
      // box's VISIBLE edges, so placement works on the line's offsets from the
      // visible top (as updateSelectionMenu's `hasRoomAbove` does).
      const placed = placeAiToolbar(
        { top: coords.top - frameBounds.top, bottom: coords.bottom - frameBounds.top },
        { height: editorFrame.clientHeight, scrollTop: editorFrame.scrollTop },
      );
      this.toolbarPosition = { x, ...placed, visible: true };
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
    type Inline =
      | { type: "text"; text: string; marks: { type: string; attrs: { suggestionId: string } }[] }
      | { type: "hardBreak" };
    const marks = [{ type: "aiSuggestion", attrs: { suggestionId } }];
    // A line break at either end would become a hardBreak outside the suggestion's
    // range (which spans marked text only) — left behind by Discard, and one per
    // render while a paragraph break is half-streamed (#2431). Spaces stay: a
    // continuation mid-sentence needs its leading one.
    const paragraphs = fullText
      .replace(/^[^\S\n]*\n\s*/, "")
      .replace(/\s*\n[^\S\n]*$/, "")
      .split(/\n{2,}/)
      .map((para) => {
        const content: Inline[] = [];
        const lines = para.split(/\n/);
        lines.forEach((line, i) => {
          if (i > 0) content.push({ type: "hardBreak" });
          if (line) content.push({ type: "text", text: line, marks });
        });
        return { type: "paragraph", content };
      })
      .filter((p) => p.content.length > 0);
    if (paragraphs.length === 0) return;
    const existing = this.#findSuggestionRange(suggestionId);
    const from = existing ? existing.from : startPos;
    const to = existing ? existing.to : startPos;
    // One transaction: the mark rides on the inserted text nodes, and the caret
    // ends after the inserted text.
    editor
      .chain()
      .setTextSelection({ from, to })
      .deleteRange({ from, to })
      .insertContent(paragraphs)
      .run();
    this.updateToolbarPosition();
  }

  accept(): void {
    const editor = this.#deps.getEditor();
    if (!editor || !this.suggestionId) return;
    const promptCtx = this.#deps.getPromptCtx();
    let range = this.#findSuggestionRange(this.suggestionId);
    if (range && hasMutationMarker(editor.state.doc.textBetween(range.from, range.to, "\n", " "))) {
      // #2424: move each mutation pill to its `⟦id⟧` marker (one transaction), then
      // re-find the range — the marker text changed its length.
      const placement = placeMutationMarkers(editor.state, range);
      if (placement.tr) {
        editor.view.dispatch(placement.tr);
        range = this.#findSuggestionRange(this.suggestionId);
        const notice = markerNotice(placement.moved.length, placement.unknown.length);
        if (notice) this.#deps.onNotice?.(notice);
      }
    }
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
        // A non-scene document (a lore entry) files under no scene.
        scene_id: this.#sceneIdForWire(scene),
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
    this.#cancelRenderTimer();
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
    if (this.lineEdits || this.lineNotes) return this.#retryLineEdits();
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
    if (!editor || !scene || this.generating || this.#persisting) return;
    if (!promptOffersOn(this.#deps.getPromptCtx(), entry, scene.entry_type)) {
      this.#deps.onNotice?.(`"${entry.title}" isn't offered on this document.`);
      return;
    }
    if (this.lineEdits) {
      // The floating toolbar is hidden while line edits are pending, so `error`
      // would never show: say it as a notice instead.
      this.#deps.onNotice?.("Finish reviewing the line edits first — accept or reject them, or Reject all.");
      return;
    }
    if (this.lineNotes) {
      this.#deps.onNotice?.("Finish reviewing the notes first — dismiss them or Dismiss all.");
      return;
    }
    if (this.flags) {
      this.#deps.onNotice?.("Finish reviewing the flags first — resolve them or Reject all.");
      return;
    }
    if (this.suggestionId) {
      this.error = "Accept or revert the pending suggestion before generating another.";
      return;
    }
    const declared = effectivePromptInputs(entry);
    if (prefilledInputs) {
      await this.runPromptEntryWithInputs(entry, prefilledInputs, assistantId);
      return;
    }
    // A non-scene document seeds the prompt's `entry` input with itself, so a
    // prompt whose only input is that (hidden) subject runs without a dialog.
    const seeded = this.#subjectSeed(entry, scene);
    if (declared.some((input) => !input.hidden)) {
      this.#deps.onRequestInputsDialog({
        entry,
        ...(Object.keys(seeded).length > 0 ? { prefilledDrafts: draftsFromInputs(seeded) } : {}),
      });
      return;
    }
    await this.runPromptEntryWithInputs(entry, seeded, assistantId);
  }

  // The wire id of the open document: the scene id for a manuscript scene, ""
  // for any other prose body (the backend renders `scene` as absent).
  #sceneIdForWire(scene: EditableDocument): string {
    return this.#deps.getDocumentKind() === "manuscript" ? scene.id : "";
  }

  #subjectSeed(entry: PromptEntrySummary, scene: EditableDocument): Record<string, unknown> {
    if (this.#deps.getDocumentKind() === "manuscript") return {};
    if (!effectivePromptInputs(entry).some((input) => input.name === "entry")) return {};
    return seedConversationInputs(entry, scene.id, scene.title, scene.entry_type, null);
  }

  async runPromptEntryWithInputs(
    entry: PromptEntrySummary,
    inputs: Record<string, unknown>,
    assistantId: string = "",
  ): Promise<void> {
    const editor = this.#deps.getEditor();
    const scene = this.#deps.getScene();
    if (!editor || !scene) return;
    // No explicit pick → the prompt's own preference (pin, else tag scope);
    // the backend would otherwise resolve "" to the topmost overall (#2593).
    // Resolved into its own name so retry replays the caller's pick ("" stays
    // ""), re-resolving against the prompt and roster as they are then.
    const runAssistantId = assistantId || assistantForPrompt(entry, get(assistantEntriesStore));
    const ctx = this.#deps.getPromptCtx();
    const surface = promptSurfaceFor(ctx, entry);
    if (surface === "cursor" || surface === "selection") {
      const run: OutputRun = { entry, inputs, assistantId: runAssistantId, scene };
      // Both editor handlers share one host; the registry decides which drives it.
      const handler = outputHandlerFor(entry.context_strategy?.output) as OutputHandler<InlineHost, InlineGathered>;
      const host = this.#inlineHost(run, surface);
      // #2596: before `produce` — nothing in the document has changed yet, so the
      // save carries exactly what the author sees, and the call reads it back.
      this.#persisting = true;
      try {
        await this.#deps.persistEdits?.();
      } finally {
        this.#persisting = false;
      }
      const gathered = await handler.produce(host);
      if (!gathered) return;
      this.error = null;
      this.#anchorPos = gathered.from;
      this.generating = true;
      this.#lastInvokedEntryId = entry.id;
      this.#lastInvokedInputs = inputs;
      this.#lastInvokedAssistantId = assistantId;
      this.updateToolbarPosition();
      await handler.apply(gathered, host);
      return;
    }
    // A `conversation` surface (ADR-0065) — an `extract_to_node` brainstorm or a
    // handler-less `general` chat — opens in a chat. Only a prompt with no
    // context_strategy at all (a snippet, or a misconfigured type) can't be invoked here.
    if (surface === "conversation") {
      this.#lastInvokedEntryId = entry.id;
      this.#lastInvokedInputs = inputs;
      this.#lastInvokedAssistantId = assistantId;
      this.#deps.onOpenChat({ entry, inputs, sceneId: scene.id, assistantId: runAssistantId });
      return;
    }
    this.error = `Prompt "${entry.title}" has no output handler and can't be invoked here.`;
    this.updateToolbarPosition();
  }

  // Build the editor handlers' host for one run — the seam between the registered
  // handler and this controller's run primitives (stream, line edits) + error surface.
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
      runLineEdits: (gathered) => this.#runLineEdits(gathered, run),
      runLineNotes: (gathered) => this.#runLineNotes(gathered, run),
    };
  }

  // The lore check's `apply` (ADR-0098): the call + placement live in aiLineNotes.ts;
  // here the outcome becomes state. A check has nothing to accept, so its cost and
  // telemetry are recorded on ARRIVAL, even for a reply with no notes.
  async #runLineNotes(gathered: InlineGathered, run: OutputRun): Promise<void> {
    const editor = this.#deps.getEditor();
    if (!editor) return;
    const { from, to } = gathered;
    const { scene } = run;
    const epoch = this.#runEpoch;
    const abort = new AbortController();
    this.#abort = abort;
    try {
      const out = await fetchLineNotes({
        editor,
        gathered,
        run,
        sceneIdForWire: this.#sceneIdForWire(scene),
        signal: abort.signal,
        isStale: () => epoch !== this.#runEpoch || this.#deps.getScene()?.id !== scene.id,
      });
      if (out.kind === "cancelled") {
        if (epoch === this.#runEpoch) this.#deps.onNotice?.("Check cancelled.");
        return;
      }
      if (out.kind === "stale") return;
      if (out.kind === "error") {
        // A reply that arrived but can't be used (cut off, unreadable, the text
        // moved) was still paid for: record it, then show the error.
        if (out.res) {
          this.#recordNotesArrival(out.res, run, 0);
          this.meta = null;
        }
        this.error = out.message;
        return;
      }
      const { res, placed, dropped, checkedAgainst } = out;
      this.#recordNotesArrival(res, run, placed.length);
      this.#anchorPos = null;
      const notice = noteNotice(placed.length, dropped);
      if (placed.length === 0) {
        this.meta = null;
        if (notice) this.#deps.onNotice?.(notice);
        return;
      }
      const names = new Map(checkedAgainst.map((c) => [c.id, c.name]));
      this.#checkedAgainst = checkedAgainst;
      this.#lineEditRange = { from, to };
      installLineNotes(editor.view, placed, to, {
        openEntry: (id) => this.#deps.onOpenEntry?.(id),
        entryName: (id) => names.get(id) ?? "",
        keep: (view, note) =>
          void this.#keepFlag(view, note.id, note.from, note.to, note.quote, noteKeepNote(note.problem, names.get(note.entry) || note.entry)),
      });
      this.#syncLineNotes(editor);
      this.#watchLineNotes(editor);
      if (notice) this.#deps.onNotice?.(notice);
    } catch (e) {
      this.error = (e as Error).message;
    } finally {
      if (this.#abort === abort) this.#abort = null;
      this.generating = false;
      this.updateToolbarPosition();
    }
  }

  // Keep one flag as a TODO (ADR-0099), then resolve it as kept. A failed write
  // leaves the flag where it is and says why.
  async #keepFlag(view: EditorView, id: number, from: number, to: number, quote: string, note: string): Promise<void> {
    const scene = this.#deps.getScene();
    const writers = this.#deps.keepWriters;
    if (!scene || !writers || this.#keeping.has(id)) return;
    this.#keeping.add(id);
    try {
      await keepFlag(
        {
          doc: view.state.doc,
          from,
          to,
          quote,
          note,
          inScene: this.#deps.getDocumentKind() === "manuscript",
          docId: scene.id,
        },
        writers,
      );
    } catch (e) {
      this.error = (e as Error).message;
      return;
    } finally {
      this.#keeping.delete(id);
    }
    if (!view.isDestroyed) keepReviewItem(view, id);
  }

  // A check has nothing to accept, so its cost and telemetry are recorded when the
  // reply arrives - usable or not.
  #recordNotesArrival(res: NotesDone, run: OutputRun, placedCount: number): void {
    this.meta = {
      provider: res.provider,
      model: res.model,
      latency_ms: res.latency_ms,
      truncated: res.truncated,
      wordCount: placedCount,
      usage: res.usage ?? null,
      cost_usd: res.cost_usd ?? null,
    };
    if (typeof res.cost_usd === "number") this.#deps.onInvocationCost(res.cost_usd);
    this.#persistAcceptedInvocation(run.entry, null);
  }

  // Follow the open note list like #watchLineEdits: keep the count and the checked
  // range current, and close the review when the last note is gone (no telemetry -
  // it was recorded on arrival).
  #watchLineNotes(editor: Editor): void {
    const onTransaction = editorCallback(({ transaction }: { transaction: Transaction }) => {
      if (transaction.docChanged && this.#lineEditRange) {
        this.#lineEditRange = {
          from: transaction.mapping.map(this.#lineEditRange.from, 1),
          to: transaction.mapping.map(this.#lineEditRange.to, -1),
        };
      }
      if (lineNoteState(editor.state).notes.length > 0) {
        this.#syncLineNotes(editor);
        return;
      }
      this.meta = null;
      this.#closeLineEdits();
      this.toolbarPosition = { x: 0, y: 0, visible: false };
    });
    editor.on("transaction", onTransaction);
    this.#stopWatchingLineEdits = () => editor.off("transaction", onTransaction);
  }

  #syncLineNotes(editor: Editor): void {
    const { notes } = lineNoteState(editor.state);
    const current = currentLineNote(editor.state);
    if (!current) return;
    const next = { remaining: notes.length, index: notes.indexOf(current) + 1, checkedAgainst: this.#checkedAgainst };
    const old = this.lineNotes;
    if (old && old.remaining === next.remaining && old.index === next.index && old.checkedAgainst === next.checkedAgainst) {
      return;
    }
    this.lineNotes = next;
  }

  dismissAllLineNotes(): void {
    const editor = this.#deps.getEditor();
    if (editor && this.lineNotes) dismissAllLineNotes(editor.view);
  }

  dismissCurrentLineNote(): void {
    const editor = this.#deps.getEditor();
    if (editor && this.lineNotes) dismissCurrentLineNote(editor.view);
  }

  nextLineNote(): void {
    const editor = this.#deps.getEditor();
    if (editor && this.lineNotes) stepLineNote(editor.view, 1);
  }

  prevLineNote(): void {
    const editor = this.#deps.getEditor();
    if (editor && this.lineNotes) stepLineNote(editor.view, -1);
  }

  // The line-edits handler's `apply`: one non-streaming call, then the edits are
  // placed on the selection and handed to the review plugin. The document is not
  // touched until the writer accepts an edit.
  async #runLineEdits(gathered: InlineGathered, run: OutputRun): Promise<void> {
    const editor = this.#deps.getEditor();
    if (!editor) return;
    const { from, to, selectionText } = gathered;
    const { entry, inputs, assistantId, scene } = run;
    const epoch = this.#runEpoch;
    const abort = new AbortController();
    this.#abort = abort;
    const { signal } = abort;
    try {
      // The edit list is read whole, so the deltas are ignored - but the call rides
      // the streaming route because only a stream's disconnect reaches the provider
      // and stops it (#2464). The terminal `done` carries the parsed edits.
      let res: Extract<AIStreamEvent, { type: "done" }> | null = null;
      let streamError: string | null = null;
      for await (const ev of api.aiGenerateStream({
        template_source: entry.body,
        target_scene_id: this.#sceneIdForWire(scene),
        session_id: scene.id,
        inputs,
        resolution_scene_id: resolutionSceneIdFromInputs(entry, inputs),
        ...gatheredRequestFields(gathered),
        ...(assistantId ? { assistant_id: assistantId } : {}),
        commit: false,
        response_format: "line_edits",
      }, signal)) {
        if (signal.aborted) break;
        if (ev.type === "done") res = ev;
        else if (ev.type === "error") streamError = ev.error || "Unknown error";
      }
      // Cancelled (#2464): drop the reply, even one that raced the abort.
      if (signal.aborted) {
        this.#noteLineEditCancelled(epoch);
        return;
      }
      // The writer switched documents mid-call: this reply isn't theirs to see.
      if (epoch !== this.#runEpoch || this.#deps.getScene()?.id !== scene.id) return;
      if (streamError !== null || !res) {
        this.error = streamError ?? "The model's reply ended before it finished.";
        return;
      }
      if (res.ok === false) {
        this.error = res.error || "Unknown error";
        return;
      }
      if (editor.state.doc.textBetween(from, to, "\n\n", " ") !== selectionText) {
        this.error = "Document changed during the AI call. Re-select the text and retry.";
        return;
      }
      if (typeof res.cost_usd === "number") this.#deps.onInvocationCost(res.cost_usd);
      const { placed, dropped } = placeLineEdits(editor.state.doc, from, to, res.edits ?? []);
      this.#anchorPos = null;
      if (placed.length === 0) {
        this.#deps.onNotice?.(
          dropped > 0 ? `None of the ${dropped} suggested edits could be placed.` : "No edits suggested.",
        );
        return;
      }
      this.meta = {
        provider: res.provider,
        model: res.model,
        latency_ms: res.latency_ms,
        truncated: res.truncated,
        wordCount: placed.length,
        usage: res.usage ?? null,
        cost_usd: res.cost_usd ?? null,
      };
      this.#lineEditRange = { from, to };
      installLineEdits(editor.view, placed, to, {
        keep: (view, edit) => void this.#keepFlag(view, edit.id, edit.from, edit.to, edit.find, editKeepNote(edit.reason, edit.replace)),
      });
      this.#syncLineEdits(editor);
      this.#watchLineEdits(editor);
      if (dropped > 0) {
        this.#deps.onNotice?.(
          `${dropped} edit${dropped === 1 ? "" : "s"} couldn't be matched to the text and ${dropped === 1 ? "was" : "were"} skipped.`,
        );
      }
    } catch (e) {
      if (signal.aborted) this.#noteLineEditCancelled(epoch);
      else this.error = (e as Error).message;
    } finally {
      if (this.#abort === abort) this.#abort = null;
      this.generating = false;
      this.updateToolbarPosition();
    }
  }

  #noteLineEditCancelled(epoch: number): void {
    if (epoch === this.#runEpoch) this.#deps.onNotice?.("Line edit cancelled.");
  }

  // Follow the open edit list: keep the remaining count and the revised range
  // current as the writer resolves edits or types, and close the list when the
  // last edit is gone. It writes $state, so it goes through editorCallback
  // (#2461): a transaction can fire inside a block teardown's reaction.
  #watchLineEdits(editor: Editor): void {
    const onTransaction = editorCallback(({ transaction }: { transaction: Transaction }) => {
      if (transaction.docChanged && this.#lineEditRange) {
        this.#lineEditRange = {
          from: transaction.mapping.map(this.#lineEditRange.from, 1),
          to: transaction.mapping.map(this.#lineEditRange.to, -1),
        };
      }
      const { edits, accepted, kept } = lineEditState(editor.state);
      if (edits.length > 0) {
        this.#syncLineEdits(editor);
        return;
      }
      // Resolved or dropped to nothing. Telemetry once, and only if the writer
      // took at least one edit: accepted, or kept as a TODO.
      if (accepted > 0 || kept > 0) {
        this.#persistAcceptedInvocation(findPromptEntry(this.#deps.getPromptCtx(), this.#lastInvokedEntryId), null);
      }
      this.meta = null;
      this.#closeLineEdits();
      this.toolbarPosition = { x: 0, y: 0, visible: false };
    });
    editor.on("transaction", onTransaction);
    this.#stopWatchingLineEdits = () => editor.off("transaction", onTransaction);
  }

  // Publish the plugin's view of the open list (count, current place, reason),
  // writing only on change so unrelated transactions don't churn the bar.
  #syncLineEdits(editor: Editor): void {
    this.lineEditView = reviewState(editor.state).view;
    const { edits } = lineEditState(editor.state);
    const current = currentLineEdit(editor.state);
    if (!current) return;
    const next = {
      remaining: edits.length,
      index: edits.indexOf(current) + 1,
      currentReason: current.reason,
    };
    const old = this.lineEdits;
    if (old && old.remaining === next.remaining && old.index === next.index && old.currentReason === next.currentReason) {
      return;
    }
    this.lineEdits = next;
  }

  #closeLineEdits(): void {
    this.#stopWatchingLineEdits?.();
    this.#stopWatchingLineEdits = null;
    this.#lineEditRange = null;
    this.lineEdits = null;
    this.lineNotes = null;
    this.flags = null;
  }

  // ---------- Flags placed from a conversation (ADR-0100) ----------
  // Called from outside the pane (the chat's Place flags) once the scene has
  // loaded. An open review of either sort closes first, as a new run replaces it.
  installConversationFlags(flags: SceneFlags): void {
    const editor = this.#deps.getEditor();
    if (!editor || editor.isDestroyed) return;
    // Place first: an open review is only replaced when there is something to
    // put in its place (placing reads the document, it doesn't change it).
    const { edits, notes, dropped, total } = placeSceneFlags(editor.state.doc, flags);
    const notice = flagsNotice(dropped, total);
    if (edits.length + notes.length === 0) {
      if (notice) this.#deps.onNotice?.(notice);
      return;
    }
    this.#stopWatchingLineEdits?.();
    this.#stopWatchingLineEdits = null;
    rejectAllFlags(editor.view);
    this.#closeLineEdits();
    this.meta = null;
    const names = flagEntryNames(flags);
    const editKind = editsKind({
      keep: (view, edit) => void this.#keepFlag(view, edit.id, edit.from, edit.to, edit.find, editKeepNote(edit.reason, edit.replace)),
    });
    const noteKind = notesKind({
      openEntry: (id) => this.#deps.onOpenEntry?.(id),
      entryName: (id) => names.get(id) ?? "",
      keep: (view, note) =>
        void this.#keepFlag(view, note.id, note.from, note.to, note.quote, noteKeepNote(note.problem, names.get(note.entry) ?? "")),
    });
    installFlags(editor.view, [
      ...edits.map((e) => ({ ...e, kind: editKind })),
      ...notes.map((n) => ({ ...n, kind: noteKind })),
    ]);
    this.#syncFlags(editor);
    this.#watchFlags(editor);
    if (notice) this.#deps.onNotice?.(notice);
  }

  // Follow the open review like #watchLineEdits, over items of either kind: keep
  // the count current and close the run when none is left. Cost was recorded by
  // the backend on the chat, so there is no telemetry to write here.
  #watchFlags(editor: Editor): void {
    const onTransaction = editorCallback(() => {
      if (reviewState(editor.state).items.length > 0) {
        this.#syncFlags(editor);
        return;
      }
      this.#closeLineEdits();
    });
    editor.on("transaction", onTransaction);
    this.#stopWatchingLineEdits = () => editor.off("transaction", onTransaction);
  }

  #syncFlags(editor: Editor): void {
    this.lineEditView = reviewState(editor.state).view;
    const { items, currentId } = reviewState(editor.state);
    const at = items.findIndex((i) => i.id === currentId);
    if (at < 0) return;
    const next = { remaining: items.length, index: at + 1, edits: items.filter((i) => i.kind.name === "edits").length };
    const old = this.flags;
    if (old && old.remaining === next.remaining && old.index === next.index && old.edits === next.edits) return;
    this.flags = next;
  }

  acceptAllFlagEdits(): void {
    const editor = this.#deps.getEditor();
    if (editor && this.flags) acceptAllLineEdits(editor.view);
  }

  rejectAllFlags(): void {
    const editor = this.#deps.getEditor();
    if (editor && this.flags) rejectAllFlags(editor.view);
  }

  nextFlag(): void {
    const editor = this.#deps.getEditor();
    if (editor && this.flags) stepReview(editor.view, 1);
  }

  prevFlag(): void {
    const editor = this.#deps.getEditor();
    if (editor && this.flags) stepReview(editor.view, -1);
  }

  // The bar's Current / Proposed / Both: same view as Alt+A / Alt+S / Alt+B.
  setLineEditView(view: ReviewView): void {
    const editor = this.#deps.getEditor();
    if (editor && !editor.isDestroyed && (this.lineEdits || this.flags)) setReviewView(view, editor.view);
  }

  acceptAllLineEdits(): void {
    const editor = this.#deps.getEditor();
    if (editor && this.lineEdits) acceptAllLineEdits(editor.view);
  }

  rejectAllLineEdits(): void {
    const editor = this.#deps.getEditor();
    if (editor && this.lineEdits) rejectAllLineEdits(editor.view);
  }

  nextLineEdit(): void {
    const editor = this.#deps.getEditor();
    if (editor && this.lineEdits) stepLineEdit(editor.view, 1);
  }

  prevLineEdit(): void {
    const editor = this.#deps.getEditor();
    if (editor && this.lineEdits) stepLineEdit(editor.view, -1);
  }

  acceptCurrentLineEdit(): void {
    const editor = this.#deps.getEditor();
    if (editor && this.lineEdits) acceptCurrentLineEdit(editor.view);
  }

  rejectCurrentLineEdit(): void {
    const editor = this.#deps.getEditor();
    if (editor && this.lineEdits) rejectCurrentLineEdit(editor.view);
  }

  // Retry for an open edit list: drop what's left and ask again on the same text.
  async #retryLineEdits(): Promise<void> {
    const editor = this.#deps.getEditor();
    const range = this.#lineEditRange;
    const entry = findPromptEntry(this.#deps.getPromptCtx(), this.#lastInvokedEntryId);
    if (!editor || !range || this.generating) return;
    if (!entry) {
      this.error = "Original prompt is no longer available.";
      return;
    }
    this.rejectAllLineEdits();
    this.dismissAllLineNotes();
    editor.chain().focus().setTextSelection(range).run();
    await this.runPromptEntry(entry, this.#lastInvokedInputs, this.#lastInvokedAssistantId);
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
    const { from, to, selectionText, destination } = gathered;
    const { entry, inputs, assistantId, scene } = run;

    // A beat-marking prompt (roleplay, via on_accept) may deliver two parts —
    // visible prose then `[[interiority]]` then private inner state (ADR-0070).
    // Only the external part is ever rendered; the internal is stashed for accept.
    const carriesInteriority = Boolean(promptOnAccept(this.#deps.getPromptCtx(), entry));
    this.#pendingInternal = null;

    const suggestionId = `ai-${this.#nextSuggestionId++}`;
    let startPos = from;
    // The prose either side of the caret, for a cursor insert (#2459).
    let caretBefore = "";
    let caretAfter = "";
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
    const abort = new AbortController();
    this.#abort = abort;
    const { signal } = abort;

    // Throttled render (#2428). The render replaces the whole suggestion with the
    // latest text, so dropping intermediate states is safe. The first delta renders
    // at once; later ones within RENDER_WINDOW_MS coalesce into one timer render.
    // Never renders once the suggestion is gone (revert/reset/error).
    let pendingVisible: string | null = null;
    const renderPending = () => {
      const visible = pendingVisible;
      pendingVisible = null;
      if (visible === null || this.suggestionId !== suggestionId) return false;
      this.#renderStreamingSuggestion(startPos, visible, suggestionId);
      return true;
    };
    const tick = () => {
      this.#renderTimer = null;
      if (renderPending()) this.#renderTimer = setTimeout(tick, RENDER_WINDOW_MS);
    };
    const scheduleRender = (visible: string) => {
      pendingVisible = visible;
      if (this.#renderTimer !== null) return;
      renderPending();
      this.#renderTimer = setTimeout(tick, RENDER_WINDOW_MS);
    };
    const flushRender = () => {
      this.#cancelRenderTimer();
      renderPending();
    };

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
        // The caret's own block around it (#2459); a leaf (a pill, a line
        // break) reads as U+FFFC, which never asks for a space.
        const caret = editor.state.doc.resolve(startPos);
        const block = caret.parent;
        caretBefore = block.textBetween(0, caret.parentOffset, undefined, "\ufffc");
        caretAfter = block.textBetween(caret.parentOffset, block.content.size, undefined, "\ufffc");
      }
      this.suggestionId = suggestionId;
      streamingActive = true;
    };

    // Take the streamed text back out: the displaced selection returns, or a
    // cursor insert is removed. Shared by the stream's error and a cancel (#2464).
    const revertStreamed = () => {
      this.#cancelRenderTimer();
      pendingVisible = null;
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
    };

    try {
      for await (const ev of api.aiGenerateStream({
        template_source: entry.body,
        target_scene_id: this.#sceneIdForWire(scene),
        session_id: scene.id,
        inputs,
        resolution_scene_id: resolutionSceneIdFromInputs(entry, inputs),
        ...gatheredRequestFields(gathered),
        ...(assistantId ? { assistant_id: assistantId } : {}),
        commit: false,
      }, signal)) {
        if (signal.aborted) break;
        if (ev.type === "delta") {
          accumulated += ev.text;
          ensureStreamingStarted();
          if (streamErrored) break;
          if (!editor) break;
          const visible = carriesInteriority ? visibleExternal(accumulated) : accumulated;
          scheduleRender(
            destination === "cursor" ? joinAtCursor(caretBefore, visible, caretAfter) : visible,
          );
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
          revertStreamed();
        }
      }
      if (signal.aborted) {
        streamErrored = true;
        revertStreamed();
      }
      if (!streamErrored) flushRender();
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
      if (signal.aborted) {
        revertStreamed();
      } else {
        flushRender(); // keep what streamed so far on screen, as per-delta rendering did
        this.error = (e as Error).message;
      }
    } finally {
      if (this.#abort === abort) this.#abort = null;
      this.#cancelRenderTimer();
      this.generating = false;
      this.updateToolbarPosition();
    }
  }
}
