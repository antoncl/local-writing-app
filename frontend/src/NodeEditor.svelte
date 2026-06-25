<script lang="ts">
  import { createEventDispatcher, onMount } from "svelte";
  import { Editor, Mark, mergeAttributes } from "@tiptap/core";
  import { Fragment, type Node as ProseMirrorNode } from "@tiptap/pm/model";
  import { TextSelection } from "@tiptap/pm/state";
  import type { EditorView } from "@tiptap/pm/view";
  import StarterKit from "@tiptap/starter-kit";
  import Table from "@tiptap/extension-table";
  import TableCell from "@tiptap/extension-table-cell";
  import TableHeader from "@tiptap/extension-table-header";
  import TableRow from "@tiptap/extension-table-row";
  import { editorHtmlToSceneMarkdown, sceneMarkdownToHtml } from "./markdown";
  import { sanitizePastedHtml } from "./sanitizePastedHtml";
  import { ImplicitContextHighlight, REBUILD_META } from "./implicitContextHighlight";
  import CodeEditor from "./CodeEditor.svelte";
  import NodePickerConfigEditor from "./NodePickerConfigEditor.svelte";
  import MetadataLongTextEditor from "./MetadataLongTextEditor.svelte";
  import ProviderTierPicker from "./ProviderTierPicker.svelte";
  import NodeList from "./NodeList.svelte";
  import NodeRow from "./NodeRow.svelte";
  import ReferencePicker from "./ReferencePicker.svelte";
  import SwatchPicker from "./SwatchPicker.svelte";
  import ColoredSelect from "./ColoredSelect.svelte";
  import { resolveColor } from "./colors";
  import type { StructureNode } from "./types";
  import { api, HttpError } from "./api";
  import { formatCostEur, formatTokens } from "./money";
  import PromptInputField from "./PromptInputField.svelte";
  import type { AIPreviewResponse, AssistantEntrySummary, Backlink, ChatUsage, EditableDocument, EntryBodyLanguage, EntryMetadata, MetadataFieldDefinition, MetadataSchema, MetadataValue, PromptEntrySummary, PromptInputDefinition } from "./types";

  export let scene: EditableDocument | null = null;
  export let documentKind: "scene" | "lore" | "prompt" | "snippet" | "assistant" | "project" | "structure_node" = "scene";
  export let metadataSchema: MetadataSchema | null = null;
  export let promptEntries: PromptEntrySummary[] = [];
  // Data sources for context_pick inputs in the prompt preview / inputs
  // dialog. Optional — the picker degrades to "no items" when missing.
  export let structure: import("./types").StructureDocument | null = null;
  export let loreEntries: import("./types").LoreEntrySummary[] = [];
  export let knownTags: string[] = [];
  // Optional matcher pass-through for the implicit-context highlight
  // plugin on long-text metadata fields. App.svelte owns the compile.
  export let implicitContextMatcher: import("./implicitContextMatcher").CompiledMatcher | null = null;
  export let assistantEntries: AssistantEntrySummary[] = [];
  export let defaultAssistantId: string = "";
  // Scenes available for the inline prompt-preview scene picker. The pane is
  // host-agnostic — App.svelte derives this from its structure tree.
  export let availableScenes: { id: string; title: string }[] = [];
  export let metadataReload: { token: number; metadata: EntryMetadata; status?: string; entryType: string } | null = null;
  export let titleReload: { token: number; title: string } | null = null;
  export let dirty = false;
  export let todoStatusHint = "";

  const dispatch = createEventDispatcher<{
    change: { title: string; bodyMarkdown: string; status: string; entryType: string; metadata: EntryMetadata; inputs?: PromptInputDefinition[] };
    focus: void;
    "custom-data": { entryType: string; kind: "scene" | "lore" | "prompt" | "assistant" };
    embeddedTodos: { todos: EmbeddedTodo[] };
    navigate: { id: string; kind: string };
    "open-chat": { entry: PromptEntrySummary; inputs: Record<string, unknown>; sceneId: string | null; assistantId: string };
  }>();

  type FloatingMenuState = {
    visible: boolean;
    x: number;
    y: number;
    wordCount: number;
    placement: "above" | "below";
  };
  type SlashMenuState = {
    visible: boolean;
    x: number;
    y: number;
    selectedIndex: number;
    mode: "commands" | "table-grid";
    gridRows: number;
    gridCols: number;
  };
  type SlashCommand = {
    label: string;
    description: string;
    group: string;
    // Optional canonical single-word command name. Defaults to label.
    // Used as the Tab-autocomplete target so `/rol[Tab]` becomes
    // `/roleplay ` (single word + space) instead of `/Untitled Prompt `
    // — gives shell-style completion without breaking the
    // `command + space + args` parse shape.
    autocompleteTo?: string;
    run: (args?: string[]) => void | Promise<void>;
  };

  const TABLE_GRID_MAX_ROWS = 8;
  const TABLE_GRID_MAX_COLS = 8;

  // How much surrounding text to send when a revise prompt runs on a selection.
  const REVISE_CONTEXT_CHARS = 600;

  type ToolbarButtonAction = {
    kind: "button";
    id: string;
    label: string;
    run: () => void | Promise<void>;
  };
  type ToolbarMenuAction = {
    kind: "menu";
    id: string;
    label: string;
    items: Array<{
      id: string;
      label: string;
      run: () => void | Promise<void>;
    }>;
  };
  type ToolbarAction = ToolbarButtonAction | ToolbarMenuAction;
  type BlockWrapType = "blockquote" | "bulletList" | "orderedList";
  export type EmbeddedTodo = {
    id: string;
    text: string;
    status: "open" | "done";
    note: string;
  };

  const WORD_PATTERN = /[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?/g;

  const AISuggestion = Mark.create({
    name: "aiSuggestion",
    inclusive: false,
    excludes: "",
    addAttributes() {
      return {
        suggestionId: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-ai-suggestion-id"),
          renderHTML: (attributes) => {
            if (!attributes.suggestionId) return {};
            return { "data-ai-suggestion-id": attributes.suggestionId };
          },
        },
      };
    },
    parseHTML() {
      return [{ tag: "span[data-ai-suggestion-id]" }];
    },
    renderHTML({ HTMLAttributes }) {
      return ["span", mergeAttributes(HTMLAttributes, { class: "ai-suggestion" }), 0];
    },
  });

  // Per-character mark color. Walks the full resolver: instance
  // (metadata.color on the lore entry) → entry-type color → parent
  // chain → kind-default. Only falls back to the deterministic hash
  // when the resolver returns null — so authors who set an explicit
  // color get it, but uncolored characters still get a stable hue.
  // Reads loreEntries + metadataSchema from the enclosing component
  // scope; runs each time TipTap renders the mark, so changes flow
  // through on next render (re-open scene if a colored character's
  // mark looks stale).
  function characterColorFromId(id: string): string {
    const entry = loreEntries.find((e) => e.id === id);
    const instanceColor = typeof entry?.metadata?.color === "string" ? entry.metadata.color : null;
    const swatch = resolveColor(instanceColor, entry?.entry_type, "lore", metadataSchema);
    if (swatch) return swatch.hex;
    // Hash fallback for entries with no resolved color (no instance,
    // no type, no kind default). Stable across reloads — no randomness.
    let hash = 0;
    for (let i = 0; i < id.length; i++) {
      hash = (hash * 31 + id.charCodeAt(i)) | 0;
    }
    const hue = ((hash % 360) + 360) % 360;
    return `hsl(${hue}, 62%, 48%)`;
  }

  // Resolve a backlink's color through the full chain: instance override
  // → entry-type → parent chain → kind-default. Returns null only if
  // every leg comes up empty (uncolored kind with no schema color).
  function findStructureNodeBySceneId(node: StructureNode | null | undefined, sceneId: string): StructureNode | null {
    if (!node) return null;
    if (node.scene_id === sceneId) return node;
    for (const child of node.children ?? []) {
      const hit = findStructureNodeBySceneId(child, sceneId);
      if (hit) return hit;
    }
    return null;
  }

  function backlinkSwatchHex(link: Backlink): string | null {
    let instanceColor: string | null | undefined = null;
    if (link.kind === "lore") {
      const entry = loreEntries.find((e) => e.id === link.id);
      instanceColor = typeof entry?.metadata?.color === "string" ? entry.metadata.color : null;
    } else if (link.kind === "scene") {
      instanceColor = findStructureNodeBySceneId(structure?.root, link.id)?.color ?? null;
    }
    return resolveColor(instanceColor, link.entry_type, link.kind, metadataSchema)?.hex ?? null;
  }

  // Spans tagged with a character lore id (`data-character="<lore-id>"`).
  // `inclusive: false` so typing at the boundary of a character's span
  // doesn't extend the tag over the author's surrounding narration —
  // critical for the per-character send-time reconstruction (next slice).
  const CharacterMark = Mark.create({
    name: "character",
    inclusive: false,
    excludes: "",
    addAttributes() {
      return {
        characterId: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-character"),
          renderHTML: (attributes) => {
            if (!attributes.characterId) return {};
            const id = String(attributes.characterId);
            return {
              "data-character": id,
              style: `--character-color: ${characterColorFromId(id)}`,
            };
          },
        },
      };
    },
    parseHTML() {
      return [{ tag: "span[data-character]" }];
    },
    renderHTML({ HTMLAttributes }) {
      return ["span", mergeAttributes(HTMLAttributes, { class: "character-mark" }), 0];
    },
  });

  const TodoAnchor = Mark.create({
    name: "todoAnchor",
    inclusive: false,
    addAttributes() {
      return {
        anchorId: {
          default: null,
          parseHTML: (element) => element.getAttribute("data-todo-id") ?? element.getAttribute("data-todo-anchor-id"),
          renderHTML: (attributes) => {
            if (!attributes.anchorId) return {};
            return { "data-todo-id": attributes.anchorId };
          },
        },
        status: {
          default: "open",
          parseHTML: (element) => (element.getAttribute("data-todo-status") === "done" ? "done" : "open"),
          renderHTML: (attributes) => ({ "data-todo-status": attributes.status === "done" ? "done" : "open" }),
        },
        note: {
          default: "",
          parseHTML: (element) => element.getAttribute("data-todo-note") ?? "",
          renderHTML: (attributes) => ({ "data-todo-note": attributes.note ?? "" }),
        },
      };
    },
    parseHTML() {
      return [{ tag: "span[data-todo-id]" }, { tag: "span[data-todo-anchor-id]" }];
    },
    renderHTML({ HTMLAttributes }) {
      return ["span", mergeAttributes(HTMLAttributes, { class: "todo-anchor" }), 0];
    },
  });

  let editorFrame: HTMLDivElement;
  let editorElement: HTMLDivElement;
  let editor: Editor | null = null;
  let loadedSceneId: string | null = null;
  let rawBody = "";
  let lastEmittedRawBody = "";
  $: entryTypeDef = metadataSchema?.entry_types[entryType] ?? null;
  $: rawBodyMode = (entryTypeDef?.body_editor ?? "wysiwyg") === "code";
  $: rawBodyLanguage = (entryTypeDef?.body_language ?? "markdown") satisfies EntryBodyLanguage;
  $: if (rawBodyMode && rawBody !== lastEmittedRawBody) {
    lastEmittedRawBody = rawBody;
    emitChange();
  }
  let title = "";
  let status = "draft";
  let entryType = "scene";
  let metadata: EntryMetadata = {};
  let liveWordCount = 0;
  let metadataSummaryText = "";
  let metadataExpanded = false;
  let editorEmpty = true;
  let selectionMenu: FloatingMenuState = { visible: false, x: 0, y: 0, wordCount: 0, placement: "above" };
  let slashMenu: SlashMenuState = { visible: false, x: 0, y: 0, selectedIndex: 0, mode: "commands", gridRows: 1, gridCols: 1 };
  let tableMenu: { visible: boolean; x: number; y: number } = { visible: false, x: 0, y: 0 };
  let openToolbarMenuId: string | null = null;
  let reconcilingTodoAnchors = false;
  let highlightedTodoId: string | null = null;
  let lastMetadataReloadToken = 0;
  let lastTitleReloadToken = 0;
  let tagPickerFieldId: string | null = null;
  let tagPickerPosition: { x: number; y: number; width: number } | null = null;
  let backlinks: Backlink[] = [];
  let backlinksExpanded = false;
  let lastBacklinksSceneId: string | null = null;

  // AI suggestion state. v1 supports a single pending suggestion at a time.
  let aiGenerating = false;
  let aiError: string | null = null;
  let aiSuggestionId: string | null = null;
  let aiSuggestionMeta: {
    provider: string;
    model: string;
    latency_ms: number;
    truncated: boolean;
    wordCount: number;
    usage?: ChatUsage | null;
    cost_usd?: number | null;
  } | null = null;
  // V2: per-scene continuation cost rollup. Frontend-only — resets when
  // you switch scenes or reload the page. Phase C will add server-side
  // persistence (a scene-level `cost_usd_total` mirroring ChatSession's).
  // The diff-review toolbar's cost line disappears the moment you Accept,
  // so without this chip the cost would never have a lasting home.
  let lastInvocationCostUsd: number | null = null;
  let sceneSessionCostUsd = 0;
  let lastSeenSceneIdForCost: string | null = null;
  let aiToolbarPosition: { x: number; y: number; visible: boolean } = { x: 0, y: 0, visible: false };
  let aiNextSuggestionId = 1;
  // For revisions: the original selected text to restore on discard. null for continuations.
  let aiSuggestionOriginal: string | null = null;
  // ProseMirror position to anchor the toolbar to BEFORE a suggestion exists
  // (while generating or after a failure). null when the suggestion's own range
  // is the anchor.
  let aiAnchorPos: number | null = null;
  let lastInvokedEntryId: string | null = null;
  let lastInvokedInputs: Record<string, unknown> = {};
  let inputsDialogEntry: PromptEntrySummary | null = null;
  // Inline error inside the inputs dialog — populated when a positional
  // arg (e.g. from `/roleplay Irene`) failed to resolve so the user can
  // see WHY the dialog opened instead of firing directly.
  let inputsDialogError: string | null = null;
  let inputsDialogDrafts: Record<string, string> = {};
  // "" means: use the user's default assistant (resolved server-side).
  let inputsDialogAssistantId: string = "";
  let lastInvokedAssistantId: string = "";
  // V2: token + cost estimate for the about-to-fire continuation. Mirrors
  // App.svelte's `chatEstimate`. Recomputed when the dialog's prompt /
  // drafts / assistant change. Null when the dialog is closed.
  let inputsDialogEstimate: {
    tokens: number;
    cost_usd: number | null;
    caching_style: "none" | "auto" | "explicit" | null;
    cache_blocks: { label: string; tokens: number; cache_break_after: boolean }[];
  } | null = null;
  // Stale-response guard: bump on every fetch, discard any earlier in-flight
  // response whose token doesn't match the latest.
  let inputsDialogEstimateToken = 0;

  // --- Per-entry prompt inputs editor (declaration side) ---
  // Inputs live on the entry now, not the entry-type. The drafts here are the
  // editor-side form state; on every edit we rebuild the canonical
  // PromptInputDefinition[] and emit it as part of the change event. App.svelte
  // stores it on the pane and persists on save.
  type EntryInputDraft = {
    // Stable key for the {#each} block. Not persisted — generated on add /
    // seed so that reordering the drafts moves the keyed component along
    // with the data (otherwise per-row internal state like NodePicker's
    // collapsed flag stays anchored to the position, not the input).
    clientId: string;
    name: string;
    type: import("./types").PromptInputType;
    label: string;
    defaultValue: string;
    options: string; // comma-separated for select
    required: boolean;
    targetKind: "" | "scene" | "lore";
    targetEntryType: string;
    // Carries the per-input config for type === "context_pick". When the
    // user picks any other type this draft field is ignored at serialize
    // time (entryInputDraftsToCanonical drops it unless type matches).
    nodePickerConfig: import("./types").NodePickerConfig;
    nameDerived: boolean;
  };
  let entryInputDrafts: EntryInputDraft[] = [];
  let entryInputDraftCounter = 0;
  function nextInputDraftId(): string {
    entryInputDraftCounter += 1;
    return `__input_${entryInputDraftCounter}`;
  }
  let entryInputsExpanded = false;
  let cheatsheetPopoverOpen = false;
  let helpButtonEl: HTMLButtonElement | undefined;
  let popoverPos = { top: 0, right: 8 };

  function toggleCheatsheetPopover() {
    if (!cheatsheetPopoverOpen && helpButtonEl) {
      const r = helpButtonEl.getBoundingClientRect();
      // Match the CSS max-height (70vh) so we don't clip below the viewport;
      // open below the button if it fits, otherwise pin near the top of the
      // viewport with an 8px margin.
      const maxPopHeight = Math.round(window.innerHeight * 0.7);
      const desiredTop = Math.round(r.bottom + 6);
      const safeTop = Math.min(desiredTop, Math.max(8, window.innerHeight - maxPopHeight - 8));
      popoverPos = {
        top: safeTop,
        right: Math.max(8, Math.round(window.innerWidth - r.right)),
      };
    }
    cheatsheetPopoverOpen = !cheatsheetPopoverOpen;
  }
  // Seed drafts from the scene prop. scene only changes when a different entry
  // is opened or after a save; the user's typing updates entryInputDrafts
  // locally without touching scene, so this won't fight in-flight edits.
  // Reactive identity key: when scene reference changes (different entry),
  // re-seed. We compare via scene id rather than reference because Svelte may
  // pass the same object reference between renders.
  let lastSeededSceneId: string | null = null;
  $: maybeReseedInputs(scene, documentKind);

  function maybeReseedInputs(currentScene: typeof scene, currentKind: typeof documentKind): void {
    if (currentKind !== "prompt" || !currentScene) {
      lastSeededSceneId = null;
      return;
    }
    if (currentScene.id === lastSeededSceneId) return;
    const sceneInputs = ((currentScene as unknown as PromptEntrySummary).inputs ?? []);
    entryInputDrafts = sceneInputs.map(inputDefinitionToDraft);
    lastSeededSceneId = currentScene.id;
  }

  function inputDefinitionToDraft(input: PromptInputDefinition): EntryInputDraft {
    const targetKindRaw = (input.target as { kind?: unknown } | null | undefined)?.kind;
    const targetEntryTypeRaw = (input.target as { entry_type?: unknown } | null | undefined)?.entry_type;
    const nodePickerConfig =
      input.type === "context_pick" && input.target && typeof input.target === "object"
        ? (input.target as unknown as import("./types").NodePickerConfig)
        : ({ kinds: [], presets: [], multiple: true } as import("./types").NodePickerConfig);
    return {
      clientId: nextInputDraftId(),
      name: input.name,
      type: input.type,
      label: input.label ?? "",
      defaultValue: input.default === undefined || input.default === null ? "" : String(input.default),
      options: (input.options ?? []).map((o) => o.value).join(", "),
      required: Boolean(input.required),
      targetKind: targetKindRaw === "scene" || targetKindRaw === "lore" ? (targetKindRaw as "scene" | "lore") : "",
      targetEntryType: typeof targetEntryTypeRaw === "string" ? targetEntryTypeRaw : "",
      nodePickerConfig,
      nameDerived: false,
    };
  }

  function entrySlugify(value: string): string {
    return value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^[0-9]/, "input_$&");
  }

  function entryInputDraftsToCanonical(drafts: EntryInputDraft[]): PromptInputDefinition[] {
    return drafts
      .filter((d) => d.name)
      .map((d) => {
        const out: PromptInputDefinition = {
          name: d.name,
          type: d.type,
        };
        if (d.label) out.label = d.label;
        if (d.required) out.required = true;
        if (d.type === "context_pick") {
          // Serialize the rich config into `target`. Skip default / options
          // (they don't apply); skip targetKind / targetEntryType (those
          // are for entity_ref types).
          out.target = d.nodePickerConfig as unknown as Record<string, import("./types").MetadataValue>;
          return out;
        }
        if (d.defaultValue !== "") out.default = d.defaultValue;
        if (d.type === "select") {
          // Emit SelectOption objects; colors aren't editable from the
          // prompt-input draft surface today (Phase 3 adds them to the
          // Detail Field editor for metadata-level selects).
          out.options = d.options
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean)
            .map((value) => ({ value }));
        }
        const target: Record<string, string> = {};
        if (d.targetKind) target.kind = d.targetKind;
        if (d.targetEntryType) target.entry_type = d.targetEntryType;
        if (Object.keys(target).length > 0) out.target = target;
        return out;
      });
  }

  function emitInputsChange(): void {
    if (!scene) return;
    const canonical = entryInputDraftsToCanonical(entryInputDrafts);
    dispatch("change", {
      title,
      bodyMarkdown: rawBodyMode ? rawBody : (editor ? editorHtmlToSceneMarkdown(editor.getHTML()) : ""),
      status,
      entryType,
      metadata: cloneMetadata(metadata),
      inputs: canonical,
    });
  }

  function addEntryInput(): void {
    entryInputDrafts = [
      ...entryInputDrafts,
      {
        clientId: nextInputDraftId(),
        name: "",
        type: "text",
        label: "",
        defaultValue: "",
        options: "",
        required: false,
        targetKind: "",
        targetEntryType: "",
        nodePickerConfig: { kinds: [], presets: [], multiple: true },
        nameDerived: true,
      },
    ];
    emitInputsChange();
  }

  function updateEntryInputNodePickerConfig(
    index: number,
    config: import("./types").NodePickerConfig,
  ): void {
    updateEntryInput(index, { nodePickerConfig: config });
  }

  function removeEntryInput(index: number): void {
    entryInputDrafts = entryInputDrafts.filter((_, i) => i !== index);
    emitInputsChange();
  }

  function updateEntryInputLabel(index: number, label: string): void {
    entryInputDrafts = entryInputDrafts.map((draft, i) => {
      if (i !== index) return draft;
      const next = { ...draft, label };
      if (draft.nameDerived) next.name = entrySlugify(label);
      return next;
    });
    emitInputsChange();
  }

  function updateEntryInputName(index: number, name: string): void {
    entryInputDrafts = entryInputDrafts.map((draft, i) =>
      i !== index ? draft : { ...draft, name: entrySlugify(name), nameDerived: false },
    );
    emitInputsChange();
  }

  function updateEntryInput(index: number, patch: Partial<EntryInputDraft>): void {
    entryInputDrafts = entryInputDrafts.map((draft, i) =>
      i !== index ? draft : { ...draft, ...patch },
    );
    emitInputsChange();
  }

  function moveEntryInput(from: number, to: number): void {
    if (from === to || from < 0 || to < 0) return;
    if (from >= entryInputDrafts.length || to >= entryInputDrafts.length) return;
    const next = entryInputDrafts.slice();
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    entryInputDrafts = next;
    emitInputsChange();
  }

  // Linear before/after reorder for the inputs list. Mirrors the tree's
  // drag-handle UX (App.svelte's handleTreeDrag*) but without the "into"
  // mode — inputs are a flat list.
  let inputDragFromIndex: number | null = null;
  let inputDragOverIndex: number | null = null;
  let inputDragOverPosition: "before" | "after" | null = null;

  function handleInputDragStart(event: DragEvent, index: number) {
    inputDragFromIndex = index;
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(index));
    }
  }

  function handleInputDragEnd() {
    inputDragFromIndex = null;
    inputDragOverIndex = null;
    inputDragOverPosition = null;
  }

  function handleInputDragOver(event: DragEvent, index: number) {
    if (inputDragFromIndex === null || inputDragFromIndex === index) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    const target = event.currentTarget;
    if (!(target instanceof HTMLElement)) return;
    const rect = target.getBoundingClientRect();
    const position: "before" | "after" = event.clientY - rect.top < rect.height / 2 ? "before" : "after";
    if (inputDragOverIndex !== index || inputDragOverPosition !== position) {
      inputDragOverIndex = index;
      inputDragOverPosition = position;
    }
  }

  function handleInputDrop(event: DragEvent, index: number) {
    event.preventDefault();
    const from = inputDragFromIndex;
    const position = inputDragOverPosition;
    handleInputDragEnd();
    if (from === null || position === null || from === index) return;
    let to = position === "before" ? index : index + 1;
    if (from < to) to -= 1;
    moveEntryInput(from, to);
  }

  // --- Inline prompt preview (when editing a prompt entry) ---
  // The editor splits vertically: CodeEditor on top, this preview always
  // visible below (resizable divider between them). Auto-renders on body
  // change with a debounce, so warnings and errors track the live draft.
  let promptPreviewSceneId = "";
  let promptPreviewInputDrafts: Record<string, string> = {};
  let promptPreviewResult: AIPreviewResponse | null = null;
  let promptPreviewRunning = false;
  let promptPreviewError: string | null = null;
  let promptPreviewPaneHeight = 280; // px; persisted only in memory for now.
  // Collapsed by default so the body editor is the primary focus. Users
  // expand the preview when they want to test the template.
  let promptPreviewCollapsed = true;
  let promptPreviewDebounceTimer: ReturnType<typeof setTimeout> | null = null;
  let promptPreviewLastRenderKey = ""; // dedupe identical renders.
  // Diagnostics pinned in the CodeEditor gutter — driven by render errors.
  let promptPreviewDiagnostics: { line: number; col?: number; severity: "error" | "warning"; message: string }[] = [];
  // Inputs are per-entry now. Read scene.inputs directly so the reactive
  // re-fires when the entry's inputs change via the editor section below.
  $: promptPreviewDeclaredInputs =
    documentKind === "prompt" && scene
      ? ((scene as unknown as PromptEntrySummary).inputs ?? [])
      : [];
  // Reset preview when the underlying entry changes — stale results from a
  // previous prompt would be confusing.
  // When opening a different entry, clear the result/diagnostics and reset
  // the drafts. A separate reactive below fills in default values for any
  // declared input that's still missing a draft — needed because the schema
  // (which carries the input definitions) can arrive in a different tick from
  // the entry itself, so the entry-switch seed sometimes runs with an empty
  // inputs list. The default-filler closes that race idempotently.
  let promptPreviewSeededEntryId: string | null = null;
  $: if (loadedSceneId && loadedSceneId !== promptPreviewSeededEntryId) {
    promptPreviewResult = null;
    promptPreviewError = null;
    promptPreviewLastRenderKey = "";
    promptPreviewDiagnostics = [];
    promptPreviewInputDrafts = seedInputDrafts(promptPreviewDeclaredInputs);
    promptPreviewSeededEntryId = loadedSceneId;
  }
  $: {
    // Fill in defaults for inputs that don't have a draft yet (typically: the
    // schema arrived after the entry was already opened). Idempotent — never
    // overwrites a value the user has typed.
    let changed = false;
    const next: Record<string, string> = { ...promptPreviewInputDrafts };
    for (const input of promptPreviewDeclaredInputs) {
      if (next[input.name] === undefined) {
        next[input.name] = input.default !== undefined && input.default !== null
          ? String(input.default)
          : (input.type === "boolean" ? "false" : "");
        changed = true;
      }
    }
    if (changed) promptPreviewInputDrafts = next;
  }
  // List of required inputs the author hasn't filled in yet. Surfaced as a
  // warning in the preview body so the render's empty `{{ input.foo }}` slots
  // aren't a mystery.
  $: promptPreviewMissingRequired = promptPreviewDeclaredInputs.filter((i) => {
    if (!i.required) return false;
    const v = promptPreviewInputDrafts[i.name];
    return v === undefined || v === null || (typeof v === "string" && !v.trim());
  });

  /** Translate Jinja2's terse error strings into plain English for the
   * prompt author. Right now: UndefinedError attribute-misses on `input.<X>`
   * (the most common authoring mistake — typo in the input name, or referring
   * to a label instead of the name). Falls through unchanged for everything
   * else. */
  function friendlyTemplateError(raw: string, declared: PromptInputDefinition[]): string {
    const m = /UndefinedError:\s*'\w+\s*object'\s*has\s*no\s*attribute\s*'(\w+)'/.exec(raw);
    if (m) {
      const missing = m[1];
      const declaredNames = declared.map((d) => d.name);
      const inputsList = declaredNames.length
        ? ` Available inputs: ${declaredNames.map((n) => "input." + n).join(", ")}.`
        : " No inputs are declared on this prompt — add one in the Detail Type editor first.";
      return `Your template references \`{{ input.${missing} }}\` but there's no input named "${missing}".${inputsList}`;
    }
    return raw;
  }

  function seedInputDrafts(declared: PromptInputDefinition[]): Record<string, string> {
    const drafts: Record<string, string> = {};
    for (const input of declared) {
      if (input.default !== undefined && input.default !== null) {
        drafts[input.name] = String(input.default);
      } else if (input.type === "boolean") {
        drafts[input.name] = "false";
      } else {
        drafts[input.name] = "";
      }
    }
    return drafts;
  }
  // Fallback scene binding for the preview's `scene` variable. The user
  // controls the explicit binding by marking a scene ★ in any context_pick
  // input — that wins backend-side (see preview.py:_find_marked_target_scene_id).
  // When no scene is marked, this auto-pick keeps the preview useful for
  // first-time authoring (template references to scene.* don't render blank).
  $: if (documentKind === "prompt" && !promptPreviewSceneId && availableScenes.length > 0) {
    promptPreviewSceneId = availableScenes[0].id;
  }
  // Auto-re-render whenever inputs to the render change. Debounced so the
  // backend isn't hammered while the author is mid-keystroke.
  $: schedulePromptPreviewRender(rawBody, promptPreviewSceneId, JSON.stringify(promptPreviewInputDrafts));

  function schedulePromptPreviewRender(_body: string, _scene: string, _inputs: string): void {
    if (documentKind !== "prompt" || !scene) return;
    if (promptPreviewDebounceTimer) clearTimeout(promptPreviewDebounceTimer);
    promptPreviewDebounceTimer = setTimeout(() => {
      promptPreviewDebounceTimer = null;
      void runPromptPreview();
    }, 800);
  }

  async function runPromptPreview(): Promise<void> {
    if (!scene || documentKind !== "prompt") return;
    if (!rawBody.trim()) {
      // Empty template — clear results without calling the backend (which would
      // 422 on template_source min_length). Keeps the panel quiet while the
      // author hasn't typed anything yet.
      promptPreviewResult = null;
      promptPreviewError = null;
      promptPreviewLastRenderKey = "";
      return;
    }
    const inputs: Record<string, unknown> = {};
    for (const declared of promptPreviewDeclaredInputs) {
      const raw = promptPreviewInputDrafts[declared.name] ?? "";
      const coerced = coerceInputValue(raw, declared.type);
      if (coerced !== null && coerced !== "") inputs[declared.name] = coerced;
    }
    const key = JSON.stringify({ rawBody, promptPreviewSceneId, inputs });
    if (key === promptPreviewLastRenderKey && !promptPreviewError) return;
    promptPreviewLastRenderKey = key;
    promptPreviewRunning = true;
    try {
      promptPreviewResult = await api.aiPreview({
        template_source: rawBody,
        target_scene_id: promptPreviewSceneId || "",
        inputs,
        commit: false,
      });
      promptPreviewError = null;
      // Clear gutter markers when the render succeeds. Per-message warnings
      // could be pinned here too in a future slice — they're file-level today.
      promptPreviewDiagnostics = [];
    } catch (e) {
      promptPreviewError = friendlyTemplateError(
        (e as Error).message || "Render failed.",
        promptPreviewDeclaredInputs,
      );
      // If the error carries a line number (Jinja2 syntax errors do), pin a
      // gutter marker on that line. UndefinedError has no line — the error
      // text shown below the preview is the only signal in that case.
      const next: typeof promptPreviewDiagnostics = [];
      if (e instanceof HttpError && e.detail && typeof e.detail === "object") {
        const d = e.detail as { line?: unknown; col?: unknown; message?: unknown };
        if (typeof d.line === "number" && d.line > 0) {
          next.push({
            line: d.line,
            col: typeof d.col === "number" && d.col > 0 ? d.col : undefined,
            severity: "error",
            message: typeof d.message === "string" ? d.message : promptPreviewError,
          });
        }
      }
      promptPreviewDiagnostics = next;
      // Keep the previous result visible — it's stale but at least gives the
      // author something to compare against the error.
    } finally {
      promptPreviewRunning = false;
    }
  }

  function startPromptPreviewResize(event: MouseEvent): void {
    if (event.button !== 0) return;
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = promptPreviewPaneHeight;
    function onMove(e: MouseEvent) {
      // Drag UP shrinks editor / grows preview. Clamp so neither collapses.
      promptPreviewPaneHeight = Math.max(120, Math.min(800, startHeight + (startY - e.clientY)));
    }
    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    }
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  $: slashCommands = editor && documentKind === "scene" ? getSlashCommands() : [];
  // slashFilterText is a plain `let` because TipTap mutates editor state in
  // place — a `$:` declaration depending on `editor` wouldn't re-run when the
  // user types. We refresh it explicitly from onUpdate/onSelectionUpdate.
  let slashFilterText = "";
  $: parsedSlash = parseSlashBody(slashFilterText) ?? { command: slashFilterText, args: "" };
  $: slashArgTokens = tokenizeSlashArgs(parsedSlash.args);
  $: filteredSlashCommands = filterSlashCommands(slashCommands, parsedSlash.command, parsedSlash.args.length > 0);
  $: activeSlashCommand = filteredSlashCommands[slashMenu.selectedIndex];
  $: clampSlashSelectedIndex(filteredSlashCommands.length);
  $: selectionToolbarActions = editor ? getSelectionToolbarActions() : [];
  $: documentLabel = documentKind === "lore" ? "Entry" : documentKind === "structure_node" ? "Node" : "Scene";
  $: documentNameLabel = documentKind === "lore" ? "Name" : "Title";
  // structure_node has no schema kind of its own — Acts/Chapters share
  // kind="scene" in the metadata schema. Reuse the scene entry types so
  // the type selector still lists Act/Chapter/Scene/etc.
  $: documentEntryTypes = Object.entries(metadataSchema?.entry_types ?? {}).filter(([, definition]) => definition.kind === (documentKind === "structure_node" ? "scene" : documentKind) && !definition.abstract);
  $: activeEntryType = metadataSchema?.entry_types[entryType] ?? metadataSchema?.entry_types[defaultEntryType()];
  // Assistants surface ai_provider / ai_capability_tier / ai_model via
  // the bespoke ProviderTierPicker above the schema fields. Hide them
  // from the generic field list to avoid duplicate editors.
  const ASSISTANT_PICKER_FIELDS = new Set([
    "ai_provider",
    "ai_capability_tier",
    "ai_model",
  ]);
  // Svelte 5 reactivity trap ([[feedback-svelte5-reactivity-traps]]):
  // chaining `$: a = ...activeEntryType...` after `$: activeEntryType =
  // ...` doesn't reliably refresh `a` when entryType changes — the
  // effect that writes activeEntryType and the effect that reads it
  // race during legacy_pre_effect scheduling, and `metadataFieldIds`
  // can end up frozen on the entry type the component first mounted
  // with (typically "scene"). Resolving the entry type INLINE from
  // metadataSchema + entryType in one effect avoids the chain.
  // Resolved INLINE from (metadataSchema, entryType) rather than chained
  // through `activeEntryType`. Svelte 5's legacy reactivity raced on the
  // chained derivation and metadataFieldIds could end up frozen on the
  // entry-type the component first mounted with. The single derivation
  // tracks both deps explicitly.
  //
  // `color` is filtered out because the dedicated SwatchPicker in the
  // metadata-color-row above already edits metadata.color — letting the
  // generic field switch render it too would produce a duplicate
  // (untyped text input) row.
  $: metadataFieldIds = ((metadataSchema?.entry_types[entryType] ?? metadataSchema?.entry_types[defaultEntryType()])?.fields ?? []).filter((fieldId) => {
    if (fieldId === "color") return false;
    return documentKind === "assistant" ? !ASSISTANT_PICKER_FIELDS.has(fieldId) : true;
  });
  $: hasBody = activeEntryType?.has_body ?? true;
  $: metadataSummaryText = buildMetadataSummary(activeEntryType?.name ?? entryType, status, liveWordCount, hasBody);

  // Reset the per-scene cost tally when the active scene changes. Reading
  // scene?.id directly so Svelte tracks the dependency
  // ([[feedback-svelte5-reactivity-traps]] — function calls in `$:` don't).
  $: {
    const currentSceneId = scene?.id ?? null;
    if (lastSeenSceneIdForCost !== currentSceneId) {
      lastSeenSceneIdForCost = currentSceneId;
      sceneSessionCostUsd = 0;
      lastInvocationCostUsd = null;
    }
  }

  $: if (metadataReload && metadataReload.token !== lastMetadataReloadToken) {
    lastMetadataReloadToken = metadataReload.token;
    status = metadataReload.status || defaultStatus();
    entryType = metadataReload.entryType || defaultEntryType();
    metadata = cloneMetadata(metadataReload.metadata);
  }

  $: if (titleReload && titleReload.token !== lastTitleReloadToken) {
    lastTitleReloadToken = titleReload.token;
    title = titleReload.title;
  }

  $: if (scene && scene.id !== lastBacklinksSceneId) {
    void refreshBacklinks(scene.id);
  } else if (!scene && lastBacklinksSceneId !== null) {
    lastBacklinksSceneId = null;
    backlinks = [];
    backlinksExpanded = false;
  }

  async function refreshBacklinks(sceneId: string) {
    lastBacklinksSceneId = sceneId;
    try {
      const response = await api.listBacklinks(sceneId);
      if (lastBacklinksSceneId === sceneId) {
        backlinks = response.backlinks;
      }
    } catch (error) {
      if (lastBacklinksSceneId === sceneId) backlinks = [];
    }
  }

  // Setting entryType / title / metadata SYNCHRONOUSLY here (not inside
  // the async loadScene) is essential: an `await` inside loadScene
  // breaks Svelte 5's legacy reactive batching, so a post-await
  // `entryType = …` doesn't reliably re-fire the `metadataFieldIds`
  // pre-effect. The metadata-pane rendered the previous (default)
  // entry-type's fields until the user clicked again.
  //
  // The editor-body load (sceneMarkdownToHtml + setContent) stays in
  // the async loadScene — that's the part that has to await — but it
  // bails early if the editor isn't mounted yet. onMount calls
  // loadScene a second time after the editor mounts so the body lands.
  $: if (scene && scene.id !== loadedSceneId) {
    title = scene.title;
    status = documentStatus(scene);
    entryType = scene.entry_type || defaultEntryType();
    metadata = cloneMetadata(scene.metadata);
    void loadScene(scene);
  }

  $: if (!scene && loadedSceneId !== null) {
    loadedSceneId = null;
    title = "";
    status = defaultStatus();
    entryType = defaultEntryType();
    metadata = {};
    tagPickerFieldId = null;
    tagPickerPosition = null;
    liveWordCount = 0;
    editor?.commands.clearContent(false);
    syncEditorEmpty();
  }

  onMount(() => {
    const AlignedTableCell = TableCell.extend({
      addAttributes() {
        return {
          ...this.parent?.(),
          align: {
            default: null,
            parseHTML: (element: HTMLElement) => element.style.textAlign || element.getAttribute("align") || null,
            renderHTML: (attributes: { align?: string | null }) =>
              attributes.align ? { style: `text-align: ${attributes.align}` } : {},
          },
        };
      },
    });
    const AlignedTableHeader = TableHeader.extend({
      addAttributes() {
        return {
          ...this.parent?.(),
          align: {
            default: null,
            parseHTML: (element: HTMLElement) => element.style.textAlign || element.getAttribute("align") || null,
            renderHTML: (attributes: { align?: string | null }) =>
              attributes.align ? { style: `text-align: ${attributes.align}` } : {},
          },
        };
      },
    });
    editor = new Editor({
      element: editorElement,
      extensions: [
        StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
        AISuggestion,
        CharacterMark,
        TodoAnchor,
        Table.configure({ resizable: true }),
        TableRow,
        AlignedTableHeader,
        AlignedTableCell,
        ImplicitContextHighlight.configure({ matcher: implicitContextMatcher }),
      ],
      content: "",
      editorProps: {
        attributes: {
          class: "editor-body",
          spellcheck: "true",
        },
        handleKeyDown: handleEditorKeydown,
        handleDOMEvents: {
          focus: () => {
            dispatch("focus");
            return false;
          },
        },
        // External clipboard HTML (Word, Google Docs, web pages) ships
        // inline styles + classes that can't round-trip through our
        // Markdown serializer. Strip them at paste time so what's stored
        // matches what's rendered — no surprise font/colour carryover.
        transformPastedHTML: (html) => sanitizePastedHtml(html),
      },
      onUpdate: () => {
        if (!enforceUniqueTodoAnchors()) {
          emitChange();
        }
        if (aiSuggestionId) updateAIToolbarPosition();
        refreshSlashFilterText();
      },
      onSelectionUpdate: () => {
        updateSelectionMenu();
        updateTableMenu();
        if (aiSuggestionId) updateAIToolbarPosition();
        refreshSlashFilterText();
      },
      onBlur: () => {
        hideSelectionMenu();
        tableMenu = { ...tableMenu, visible: false };
      },
    });

    if (scene) {
      void loadScene(scene);
    }

    return () => editor?.destroy();
  });

  // Reactively poke the ImplicitContextHighlight extension when the
  // matcher reference changes (lore added/edited at the App level).
  // Mirrors PlainTextEditor + MetadataLongTextEditor.
  $: if (editor) updateImplicitMatcher(implicitContextMatcher);
  function updateImplicitMatcher(next: typeof implicitContextMatcher): void {
    if (!editor) return;
    const ext = editor.extensionManager.extensions.find(
      (e) => e.name === "implicitContextHighlight",
    );
    if (!ext) return;
    ext.options.matcher = next;
    const view = editor.view;
    if (!view) return;
    const tr = view.state.tr.setMeta(REBUILD_META, true).setMeta("addToHistory", false);
    view.dispatch(tr);
  }

  async function loadScene(nextScene: Scene) {
    const sceneId = nextScene.id;
    title = nextScene.title;
    status = documentStatus(nextScene);
    entryType = nextScene.entry_type || defaultEntryType();
    metadata = cloneMetadata(nextScene.metadata);
    // Drop any pending AI suggestion state when changing documents.
    aiSuggestionId = null;
    aiSuggestionMeta = null;
    aiSuggestionOriginal = null;
    aiAnchorPos = null;
    aiError = null;
    aiToolbarPosition = { x: 0, y: 0, visible: false };
    const nextEntryDefinition = metadataSchema?.entry_types[entryType];
    const nextHasBody = nextEntryDefinition?.has_body ?? true;
    metadataExpanded = documentKind === "lore" || !nextHasBody;
    tagPickerFieldId = null;
    tagPickerPosition = null;
    // Branch on the FRESHLY-resolved entry-type's body_editor — the `rawBodyMode`
    // reactive hasn't recomputed yet (Svelte updates on the next microtask), so
    // reading it here would reflect the PREVIOUS entry. For a prompt opened
    // after a scene that meant we fell through to the WYSIWYG branch and lost
    // the Jinja2 source view.
    const nextRawBodyMode = (nextEntryDefinition?.body_editor ?? "wysiwyg") === "code";
    if (nextRawBodyMode) {
      const nextBody = nextScene.body_markdown ?? "";
      rawBody = nextBody;
      lastEmittedRawBody = nextBody;
      loadedSceneId = sceneId;
      liveWordCount = countWords(nextBody);
      return;
    }
    const html = await sceneMarkdownToHtml(nextScene.body_markdown || "");
    if (!editor || scene?.id !== sceneId) return;
    editor.commands.setContent(html || "<p></p>", false);
    loadedSceneId = sceneId;
    enforceUniqueTodoAnchors();
    syncTodoAnchorDomState(true);
    updateLiveWordCount();
    dispatchEmbeddedTodos();
    syncEditorEmpty();
    updateSelectionMenu();
    updateTableMenu();
  }

  function emitChange() {
    if (!scene) return;
    if (rawBodyMode) {
      liveWordCount = countWords(rawBody);
      dispatch("change", {
        title,
        bodyMarkdown: rawBody,
        status,
        entryType,
        metadata: cloneMetadata(metadata),
        inputs: documentKind === "prompt" ? entryInputDraftsToCanonical(entryInputDrafts) : undefined,
      });
      return;
    }
    if (!editor) return;
    syncEditorEmpty();
    updateSelectionMenu();
    updateTableMenu();
    updateSlashMenuFromContent();
    syncTodoAnchorDomState(true);
    updateLiveWordCount();
    dispatchEmbeddedTodos();
    dispatch("change", {
      title,
      bodyMarkdown: editorHtmlToSceneMarkdown(editor.getHTML()),
      status,
      entryType,
      inputs: documentKind === "prompt" ? entryInputDraftsToCanonical(entryInputDrafts) : undefined,
      metadata: cloneMetadata(metadata),
    });
  }

  function cloneMetadata(value: EntryMetadata) {
    return JSON.parse(JSON.stringify(value ?? {})) as EntryMetadata;
  }

  function metadataEqual(left: EntryMetadata, right: EntryMetadata) {
    return JSON.stringify(left ?? {}) === JSON.stringify(right ?? {});
  }

  function updateStatus(value: string) {
    status = value;
    emitChange();
  }

  function updateEntryType(value: string) {
    entryType = value;
    emitChange();
  }

  function defaultEntryType() {
    return documentKind === "lore" ? "lore_note" : "scene";
  }

  function defaultStatus() {
    return documentKind === "scene" ? "draft" : "";
  }

  function documentStatus(document: EditableDocument) {
    return "status" in document ? document.status || "draft" : "";
  }

  function updateMetadataField(fieldId: string, field: MetadataFieldDefinition, value: MetadataValue) {
    metadata = {
      ...metadata,
      [fieldId]: normaliseFieldValue(field, value),
    };
    emitChange();
  }

  function normaliseFieldValue(field: MetadataFieldDefinition, value: MetadataValue): MetadataValue {
    if (field.type === "multi_select" || field.type === "tags" || field.type === "entity_ref_list") {
      if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
      return String(value ?? "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    }
    if (field.type === "number") {
      if (value === "" || value === null) return null;
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : null;
    }
    if (field.type === "boolean") {
      return Boolean(value);
    }
    return value === null ? "" : String(value);
  }

  function metadataValueString(value: MetadataValue | undefined) {
    if (Array.isArray(value)) return value.join(", ");
    if (value === null || value === undefined) return "";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function metadataValueList(value: MetadataValue | undefined) {
    if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
    if (value === null || value === undefined || value === "") return [];
    return String(value)
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function metadataReferenceValue(field: MetadataFieldDefinition, value: MetadataValue | undefined): string | string[] {
    if (field.type === "entity_ref_list") return metadataValueList(value);
    if (value === null || value === undefined) return "";
    if (typeof value === "object") return "";
    return String(value);
  }

  function hasTag(fieldId: string, tag: string) {
    const key = tag.toLowerCase();
    return metadataValueList(metadata[fieldId]).some((item) => item.toLowerCase() === key);
  }

  function addKnownTag(fieldId: string, field: MetadataFieldDefinition, tag: string) {
    const key = tag.toLowerCase();
    const nextTags = metadataValueList(metadata[fieldId]).filter((item) => item.toLowerCase() !== key);
    updateMetadataField(fieldId, field, [...nextTags, tag]);
  }

  function toggleMultiSelectOption(fieldId: string, field: MetadataFieldDefinition, option: string) {
    const current = metadataValueList(metadata[fieldId]);
    const key = option.toLowerCase();
    const hasIt = current.some((item) => item.toLowerCase() === key);
    const next = hasIt
      ? current.filter((item) => item.toLowerCase() !== key)
      : [...current, option];
    updateMetadataField(fieldId, field, next);
  }

  function isMultiSelectOptionSelected(fieldId: string, option: string) {
    const key = option.toLowerCase();
    return metadataValueList(metadata[fieldId]).some((item) => item.toLowerCase() === key);
  }

  function toggleTagPicker(fieldId: string, event: MouseEvent) {
    if (tagPickerFieldId === fieldId) {
      tagPickerFieldId = null;
      tagPickerPosition = null;
      return;
    }
    const anchor = (event.currentTarget as HTMLElement).closest(".tag-picker-anchor") as HTMLElement | null;
    const bounds = (anchor ?? (event.currentTarget as HTMLElement)).getBoundingClientRect();
    tagPickerFieldId = fieldId;
    tagPickerPosition = {
      x: bounds.left,
      y: bounds.bottom + 4,
      width: Math.min(320, Math.max(220, bounds.width)),
    };
  }

  function syncSelectValue(node: HTMLSelectElement, value: string) {
    let mounted = true;
    const applyValue = (nextValue: string) => {
      window.queueMicrotask(() => {
        if (!mounted) return;
        node.value = nextValue;
      });
    };
    applyValue(value);
    return {
      update(nextValue: string) {
        applyValue(nextValue);
      },
      destroy() {
        mounted = false;
      },
    };
  }

  function computedFieldString(fieldId: string) {
    if (fieldId === "word_count") return String(liveWordCount);
    const value = scene?.computed_metadata?.[fieldId];
    if (Array.isArray(value)) return value.join(", ");
    if (value === null || value === undefined) return "";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  function buildMetadataSummary(typeName: string, currentStatus: string, wordCount: number, bodyEnabled: boolean) {
    if (documentKind === "lore") return typeName;
    if (!bodyEnabled) return typeName;
    return `${typeName} · ${currentStatus || "draft"} · ${wordCount} ${wordCount === 1 ? "word" : "words"}`;
  }

  function updateLiveWordCount() {
    if (!editor) {
      liveWordCount = 0;
      return;
    }
    liveWordCount = countWords(editor.state.doc.textBetween(0, editor.state.doc.content.size, " "));
  }

  function countWords(text: string) {
    return Array.from(text.matchAll(WORD_PATTERN)).length;
  }

  function syncEditorEmpty() {
    if (!editor) {
      editorEmpty = true;
      return;
    }

    const doc = editor.state.doc;
    if (doc.childCount !== 1) {
      editorEmpty = false;
      return;
    }

    const firstNode = doc.child(0);
    editorEmpty = firstNode.type.name === "paragraph" && firstNode.content.size === 0;
  }

  function walkPromptAncestors(entryTypeId: string | undefined | null): string[] {
    if (!entryTypeId || !metadataSchema) return [];
    const seen = new Set<string>();
    const chain: string[] = [];
    let current: string | undefined = entryTypeId;
    while (current && !seen.has(current)) {
      seen.add(current);
      chain.push(current);
      current = metadataSchema.entry_types[current]?.parent ?? undefined;
    }
    return chain;
  }

  function effectiveOutputKind(entry: PromptEntrySummary): string | null {
    const definition = metadataSchema?.entry_types[entry.entry_type];
    const output = definition?.prompt?.context_strategy?.output;
    if (!output || typeof output.kind !== "string") return null;
    return output.kind;
  }

  function promptEntriesForSurface(surface: "append_to_body" | "replace_selection" | "chat_panel"): PromptEntrySummary[] {
    if (!metadataSchema) return [];
    return promptEntries
      .filter((entry) => effectiveOutputKind(entry) === surface)
      .sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
  }

  function promptEntryDescription(entry: PromptEntrySummary): string {
    const typeName = metadataSchema?.entry_types[entry.entry_type]?.name ?? entry.entry_type;
    return typeName;
  }

  function effectivePromptInputs(entry: PromptEntrySummary) {
    // Inputs now live on the entry itself (not the entry-type) — the
    // declaration and the template that uses it are coupled.
    return entry.inputs ?? [];
  }

  // Resolve a positional-string token against a context_pick input. Returns
  // the serialized NodePickerRef-array JSON the dialog/runtime expects,
  // or null if the name is ambiguous / unresolved (so the caller can fall
  // back to the dialog).
  function resolveContextPickToken(
    token: string,
    target: { kind?: string; entry_type?: string } | null | undefined,
  ): string | null {
    const lower = token.toLowerCase();
    const wantKind = target?.kind;
    const wantEntryType = target?.entry_type;

    type Cand = { id: string; kind: "lore" | "scene"; title: string; entry_type?: string };
    const candidates: Cand[] = [];

    if (!wantKind || wantKind === "lore") {
      for (const lore of loreEntries) {
        if (lore.title.toLowerCase() !== lower) continue;
        if (wantEntryType && lore.entry_type !== wantEntryType) continue;
        candidates.push({ id: lore.id, kind: "lore", title: lore.title, entry_type: lore.entry_type });
      }
    }
    if (!wantKind || wantKind === "scene") {
      for (const sc of availableScenes) {
        if (sc.title.toLowerCase() !== lower) continue;
        candidates.push({ id: sc.id, kind: "scene", title: sc.title });
      }
    }

    if (candidates.length !== 1) return null;
    const c = candidates[0];
    const ref: { id: string; kind: string; title: string; entry_type?: string } = {
      id: c.id,
      kind: c.kind,
      title: c.title,
    };
    if (c.entry_type) ref.entry_type = c.entry_type;
    return JSON.stringify([ref]);
  }

  function resolvePromptPositionalArgs(
    entry: PromptEntrySummary,
    args: string[],
  ): {
    inputs: Record<string, unknown> | undefined;
    satisfied: boolean;
    unresolved: Array<{ name: string; label: string; token: string }>;
  } {
    const declared = effectivePromptInputs(entry);
    if (declared.length === 0 || args.length === 0) {
      return { inputs: undefined, satisfied: false, unresolved: [] };
    }
    const inputs: Record<string, unknown> = {};
    const filledNames = new Set<string>();
    const unresolved: Array<{ name: string; label: string; token: string }> = [];
    const limit = Math.min(declared.length, args.length);
    for (let i = 0; i < limit; i++) {
      const input = declared[i];
      const raw = args[i];
      const label = input.label || input.name;
      if (input.type === "context_pick") {
        const target = input.target as { kind?: string; entry_type?: string } | null | undefined;
        const resolved = resolveContextPickToken(raw, target);
        if (resolved === null) {
          unresolved.push({ name: input.name, label, token: raw });
          continue;
        }
        inputs[input.name] = resolved;
        filledNames.add(input.name);
      } else {
        const coerced = coerceInputValue(raw, input.type);
        if (coerced === null || coerced === "") {
          unresolved.push({ name: input.name, label, token: raw });
          continue;
        }
        inputs[input.name] = coerced;
        filledNames.add(input.name);
      }
    }
    const missingRequired = declared.some(
      (input) => input.required && !filledNames.has(input.name),
    );
    // Satisfied = no required-missing AND every supplied positional arg
    // resolved. A partially-resolved invocation falls through to the
    // dialog so the user can fix the unresolved tokens.
    return {
      inputs,
      satisfied: !missingRequired && unresolved.length === 0,
      unresolved,
    };
  }

  function handleEditorKeydown(view: EditorView, event: KeyboardEvent) {
    if (documentKind !== "scene") {
      if (slashMenu.visible) closeSlashMenu();
      return false;
    }

    // Ctrl/⌘+J: invoke the first available continuation prompt.
    if (event.key.toLowerCase() === "j" && (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey) {
      event.preventDefault();
      const entry = defaultPromptForSurface("append_to_body");
      if (entry) void runPromptEntry(entry);
      return true;
    }
    // Ctrl/⌘+Shift+J: invoke the first available revise prompt.
    if (event.key.toLowerCase() === "j" && (event.ctrlKey || event.metaKey) && !event.altKey && event.shiftKey) {
      event.preventDefault();
      const entry = defaultPromptForSurface("replace_selection");
      if (entry) void runPromptEntry(entry);
      return true;
    }

    if (slashMenu.visible && slashMenu.mode === "table-grid") {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        slashMenu = { ...slashMenu, gridRows: Math.min(TABLE_GRID_MAX_ROWS, slashMenu.gridRows + 1) };
        return true;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        slashMenu = { ...slashMenu, gridRows: Math.max(1, slashMenu.gridRows - 1) };
        return true;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        slashMenu = { ...slashMenu, gridCols: Math.min(TABLE_GRID_MAX_COLS, slashMenu.gridCols + 1) };
        return true;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        slashMenu = { ...slashMenu, gridCols: Math.max(1, slashMenu.gridCols - 1) };
        return true;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        insertTableFromGrid(slashMenu.gridRows, slashMenu.gridCols);
        return true;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeSlashMenu();
        return true;
      }
    } else if (slashMenu.visible) {
      const count = filteredSlashCommands.length;
      if (event.key === "ArrowDown" && count > 0) {
        event.preventDefault();
        slashMenu = { ...slashMenu, selectedIndex: (slashMenu.selectedIndex + 1) % count };
        return true;
      }
      if (event.key === "ArrowUp" && count > 0) {
        event.preventDefault();
        slashMenu = {
          ...slashMenu,
          selectedIndex: (slashMenu.selectedIndex - 1 + count) % count,
        };
        return true;
      }
      if (event.key === "Enter" && activeSlashCommand) {
        event.preventDefault();
        runSlashCommand(activeSlashCommand);
        return true;
      }
      if (event.key === "Tab" && activeSlashCommand) {
        event.preventDefault();
        autocompleteSlashFilter(activeSlashCommand);
        return true;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeSlashMenu();
        return true;
      }
    }

    // Tab outside the slash menu: indent a list item if we're in one,
    // otherwise insert a literal tab character. Both override the
    // browser default of focusing the next form element — when the user
    // is writing, Tab should stay inside the editor.
    if (event.key === "Tab" && !event.shiftKey && editor) {
      if (editor.can().sinkListItem("listItem")) {
        event.preventDefault();
        editor.chain().focus().sinkListItem("listItem").run();
        return true;
      }
      event.preventDefault();
      editor.chain().focus().insertContent("\t").run();
      return true;
    }
    // Shift+Tab outside the slash menu: outdent a list item if we're
    // in one. Outside lists, leave Shift+Tab alone so it can still
    // navigate focus backward to the previous element if the user
    // wants to escape the editor.
    if (event.key === "Tab" && event.shiftKey && editor && editor.can().liftListItem("listItem")) {
      event.preventDefault();
      editor.chain().focus().liftListItem("listItem").run();
      return true;
    }

    if (event.key === "/" && isEmptyTextblock(view)) {
      window.setTimeout(openSlashMenu, 0);
      return false;
    }

    if (event.key === "Escape") {
      hideSelectionMenu();
      closeSlashMenu();
    }

    return false;
  }

  function isEmptyTextblock(view: EditorView) {
    const { selection } = view.state;
    return selection.empty && selection.$from.parent.type.name === "paragraph" && selection.$from.parent.textContent.length === 0;
  }

  // Slash text shape: `/<command>[ <args>]`. The command is word-chars only;
  // args is free text that gets tokenized at run time. `/ prose` (empty
  // command + space) is NOT a slash trigger — that lets the user start a
  // line with `/` and keep typing.
  const SLASH_COMMAND_PATTERN = /^[a-zA-Z0-9_-]*$/;
  const SLASH_WITH_ARGS_PATTERN = /^([a-zA-Z0-9_-]+)\s+(.*)$/;

  function parseSlashBody(text: string): { command: string; args: string } | null {
    if (SLASH_COMMAND_PATTERN.test(text)) return { command: text, args: "" };
    const m = text.match(SLASH_WITH_ARGS_PATTERN);
    if (m) return { command: m[1], args: m[2] };
    return null;
  }

  // `/table 9x2` → 9 rows × 2 cols. The visual grid picker tops out at 8×8,
  // but the CLI shouldn't silently truncate what the user typed — clamp
  // generously instead so /table 50x3 still inserts a 50×3 table.
  function parseTableDims(token: string): { rows: number; cols: number } | null {
    const m = token.match(/^(\d+)\s*[x×]\s*(\d+)$/i);
    if (!m) return null;
    const rows = Math.min(100, Math.max(1, parseInt(m[1], 10)));
    const cols = Math.min(100, Math.max(1, parseInt(m[2], 10)));
    return { rows, cols };
  }

  function tokenizeSlashArgs(input: string): string[] {
    const tokens: string[] = [];
    let i = 0;
    while (i < input.length) {
      while (i < input.length && /\s/.test(input[i])) i++;
      if (i >= input.length) break;
      if (input[i] === '"' || input[i] === "'") {
        const quote = input[i++];
        let token = "";
        while (i < input.length && input[i] !== quote) token += input[i++];
        if (i < input.length) i++;
        tokens.push(token);
      } else {
        let token = "";
        while (i < input.length && !/\s/.test(input[i])) token += input[i++];
        tokens.push(token);
      }
    }
    return tokens;
  }

  function isSlashTriggerContext() {
    if (documentKind !== "scene") return false;
    if (!editor) return false;
    const { selection } = editor.state;
    if (!selection.empty) return false;
    if (selection.$from.parent.type.name !== "paragraph") return false;
    const text = selection.$from.parent.textContent;
    if (!text.startsWith("/")) return false;
    return parseSlashBody(text.slice(1)) !== null;
  }

  function readSlashFilterText(): string {
    if (!editor) return "";
    const text = editor.state.selection.$from.parent.textContent;
    if (!text.startsWith("/")) return "";
    return text.slice(1);
  }

  function refreshSlashFilterText() {
    const next = editor && documentKind === "scene" ? readSlashFilterText() : "";
    if (next !== slashFilterText) slashFilterText = next;
  }

  // Anchor matching to word starts. `/ro` matches "Roleplay" and
  // "Bullet List"'s second word "list" would match `/list`, but
  // "Paragraph" (description "Return this line to plain prose.") no
  // longer matches `/ro` just because "prose" or "Return" contain
  // the letters somewhere inside.
  function matchesSlashFilter(haystack: string, needle: string): boolean {
    const lower = needle.toLowerCase();
    return haystack.toLowerCase().split(/\s+/).some((word) => word.startsWith(lower));
  }

  function filterSlashCommands(commands: SlashCommand[], command: string, argsPresent: boolean): SlashCommand[] {
    if (!command) return commands;
    const lower = command.toLowerCase();
    // With positional args, prefer an exact label match so unambiguous
    // commands fire without showing siblings — `/table 9x2` should
    // narrow to "Table", not also "Heading 2". With no exact match
    // we fall through to the same word-prefix search the no-args
    // path uses (label OR description OR group) so a prompt titled
    // "Untitled Prompt" of type Roleplay still matches `/roleplay …`.
    if (argsPresent) {
      const exact = commands.filter((cmd) => cmd.label.toLowerCase() === lower);
      if (exact.length > 0) return exact;
    }
    return commands.filter((cmd) =>
      matchesSlashFilter(cmd.label, command) ||
      matchesSlashFilter(cmd.description, command) ||
      matchesSlashFilter(cmd.group, command),
    );
  }

  function clampSlashSelectedIndex(count: number) {
    if (!slashMenu.visible || slashMenu.mode !== "commands") return;
    if (slashMenu.selectedIndex > 0 && slashMenu.selectedIndex >= count) {
      slashMenu = { ...slashMenu, selectedIndex: 0 };
    }
  }

  function updateSlashMenuFromContent() {
    if (documentKind !== "scene") {
      if (slashMenu.visible) closeSlashMenu();
      return;
    }

    if (slashMenu.visible && slashMenu.mode === "table-grid") {
      return;
    }

    if (isSlashTriggerContext()) {
      window.setTimeout(openSlashMenu, 0);
    } else if (slashMenu.visible) {
      closeSlashMenu();
    }
  }

  function setCellAlign(align: "left" | "center" | "right") {
    if (!editor) return;
    const { state, view } = editor;
    const { $from } = state.selection;
    let tablePos = -1;
    let tableNode: ProseMirrorNode | null = null;
    let tableDepth = -1;
    for (let d = $from.depth; d >= 0; d--) {
      const node = $from.node(d);
      if (node.type.name === "table") {
        tablePos = $from.before(d);
        tableNode = node;
        tableDepth = d;
        break;
      }
    }
    if (!tableNode || tablePos < 0 || $from.depth < tableDepth + 2) {
      editor.chain().focus().setCellAttribute("align", align).run();
      return;
    }
    const cellIndex = $from.index(tableDepth + 1);
    let tr = state.tr;
    let rowPos = tablePos + 1;
    for (let i = 0; i < tableNode.childCount; i++) {
      const row = tableNode.child(i);
      let cellPos = rowPos + 1;
      for (let j = 0; j < row.childCount; j++) {
        const cell = row.child(j);
        if (j === cellIndex) {
          tr = tr.setNodeMarkup(cellPos, null, { ...cell.attrs, align });
          break;
        }
        cellPos += cell.nodeSize;
      }
      rowPos += row.nodeSize;
    }
    view.dispatch(tr);
    editor.commands.focus();
  }

  function findCurrentTableElement(): HTMLElement | null {
    if (!editor) return null;
    const { selection } = editor.state;
    let node: Node | null = editor.view.domAtPos(selection.from).node;
    while (node && node !== document.body) {
      if (node instanceof HTMLElement && node.tagName === "TABLE") return node;
      node = node.parentNode;
    }
    return null;
  }

  function updateTableMenu() {
    if (!editor || !editorFrame || documentKind !== "scene" || !editor.isFocused) {
      if (tableMenu.visible) tableMenu = { ...tableMenu, visible: false };
      return;
    }
    if (!editor.isActive("table")) {
      if (tableMenu.visible) tableMenu = { ...tableMenu, visible: false };
      return;
    }
    const tableEl = findCurrentTableElement();
    if (!tableEl) {
      if (tableMenu.visible) tableMenu = { ...tableMenu, visible: false };
      return;
    }
    const tableRect = tableEl.getBoundingClientRect();
    const frameBounds = editorFrame.getBoundingClientRect();
    const toolbarHeight = 36;
    const above = tableRect.top - frameBounds.top - toolbarHeight - 4;
    const below = tableRect.bottom - frameBounds.top + 6;
    const y = above >= 4 ? above : below;
    tableMenu = {
      visible: true,
      x: tableRect.left - frameBounds.left + editorFrame.scrollLeft,
      y: y + editorFrame.scrollTop,
    };
  }

  function updateSelectionMenu() {
    if (!editor || !editorFrame) return;
    const { selection } = editor.state;
    if (selection.empty || !editor.isFocused) {
      hideSelectionMenu();
      return;
    }

    const selectedText = editor.state.doc.textBetween(selection.from, selection.to, " ").trim();
    if (!selectedText) {
      hideSelectionMenu();
      return;
    }

    const anchorRect = getVisibleSelectionRect() ?? getSelectionEndpointRect();
    if (!anchorRect) {
      hideSelectionMenu();
      return;
    }

    const frameBounds = editorFrame.getBoundingClientRect();
    const toolbarHeight = 42;
    const toolbarMargin = 10;
    const visibleTop = Math.max(frameBounds.top, 0) + toolbarMargin;
    const visibleBottom = Math.min(frameBounds.bottom, window.innerHeight) - toolbarMargin;
    const anchorTop = anchorRect.top;
    const anchorBottom = anchorRect.bottom;
    const hasRoomAbove = anchorTop - toolbarHeight - toolbarMargin >= visibleTop;
    const placement = hasRoomAbove ? "above" : "below";
    const preferredY = placement === "above" ? anchorTop - toolbarMargin : anchorBottom + toolbarMargin;
    const minY = placement === "above" ? visibleTop + toolbarHeight : visibleTop;
    const maxY = placement === "above" ? visibleBottom : visibleBottom - toolbarHeight;
    const toolbarHalfWidth = Math.min(360, Math.max(140, editorFrame.clientWidth / 2 - toolbarMargin));
    const unclampedX = (anchorRect.left + anchorRect.right) / 2;
    const minX = Math.max(frameBounds.left, 0) + toolbarHalfWidth;
    const maxX = Math.min(frameBounds.right, window.innerWidth) - toolbarHalfWidth;
    const wordCount = countWords(selectedText);
    selectionMenu = {
      visible: true,
      x: minX <= maxX ? clamp(unclampedX, minX, maxX) : (Math.max(frameBounds.left, 0) + Math.min(frameBounds.right, window.innerWidth)) / 2,
      y: clamp(preferredY, minY, maxY),
      wordCount,
      placement,
    };
    openToolbarMenuId = null;
    closeSlashMenu();
  }

  function getVisibleSelectionRect() {
    if (!editorFrame) return null;
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0) return null;
    const frameBounds = editorFrame.getBoundingClientRect();
    const visibleRects = Array.from(selection.getRangeAt(0).getClientRects()).filter(
      (rect) =>
        rect.width > 0 &&
        rect.height > 0 &&
        rect.bottom >= frameBounds.top &&
        rect.top <= frameBounds.bottom &&
        rect.right >= frameBounds.left &&
        rect.left <= frameBounds.right,
    );
    return visibleRects[0] ?? null;
  }

  function getSelectionEndpointRect() {
    if (!editor) return null;
    const { selection } = editor.state;
    const start = editor.view.coordsAtPos(selection.from);
    const end = editor.view.coordsAtPos(selection.to);
    return {
      top: Math.min(start.top, end.top),
      bottom: Math.max(start.bottom, end.bottom),
      left: Math.min(start.left, end.left),
      right: Math.max(start.right, end.right),
    };
  }

  function hideSelectionMenu() {
    selectionMenu = { ...selectionMenu, visible: false };
    openToolbarMenuId = null;
  }

  function clamp(value: number, min: number, max: number) {
    return Math.min(Math.max(value, min), max);
  }

  function openSlashMenu() {
    if (documentKind !== "scene") return;
    if (!editor || !editorFrame || !editor.isFocused) return;
    // Re-check trigger context: this function is called via setTimeout(0) from
    // updateSlashMenuFromContent, so by the time it fires the slash text may
    // already have been cleared (e.g. by clearSlashTrigger inside runSlashCommand).
    // Without this check the menu would re-open the moment after closeSlashMenu ran.
    if (!isSlashTriggerContext()) return;
    const coords = editor.view.coordsAtPos(editor.state.selection.from);
    const frameBounds = editorFrame.getBoundingClientRect();
    slashMenu = {
      visible: true,
      x: coords.left - frameBounds.left + editorFrame.scrollLeft,
      y: coords.bottom - frameBounds.top + editorFrame.scrollTop + 8,
      selectedIndex: 0,
      mode: "commands",
      gridRows: 1,
      gridCols: 1,
    };
  }

  function closeSlashMenu() {
    slashMenu = { ...slashMenu, visible: false, selectedIndex: 0, mode: "commands", gridRows: 1, gridCols: 1 };
  }

  function openTableGrid() {
    slashMenu = { ...slashMenu, mode: "table-grid", gridRows: 1, gridCols: 1 };
  }

  function insertTableFromGrid(rows: number, cols: number) {
    clearSlashTrigger();
    editor?.chain().focus().insertTable({ rows, cols, withHeaderRow: true }).run();
    closeSlashMenu();
    syncEditorEmpty();
  }

  function clearSlashTrigger() {
    if (!editor) return;
    const { selection } = editor.state;
    const paragraphStart = selection.$from.start();
    const paragraphText = selection.$from.parent.textContent;
    if (paragraphText.startsWith("/") && parseSlashBody(paragraphText.slice(1)) !== null) {
      editor.chain().focus().deleteRange({ from: paragraphStart, to: paragraphStart + paragraphText.length }).run();
    }
  }

  // Tab in the slash menu: rewrite the trigger paragraph from "/<partial>"
  // to "/<full-command> " so the user can immediately type positional
  // args. Only intercepted while the menu is visible — see the gated
  // Tab branch in handleEditorKeydown — so prose Tab handling outside
  // the menu is untouched.
  function autocompleteSlashFilter(cmd: SlashCommand) {
    if (!editor) return;
    const { selection } = editor.state;
    const paragraphStart = selection.$from.start();
    const paragraphText = selection.$from.parent.textContent;
    if (!paragraphText.startsWith("/") || parseSlashBody(paragraphText.slice(1)) === null) return;
    const target = (cmd.autocompleteTo ?? cmd.label).trim();
    if (!target) return;
    const replacement = `/${target} `;
    if (paragraphText === replacement) return;
    editor
      .chain()
      .focus()
      .deleteRange({ from: paragraphStart, to: paragraphStart + paragraphText.length })
      .insertContent(replacement)
      .run();
  }

  function runSlashCommand(command: SlashCommand) {
    const parsed = parseSlashBody(slashFilterText) ?? { command: slashFilterText, args: "" };
    const args = tokenizeSlashArgs(parsed.args);
    command.run(args);
    clearSlashTrigger();
    if (slashMenu.mode === "commands") {
      closeSlashMenu();
      syncEditorEmpty();
    }
  }

  async function runPromptEntry(
    entry: PromptEntrySummary,
    prefilledInputs?: Record<string, unknown>,
    assistantId: string = "",
  ) {
    if (!editor || !scene || aiGenerating || documentKind !== "scene") return;
    if (aiSuggestionId) {
      aiError = "Accept or revert the pending suggestion before generating another.";
      return;
    }
    const declared = effectivePromptInputs(entry);
    if (declared.length > 0 && !prefilledInputs) {
      openInputsDialog(entry);
      return;
    }
    await runPromptEntryWithInputs(entry, prefilledInputs ?? {}, assistantId);
  }

  function openInputsDialog(entry: PromptEntrySummary) {
    const declared = effectivePromptInputs(entry);
    const prior = lastInvokedEntryId === entry.id ? lastInvokedInputs : {};
    const drafts: Record<string, string> = {};
    for (const input of declared) {
      const previous = prior[input.name];
      if (previous !== undefined && previous !== null) {
        drafts[input.name] = String(previous);
      } else if (input.default !== undefined && input.default !== null) {
        drafts[input.name] = String(input.default);
      } else {
        drafts[input.name] = input.type === "boolean" ? "false" : "";
      }
    }
    inputsDialogDrafts = drafts;
    // Seed with the user's default; the picker shows it as "Default (Name)".
    inputsDialogAssistantId = "";
    inputsDialogError = null;
    inputsDialogEntry = entry;
  }

  function cancelInputsDialog() {
    inputsDialogEntry = null;
    inputsDialogDrafts = {};
    inputsDialogAssistantId = "";
    inputsDialogError = null;
  }

  function updateInputsDialogDraft(name: string, value: string) {
    inputsDialogDrafts = { ...inputsDialogDrafts, [name]: value };
  }

  async function fetchInputsDialogEstimate(): Promise<void> {
    const entry = inputsDialogEntry;
    if (!entry) {
      inputsDialogEstimate = null;
      return;
    }
    const ourToken = ++inputsDialogEstimateToken;
    const declared = effectivePromptInputs(entry);
    const inputs: Record<string, unknown> = {};
    for (const input of declared) {
      const raw = inputsDialogDrafts[input.name] ?? "";
      const coerced = coerceInputValue(raw, input.type);
      if (coerced !== null && coerced !== "") inputs[input.name] = coerced;
    }
    try {
      const preview = await api.aiPreview({
        template_source: entry.body_markdown,
        target_scene_id: scene?.id ?? "",
        inputs,
        commit: false,
        assistant_id: inputsDialogAssistantId || null,
      });
      if (ourToken !== inputsDialogEstimateToken) return;
      inputsDialogEstimate = {
        tokens: preview.estimated_tokens ?? 0,
        cost_usd: preview.estimated_cost_usd ?? null,
        caching_style: preview.caching_style ?? null,
        cache_blocks: (preview.cache_blocks ?? []).map((b) => ({
          label: b.label,
          tokens: b.tokens,
          cache_break_after: b.cache_break_after,
        })),
      };
    } catch {
      // Render errors surface when the user runs; keep the strip quiet
      // rather than flickering an error here.
    }
  }

  // Reactive trigger: refetch when the dialog's prompt / drafts / assistant
  // change. Per [[feedback-svelte5-reactivity-traps]], read each dep on its
  // own line so Svelte tracks them — a function call alone wouldn't.
  $: {
    void inputsDialogEntry;
    void inputsDialogDrafts;
    void inputsDialogAssistantId;
    void fetchInputsDialogEstimate();
  }

  function coerceInputValue(raw: string, type: PromptInputDefinition["type"]): unknown {
    const trimmed = raw.trim();
    if (type === "number") {
      if (trimmed === "") return null;
      const parsed = Number(trimmed);
      return Number.isFinite(parsed) ? parsed : trimmed;
    }
    if (type === "boolean") return trimmed.toLowerCase() === "true";
    if (type === "entity_ref_list") {
      if (!trimmed) return null;
      try {
        const parsed = JSON.parse(trimmed);
        return Array.isArray(parsed) ? parsed : null;
      } catch {
        return null;
      }
    }
    return trimmed;
  }

  function refInputDraftValue(input: PromptInputDefinition, raw: string | undefined): string | string[] {
    if (input.type === "entity_ref_list") {
      if (!raw) return [];
      try {
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
      } catch {
        return [];
      }
    }
    return raw ?? "";
  }

  function encodeRefInputDraft(value: string | string[]): string {
    return Array.isArray(value) ? JSON.stringify(value) : value;
  }

  function assistantDisplayName(assistantId: string): string {
    if (!assistantId) return "";
    return assistantEntries.find((a) => a.id === assistantId)?.title ?? "";
  }

  function refInputStubField(input: PromptInputDefinition): MetadataFieldDefinition {
    const target: Record<string, string> = {};
    const t = input.target as { kind?: unknown; entry_type?: unknown } | null | undefined;
    if (t && typeof t.kind === "string") target.kind = t.kind;
    if (t && typeof t.entry_type === "string") target.entry_type = t.entry_type;
    return {
      name: input.label || input.name,
      type: input.type === "entity_ref_list" ? "entity_ref_list" : "entity_ref",
      options: [],
      target: Object.keys(target).length ? target : null,
    };
  }

  async function submitInputsDialog() {
    const entry = inputsDialogEntry;
    if (!entry) return;
    const declared = effectivePromptInputs(entry);
    const missing = declared.filter((input) => {
      if (!input.required) return false;
      const raw = inputsDialogDrafts[input.name];
      if (input.type === "entity_ref_list") {
        const list = refInputDraftValue(input, raw);
        return !Array.isArray(list) || list.length === 0;
      }
      return !raw?.trim();
    });
    if (missing.length > 0) {
      aiError = `Missing required: ${missing.map((i) => i.label || i.name).join(", ")}.`;
      return;
    }
    const values: Record<string, unknown> = {};
    for (const input of declared) {
      const raw = inputsDialogDrafts[input.name] ?? "";
      const coerced = coerceInputValue(raw, input.type);
      if (coerced !== null && coerced !== "") values[input.name] = coerced;
    }
    const pickedAssistantId = inputsDialogAssistantId;
    inputsDialogEntry = null;
    inputsDialogDrafts = {};
    inputsDialogAssistantId = "";
    await runPromptEntry(entry, values, pickedAssistantId);
  }

  function handleInputsDialogKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      cancelInputsDialog();
    } else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      void submitInputsDialog();
    }
  }

  async function runPromptEntryWithInputs(
    entry: PromptEntrySummary,
    inputs: Record<string, unknown>,
    assistantId: string = "",
  ) {
    if (!editor || !scene) return;
    const outputKind = effectiveOutputKind(entry);
    if (outputKind === "chat_panel") {
      lastInvokedEntryId = entry.id;
      lastInvokedInputs = inputs;
      lastInvokedAssistantId = assistantId;
      dispatch("open-chat", { entry, inputs, sceneId: scene.id, assistantId });
      return;
    }
    if (outputKind !== "append_to_body" && outputKind !== "replace_selection") {
      aiError = `Output kind "${outputKind ?? "(unset)"}" is not yet supported for inline dispatch.`;
      updateAIToolbarPosition();
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
        aiAnchorPos = from;
        aiError = "Select text to revise.";
        updateAIToolbarPosition();
        return;
      }
      selectionText = editor.state.doc.textBetween(from, to, "\n\n", " ");
      if (!selectionText.trim()) {
        aiAnchorPos = from;
        aiError = "Select non-empty text to revise.";
        updateAIToolbarPosition();
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

    aiError = null;
    aiAnchorPos = from;
    aiGenerating = true;
    lastInvokedEntryId = entry.id;
    lastInvokedInputs = inputs;
    lastInvokedAssistantId = assistantId;
    updateAIToolbarPosition();

    const suggestionId = `ai-${aiNextSuggestionId++}`;
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
          aiError = "Document changed during the AI call. Re-select the text and retry.";
          streamErrored = true;
          return;
        }
        editor.chain().focus().setTextSelection({ from, to }).deleteSelection().run();
        startPos = editor.state.selection.from;
        aiSuggestionOriginal = selectionText!;
      } else {
        startPos = editor.state.selection.from;
      }
      aiSuggestionId = suggestionId;
      streamingActive = true;
    };

    try {
      for await (const ev of api.aiGenerateStream({
        template_source: entry.body_markdown,
        target_scene_id: scene.id,
        session_id: scene.id,
        inputs,
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
          renderStreamingSuggestion(startPos, accumulated, suggestionId);
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
          aiError = ev.error || "Unknown error";
          streamErrored = true;
          if (streamingActive && editor) {
            // Roll back: if we were revising, restore the original text; if appending, drop what we inserted.
            const range = findAISuggestionRange(suggestionId);
            if (range) {
              if (outputKind === "replace_selection" && aiSuggestionOriginal) {
                editor
                  .chain()
                  .setTextSelection({ from: range.from, to: range.to })
                  .deleteSelection()
                  .insertContent(aiSuggestionOriginal)
                  .run();
              } else {
                editor
                  .chain()
                  .setTextSelection({ from: range.from, to: range.to })
                  .deleteSelection()
                  .run();
              }
            }
            aiSuggestionId = null;
            aiSuggestionOriginal = null;
          }
        }
      }
      if (!streamErrored) {
        if (!accumulated.trim()) {
          aiError = "Model returned empty output.";
        } else if (lastMeta) {
          aiSuggestionMeta = {
            provider: lastMeta.provider,
            model: lastMeta.model,
            latency_ms: lastMeta.latency_ms,
            truncated: lastMeta.truncated,
            wordCount: countWords(accumulated),
            usage: lastMeta.usage,
            cost_usd: lastMeta.cost_usd,
          };
          if (typeof lastMeta.cost_usd === "number") {
            lastInvocationCostUsd = lastMeta.cost_usd;
            sceneSessionCostUsd += lastMeta.cost_usd;
          }
          aiAnchorPos = null;
        }
      }
    } catch (e) {
      aiError = (e as Error).message;
    } finally {
      aiGenerating = false;
      updateAIToolbarPosition();
    }
  }

  function renderStreamingSuggestion(startPos: number, fullText: string, suggestionId: string) {
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
    const existing = findAISuggestionRange(suggestionId);
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
    updateAIToolbarPosition();
  }

  function replaceWithAISuggestion(from: number, to: number, newText: string, originalText: string) {
    if (!editor) return;
    const suggestionId = `ai-${aiNextSuggestionId++}`;
    type Inline = { type: "text"; text: string } | { type: "hardBreak" };
    const paragraphs = newText
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

    editor
      .chain()
      .focus()
      .setTextSelection({ from, to })
      .deleteSelection()
      .insertContent(paragraphs)
      .run();
    const endPos = editor.state.selection.from;

    editor
      .chain()
      .setTextSelection({ from, to: endPos })
      .setMark("aiSuggestion", { suggestionId })
      .setTextSelection(endPos)
      .run();

    aiSuggestionId = suggestionId;
    aiSuggestionOriginal = originalText;
    requestAnimationFrame(updateAIToolbarPosition);
  }

  function findPromptEntry(entryId: string | null): PromptEntrySummary | null {
    if (!entryId) return null;
    return promptEntries.find((entry) => entry.id === entryId) ?? null;
  }

  function defaultPromptForSurface(surface: "append_to_body" | "replace_selection"): PromptEntrySummary | null {
    return promptEntriesForSurface(surface)[0] ?? null;
  }

  function updateAIToolbarPosition() {
    if (!editor || !editorFrame) {
      if (aiToolbarPosition.visible) aiToolbarPosition = { x: 0, y: 0, visible: false };
      return;
    }
    // Anchor priority: existing suggestion range > pre-suggestion anchor (loading/error).
    let pos: number | null = null;
    if (aiSuggestionId) {
      const range = findAISuggestionRange(aiSuggestionId);
      if (range) pos = range.from;
    } else if (aiAnchorPos !== null) {
      const docSize = editor.state.doc.content.size;
      pos = Math.max(0, Math.min(aiAnchorPos, docSize));
    }
    if (pos === null) {
      if (aiToolbarPosition.visible) aiToolbarPosition = { x: 0, y: 0, visible: false };
      return;
    }
    try {
      const coords = editor.view.coordsAtPos(pos);
      const frameBounds = editorFrame.getBoundingClientRect();
      aiToolbarPosition = {
        x: coords.left - frameBounds.left + editorFrame.scrollLeft,
        y: coords.top - frameBounds.top + editorFrame.scrollTop,
        visible: true,
      };
    } catch {
      aiToolbarPosition = { x: 0, y: 0, visible: false };
    }
  }

  function dismissAIError() {
    aiError = null;
    aiAnchorPos = null;
    aiToolbarPosition = { x: 0, y: 0, visible: false };
  }

  function insertAISuggestion(text: string) {
    if (!editor) return;
    const suggestionId = `ai-${aiNextSuggestionId++}`;
    const startPos = editor.state.selection.from;

    // Split AI text into ProseMirror paragraph nodes.
    type Inline = { type: "text"; text: string } | { type: "hardBreak" };
    const paragraphs = text
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

    editor.chain().focus().insertContent(paragraphs).run();
    const endPos = editor.state.selection.from;

    editor
      .chain()
      .setTextSelection({ from: startPos, to: endPos })
      .setMark("aiSuggestion", { suggestionId })
      .setTextSelection(endPos)
      .run();

    aiSuggestionId = suggestionId;
    // Defer toolbar positioning until the editor has rendered the new content.
    requestAnimationFrame(updateAIToolbarPosition);
  }

  function findAISuggestionRange(suggestionId: string): { from: number; to: number } | null {
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

  // True iff the prompt entry-type chain includes `roleplay` (so any
  // future sub-type of roleplay still gets character-tagged on Accept).
  function isRoleplayPromptEntry(entry: PromptEntrySummary | null | undefined): boolean {
    if (!entry || !metadataSchema) return false;
    let cursor: string | undefined = entry.entry_type;
    const seen = new Set<string>();
    while (cursor && !seen.has(cursor)) {
      if (cursor === "roleplay") return true;
      seen.add(cursor);
      cursor = metadataSchema.entry_types[cursor]?.parent ?? undefined;
    }
    return false;
  }

  // Pull the first lore id from a context_pick input value. Frontend
  // serializes context_pick as a JSON-string list of refs (see
  // resolveContextPickToken / PromptInputField). Returns null for any
  // other shape, including legacy bare-string ids (a roleplay invocation
  // always goes through the picker or CLI resolver, both of which
  // produce the JSON-list form).
  function characterIdFromInputValue(value: unknown): string | null {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    if (!trimmed.startsWith("[")) return null;
    try {
      const parsed = JSON.parse(trimmed);
      if (!Array.isArray(parsed) || parsed.length === 0) return null;
      const first = parsed[0];
      if (first && typeof first === "object" && typeof first.id === "string") return first.id;
      return null;
    } catch {
      return null;
    }
  }

  function acceptAISuggestion() {
    if (!editor || !aiSuggestionId) return;
    const range = findAISuggestionRange(aiSuggestionId);
    if (range) {
      const lastEntry = findPromptEntry(lastInvokedEntryId);
      const characterId = isRoleplayPromptEntry(lastEntry)
        ? characterIdFromInputValue(lastInvokedInputs.character)
        : null;
      let chain = editor.chain().focus().setTextSelection(range).unsetMark("aiSuggestion");
      if (characterId) {
        chain = chain.setMark("character", { characterId });
      }
      chain.setTextSelection(range.to).run();
    }
    aiSuggestionId = null;
    aiSuggestionMeta = null;
    aiSuggestionOriginal = null;
    aiAnchorPos = null;
    aiError = null;
    aiToolbarPosition = { x: 0, y: 0, visible: false };
  }

  function revertAISuggestion() {
    if (!editor || !aiSuggestionId) return;
    const range = findAISuggestionRange(aiSuggestionId);
    if (range) {
      if (aiSuggestionOriginal !== null) {
        // Revise discard: replace AI text with the original.
        editor
          .chain()
          .focus()
          .setTextSelection(range)
          .deleteSelection()
          .insertContent(aiSuggestionOriginal)
          .run();
      } else {
        // Continue discard: just delete the inserted text.
        editor.chain().focus().deleteRange(range).run();
      }
    }
    aiSuggestionId = null;
    aiSuggestionMeta = null;
    aiSuggestionOriginal = null;
    aiAnchorPos = null;
    aiError = null;
    aiToolbarPosition = { x: 0, y: 0, visible: false };
  }

  async function retryAISuggestion() {
    if (!aiSuggestionId || aiGenerating || !editor) return;
    const wasRevision = aiSuggestionOriginal !== null;
    const original = aiSuggestionOriginal;
    const range = findAISuggestionRange(aiSuggestionId);
    const entry = findPromptEntry(lastInvokedEntryId);
    if (!entry) {
      aiError = "Original prompt is no longer available.";
      return;
    }

    revertAISuggestion();

    if (wasRevision && original && range) {
      // After revert, the original text occupies [range.from, range.from + original.length].
      const restoredTo = range.from + original.length;
      editor.chain().focus().setTextSelection({ from: range.from, to: restoredTo }).run();
    }
    await runPromptEntry(entry, lastInvokedInputs, lastInvokedAssistantId);
  }

  async function focusAndRun(command: () => void | Promise<void>) {
    try {
      await command();
    } catch {
      // The parent action surfaces failures through the app-level error state.
    } finally {
      openToolbarMenuId = null;
      updateSelectionMenu();
    }
  }

  function markSelectionAsTodo() {
    if (!editor) return;
    const { from, to } = editor.state.selection;
    const selectedText = selectedPlainText();
    if (!selectedText) return;
    const anchorId = createTodoId();
    const docEnd = editor.state.doc.content.size;
    if (from >= to || from > docEnd || to > docEnd) return;
    editor.view.dispatch(editor.state.tr.setSelection(TextSelection.create(editor.state.doc, from, to)));
    editor.chain().focus().setMark("todoAnchor", { anchorId, status: "open", note: "" }).run();
    window.setTimeout(() => syncTodoAnchorDomState(true), 0);
  }

  function createTodoId() {
    const randomId = globalThis.crypto?.randomUUID?.().replace(/-/g, "") ?? Math.random().toString(16).slice(2);
    return `todo_${randomId.slice(0, 12)}`;
  }

  function selectedPlainText() {
    if (!editor) return "";
    const { selection } = editor.state;
    return editor.state.doc.textBetween(selection.from, selection.to, " ").trim();
  }

  function enforceUniqueTodoAnchors() {
    const seenAnchorIds = new Set<string>();
    return removeTodoAnchors((anchorId) => {
      if (seenAnchorIds.has(anchorId)) return true;
      seenAnchorIds.add(anchorId);
      return false;
    });
  }

  function removeTodoAnchors(shouldRemove: (anchorId: string) => boolean) {
    if (!editor || reconcilingTodoAnchors) return false;
    const markType = editor.state.schema.marks.todoAnchor;
    if (!markType) return false;

    let transaction = editor.state.tr;
    editor.state.doc.descendants((node, position) => {
      if (!node.isText) return true;
      for (const mark of node.marks) {
        if (mark.type !== markType) continue;
        const anchorId = String(mark.attrs.anchorId ?? "");
        if (anchorId && shouldRemove(anchorId)) {
          transaction = transaction.removeMark(position, position + node.nodeSize, mark);
        }
      }
      return true;
    });

    if (!transaction.docChanged) return false;
    reconcilingTodoAnchors = true;
    editor.view.dispatch(transaction);
    reconcilingTodoAnchors = false;
    window.setTimeout(() => syncTodoAnchorDomState(true), 0);
    return true;
  }

  function syncTodoAnchorDomState(force = false) {
    if (!editorElement) return;
    for (const element of editorElement.querySelectorAll<HTMLElement>("[data-todo-anchor-id]")) {
      element.dataset.todoId = element.dataset.todoAnchorId;
      delete element.dataset.todoAnchorId;
    }
    for (const element of editorElement.querySelectorAll<HTMLElement>("[data-todo-id]")) {
      element.classList.toggle("todo-anchor-highlight", element.dataset.todoId === highlightedTodoId);
      const status = element.dataset.todoStatus === "done" ? "done" : "open";
      element.title = status === "done" ? "Completed TODO" : "Open TODO";
    }
  }

  function collectSelectedTodoAnchorIds() {
    if (!editor) return new Set<string>();
    const { from, to } = editor.state.selection;
    return collectTodoAnchorIdsInRange(from, to);
  }

  function collectDocumentTodoAnchorIds() {
    if (!editor) return new Set<string>();
    return collectTodoAnchorIdsInRange(0, editor.state.doc.content.size);
  }

  function collectTodoAnchorIdsInRange(from: number, to: number) {
    const anchorIds = new Set<string>();
    if (!editor || from >= to) return anchorIds;
    const markType = editor.state.schema.marks.todoAnchor;
    if (!markType) return anchorIds;
    editor.state.doc.nodesBetween(from, to, (node) => {
      for (const mark of node.marks) {
        if (mark.type === markType && mark.attrs.anchorId) {
          anchorIds.add(String(mark.attrs.anchorId));
        }
      }
    });
    return anchorIds;
  }

  function collectFragmentTodoAnchorIds(fragment: Fragment) {
    const anchorIds = new Set<string>();
    fragment.forEach((node) => {
      collectNodeTodoAnchorIds(node, anchorIds);
    });
    return anchorIds;
  }

  function collectNodeTodoAnchorIds(node: ProseMirrorNode, anchorIds: Set<string>) {
    for (const mark of node.marks) {
      if (mark.type.name === "todoAnchor" && mark.attrs.anchorId) {
        anchorIds.add(String(mark.attrs.anchorId));
      }
    }
    node.content.forEach((child) => collectNodeTodoAnchorIds(child, anchorIds));
  }

  function mapFragmentTodoAnchors(fragment: Fragment, shouldKeep: (anchorId: string) => boolean) {
    const children: ProseMirrorNode[] = [];
    fragment.forEach((node) => {
      children.push(mapNodeTodoAnchors(node, shouldKeep));
    });
    return Fragment.fromArray(children);
  }

  function mapNodeTodoAnchors(node: ProseMirrorNode, shouldKeep: (anchorId: string) => boolean) {
    const content = node.content.size > 0 ? mapFragmentTodoAnchors(node.content, shouldKeep) : node.content;
    const marks = node.marks.filter((mark) => {
      if (mark.type.name !== "todoAnchor") return true;
      const anchorId = String(mark.attrs.anchorId ?? "");
      return Boolean(anchorId) && shouldKeep(anchorId);
    });
    const copy = node.isText ? node : node.copy(content);
    return copy.mark(marks);
  }

  function addTodoAnchorToFragment(fragment: Fragment, anchorId: string) {
    const children: ProseMirrorNode[] = [];
    fragment.forEach((node) => {
      children.push(addTodoAnchorToNode(node, anchorId));
    });
    return Fragment.fromArray(children);
  }

  function addTodoAnchorToNode(node: ProseMirrorNode, anchorId: string) {
    if (!editor) return node;
    const markType = editor.state.schema.marks.todoAnchor;
    if (!markType) return node;
    const content = node.content.size > 0 ? addTodoAnchorToFragment(node.content, anchorId) : node.content;
    const copy = node.isText ? node : node.copy(content);
    if (!node.isText || !node.textContent.trim()) return copy;
    return copy.mark([...copy.marks.filter((mark) => mark.type !== markType), markType.create({ anchorId })]);
  }

  function dispatchEmbeddedTodos() {
    dispatch("embeddedTodos", { todos: collectEmbeddedTodos() });
  }

  function collectEmbeddedTodos() {
    const todosById = new Map<string, EmbeddedTodo>();
    if (!editor) return [];
    const markType = editor.state.schema.marks.todoAnchor;
    if (!markType) return [];
    editor.state.doc.descendants((node) => {
      if (!node.isText) return true;
      for (const mark of node.marks) {
        if (mark.type !== markType) continue;
        const id = String(mark.attrs.anchorId ?? "");
        if (!id) continue;
        const existing = todosById.get(id);
        const text = node.textContent;
        todosById.set(id, {
          id,
          text: existing ? `${existing.text}${text}` : text,
          status: mark.attrs.status === "done" ? "done" : "open",
          note: String(mark.attrs.note ?? ""),
        });
      }
      return true;
    });
    return Array.from(todosById.values());
  }

  export function updateEmbeddedTodo(todoId: string, updates: { status?: "open" | "done"; note?: string }) {
    if (!editor) return;
    updateTodoMark(todoId, updates);
  }

  export function deleteEmbeddedTodo(todoId: string) {
    if (removeTodoAnchors((anchorId) => anchorId === todoId)) {
      emitChange();
    }
  }

  export function highlightEmbeddedTodo(todoId: string) {
    if (!editorElement) return;
    const target = editorElement.querySelector<HTMLElement>(`[data-todo-id="${CSS.escape(todoId)}"]`);
    if (!target) return;
    highlightedTodoId = todoId;
    syncTodoAnchorDomState(true);
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    window.setTimeout(() => {
      if (highlightedTodoId === todoId) {
        highlightedTodoId = null;
        syncTodoAnchorDomState(true);
      }
    }, 2400);
  }

  function updateTodoMark(todoId: string, updates: { status?: "open" | "done"; note?: string }) {
    if (!editor || reconcilingTodoAnchors) return;
    const markType = editor.state.schema.marks.todoAnchor;
    if (!markType) return;
    let transaction = editor.state.tr;
    editor.state.doc.descendants((node, position) => {
      if (!node.isText) return true;
      for (const mark of node.marks) {
        if (mark.type !== markType || mark.attrs.anchorId !== todoId) continue;
        const attrs = {
          ...mark.attrs,
          status: updates.status ?? mark.attrs.status,
          note: updates.note ?? mark.attrs.note,
        };
        transaction = transaction
          .removeMark(position, position + node.nodeSize, mark)
          .addMark(position, position + node.nodeSize, markType.create(attrs));
      }
      return true;
    });
    if (transaction.docChanged) {
      editor.view.dispatch(transaction);
      emitChange();
    }
  }

  function applySelectionHeading(level: 1 | 2 | 3) {
    if (!editor) return;
    if (!extractSelectionToHeading(level)) {
      editor.chain().focus().setHeading({ level }).run();
    }
  }

  function extractSelectionToHeading(level: 1 | 2 | 3) {
    if (!editor) return false;
    return extractPartialTextSelection((selectedContent) => editor!.state.schema.nodes.heading.create({ level }, selectedContent));
  }

  function applySelectionBlockWrap(type: BlockWrapType) {
    if (!editor) return;
    if (extractSelectionToBlockWrap(type)) return;

    if (type === "blockquote") {
      editor.chain().focus().toggleBlockquote().run();
    } else if (type === "bulletList") {
      editor.chain().focus().toggleBulletList().run();
    } else {
      editor.chain().focus().toggleOrderedList().run();
    }
  }

  function extractSelectionToBlockWrap(type: BlockWrapType) {
    if (!editor) return false;
    const { schema } = editor.state;
    const paragraphType = schema.nodes.paragraph;
    const blockquoteType = schema.nodes.blockquote;
    const bulletListType = schema.nodes.bulletList;
    const orderedListType = schema.nodes.orderedList;
    const listItemType = schema.nodes.listItem;

    if (!paragraphType) return false;

    return extractPartialTextSelection((selectedContent) => {
      const paragraph = paragraphType.create(null, selectedContent);
      if (type === "blockquote") {
        return blockquoteType ? blockquoteType.create(null, paragraph) : null;
      }

      if (!listItemType) return null;
      const listItem = listItemType.create(null, paragraph);
      if (type === "bulletList") {
        return bulletListType ? bulletListType.create(null, listItem) : null;
      }
      return orderedListType ? orderedListType.create(null, listItem) : null;
    });
  }

  function extractPartialTextSelection(createSelectedBlock: (selectedContent: Fragment) => ProseMirrorNode | null) {
    if (!editor) return false;
    const { state, view } = editor;
    const { selection } = state;
    const { $from, $to, from, to } = selection;
    const parent = $from.parent;
    const paragraphType = state.schema.nodes.paragraph;

    if (
      selection.empty ||
      !paragraphType ||
      !$from.sameParent($to) ||
      $from.depth !== 1 ||
      !parent.isTextblock
    ) {
      return false;
    }

    const parentStart = $from.start();
    const parentEnd = $from.end();
    if (from === parentStart && to === parentEnd) {
      return false;
    }

    const beforeContent = parent.content.cut(0, from - parentStart);
    const selectedContent = parent.content.cut(from - parentStart, to - parentStart);
    const afterContent = parent.content.cut(to - parentStart, parent.content.size);
    if (selectedContent.size === 0) return false;
    const selectedBlock = createSelectedBlock(selectedContent);
    if (!selectedBlock) return false;

    const replacementNodes = [
      createParagraphNode(beforeContent),
      selectedBlock,
      createParagraphNode(afterContent),
    ].filter(Boolean);

    const transaction = state.tr.replaceWith($from.before(), $from.after(), replacementNodes);
    view.dispatch(transaction.scrollIntoView());
    view.focus();
    return true;
  }

  function createParagraphNode(content: Fragment) {
    if (!editor || content.size === 0) return null;
    return editor.state.schema.nodes.paragraph.create(null, content);
  }

  function toggleToolbarMenu(actionId: string) {
    openToolbarMenuId = openToolbarMenuId === actionId ? null : actionId;
  }

  function getSelectionToolbarActions(): ToolbarAction[] {
    if (!editor) return [];
    const reviseEntries = promptEntriesForSurface("replace_selection");
    const reviseAction: ToolbarAction | null =
      reviseEntries.length === 0
        ? null
        : reviseEntries.length === 1
          ? {
              kind: "button",
              id: `ai-revise:${reviseEntries[0].id}`,
              label: `✨ ${reviseEntries[0].title}`,
              run: () => focusAndRun(() => runPromptEntry(reviseEntries[0])),
            }
          : {
              kind: "menu",
              id: "ai-revise",
              label: "✨ Revise",
              items: reviseEntries.map((entry) => ({
                id: `ai-revise:${entry.id}`,
                label: entry.title,
                run: () => focusAndRun(() => runPromptEntry(entry)),
              })),
            };
    return [
      {
        kind: "button",
        id: "bold",
        label: "B",
        run: () => editor?.chain().focus().toggleBold().run(),
      },
      {
        kind: "button",
        id: "italic",
        label: "I",
        run: () => editor?.chain().focus().toggleItalic().run(),
      },
      {
        kind: "button",
        id: "strike",
        label: "S",
        run: () => editor?.chain().focus().toggleStrike().run(),
      },
      ...(reviseAction ? [reviseAction] : []),
      {
        kind: "menu",
        id: "heading",
        label: "Heading",
        items: [
          {
            id: "paragraph",
            label: "Paragraph",
            run: () => editor?.chain().focus().setParagraph().run(),
          },
          {
            id: "heading-1",
            label: "Heading 1",
            run: () => applySelectionHeading(1),
          },
          {
            id: "heading-2",
            label: "Heading 2",
            run: () => applySelectionHeading(2),
          },
          {
            id: "heading-3",
            label: "Heading 3",
            run: () => applySelectionHeading(3),
          },
        ],
      },
      {
        kind: "menu",
        id: "list",
        label: "List",
        items: [
          {
            id: "bullet-list",
            label: "Bullet List",
            run: () => applySelectionBlockWrap("bulletList"),
          },
          {
            id: "numbered-list",
            label: "Numbered List",
            run: () => applySelectionBlockWrap("orderedList"),
          },
        ],
      },
      {
        kind: "button",
        id: "quote",
        label: "Quote",
        run: () => applySelectionBlockWrap("blockquote"),
      },
      {
        kind: "button",
        id: "todo",
        label: "TODO",
        run: markSelectionAsTodo,
      },
    ];
  }

  function getSlashCommands(): SlashCommand[] {
    if (!editor) return [];
    return [
      {
        group: "Structure",
        label: "Paragraph",
        description: "Return this line to plain prose.",
        run: () => editor?.chain().focus().setParagraph().run(),
      },
      {
        group: "Structure",
        label: "Heading 1",
        description: "Create a top-level heading.",
        run: () => editor?.chain().focus().setHeading({ level: 1 }).run(),
      },
      {
        group: "Structure",
        label: "Heading 2",
        description: "Create a section heading.",
        run: () => editor?.chain().focus().setHeading({ level: 2 }).run(),
      },
      {
        group: "Structure",
        label: "Heading 3",
        description: "Create a smaller section heading.",
        run: () => editor?.chain().focus().setHeading({ level: 3 }).run(),
      },
      {
        group: "Formatting",
        label: "Bullet List",
        description: "Start a simple unordered list.",
        run: () => editor?.chain().focus().toggleBulletList().run(),
      },
      {
        group: "Formatting",
        label: "Numbered List",
        description: "Start an ordered list.",
        run: () => editor?.chain().focus().toggleOrderedList().run(),
      },
      {
        group: "Formatting",
        label: "Quote",
        description: "Format this paragraph as a block quote.",
        run: () => editor?.chain().focus().toggleBlockquote().run(),
      },
      {
        group: "Insert",
        label: "Table",
        description: "Pick a size — or type \"/table NxM\" (rows × cols).",
        run: (args) => {
          const dims = args && args.length > 0 ? parseTableDims(args[0]) : null;
          if (dims) {
            insertTableFromGrid(dims.rows, dims.cols);
          } else {
            openTableGrid();
          }
        },
      },
      ...promptEntriesForSurface("append_to_body")
        .map((entry) => ({
          group: "AI",
          label: entry.title,
          description: promptEntryDescription(entry),
          // Tab-completes to the entry-type id (always slug-shaped, no
          // spaces), so even prompts titled "Untitled Prompt" expand
          // to a usable shell command word like `/roleplay`.
          autocompleteTo: entry.entry_type,
          run: (args?: string[]) => {
            clearSlashTrigger();
            const resolved = args && args.length > 0
              ? resolvePromptPositionalArgs(entry, args)
              : {
                  inputs: undefined as Record<string, unknown> | undefined,
                  satisfied: false,
                  unresolved: [] as Array<{ name: string; label: string; token: string }>,
                };
            if (resolved.inputs && resolved.satisfied) {
              void runPromptEntry(entry, resolved.inputs);
            } else if (resolved.inputs) {
              // Partial: open dialog, write the resolved drafts in, and
              // CLEAR any input whose positional arg failed to resolve so
              // the user doesn't see a stale value from the prior run.
              openInputsDialog(entry);
              for (const [name, value] of Object.entries(resolved.inputs)) {
                updateInputsDialogDraft(name, String(value));
              }
              for (const { name } of resolved.unresolved) {
                updateInputsDialogDraft(name, "");
              }
              if (resolved.unresolved.length > 0) {
                inputsDialogError = resolved.unresolved
                  .map((u) => `Couldn't find “${u.token}” for ${u.label}`)
                  .join(" · ");
              }
            } else {
              void runPromptEntry(entry);
            }
          },
        })),
    ];
  }
</script>

<div class="editor-panel" class:body-hidden={!hasBody}>
  <section class="editor-header">
    {#if scene}
      <div class="scene-title-row">
        <label class="title-label">
          {documentNameLabel}
          <input class="title-input" aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()}`} placeholder={documentNameLabel} bind:value={title} on:input={emitChange} />
        </label>
      </div>
      <div class="editor-hint">
        <span class="editor-hint-text">
          {#if todoStatusHint}
            {todoStatusHint}
          {:else if editorEmpty}
            {documentKind === "scene" ? "Start writing, or type / for commands." : "Start writing."}
          {:else}
            {documentKind === "scene" ? "Select text for formatting. Type / on an empty line for insert commands." : "Select text for formatting."}
          {/if}
        </span>
        {#if documentKind === "scene" && lastInvocationCostUsd != null}
          <span class="continuation-cost-chip" title="Last continuation invocation cost · running total for this scene this session. Resets on reload or scene switch.">
            last {formatCostEur(lastInvocationCostUsd)} · session {formatCostEur(sceneSessionCostUsd)}
          </span>
        {/if}
      </div>
      {#if metadataSchema}
        <section class="scene-metadata" aria-label={`${documentLabel} details`}>
          <div class="metadata-stripe">
            <button class="metadata-toggle" type="button" on:click={() => (metadataExpanded = !metadataExpanded)}>
              <strong>{metadataExpanded ? "Hide Details" : "Show Details"}</strong>
              <span>{metadataSummaryText}</span>
            </button>
            <button
              class="metadata-custom-button"
              type="button"
              on:click={() => dispatch("custom-data", { entryType, kind: documentKind })}
            >
              Edit type…
            </button>
          </div>
          {#if metadataExpanded}
            <div class="metadata-panel">
              <label>
                {documentLabel} Type
                <select value={entryType} on:change={(event) => updateEntryType(event.currentTarget.value)}>
                  {#if entryType && !metadataSchema.entry_types[entryType]}
                    <option value={entryType}>{entryType}</option>
                  {/if}
                  {#each documentEntryTypes as [typeId, definition]}
                    <option value={typeId}>{definition.name}</option>
                  {/each}
                </select>
              </label>
              <div class="metadata-color-row">
                <span>Color</span>
                <SwatchPicker
                  value={metadataValueString(metadata.color) || null}
                  onChange={(id) => {
                    metadata = { ...metadata, color: id ?? "" };
                    emitChange();
                  }}
                />
                {#if !metadataValueString(metadata.color)}
                  {@const inherited = metadataSchema.entry_types[entryType]?.color}
                  {#if inherited}
                    <small class="muted">inherits <code>{inherited}</code> from type</small>
                  {:else}
                    <small class="muted">no override (falls back to type / kind default)</small>
                  {/if}
                {/if}
              </div>
              {#if documentKind === "assistant"}
                <ProviderTierPicker
                  provider={metadataValueString(metadata.ai_provider)}
                  tier={metadataValueString(metadata.ai_capability_tier) as import("./types").AICapabilityTier | ""}
                  model={metadataValueString(metadata.ai_model)}
                  on:change={(event) => {
                    metadata = {
                      ...metadata,
                      ai_provider: event.detail.provider,
                      ai_capability_tier: event.detail.tier,
                      ai_model: event.detail.model,
                    };
                    emitChange();
                  }}
                />
              {/if}
              <div class="metadata-fields">
                {#each metadataFieldIds as fieldId}
                  {#if metadataSchema.fields[fieldId]}
                    {@const field = metadataSchema.fields[fieldId]}
                    {@const currentValue = metadataValueString(metadata[fieldId])}
                    {#if field.type === "long_text"}
                      <div class="metadata-field wide-field">
                        <span class="metadata-field-label">{field.name}</span>
                        <MetadataLongTextEditor
                          ariaLabel={field.name}
                          value={currentValue}
                          matcher={implicitContextMatcher}
                          on:change={(event) => updateMetadataField(fieldId, field, event.detail.value)}
                        />
                      </div>
                    {:else if field.type === "entity_ref" || field.type === "entity_ref_list"}
                      <div class="metadata-field wide-field reference-field">
                        <ReferencePicker
                          {field}
                          value={metadataReferenceValue(field, metadata[fieldId])}
                          metadataSchema={metadataSchema}
                          excludeId={scene?.id ?? null}
                          ariaLabel={field.name}
                          structure={structure}
                          loreEntries={loreEntries}
                          promptEntries={promptEntries}
                          on:change={(event) => updateMetadataField(fieldId, field, event.detail.value)}
                          on:navigate={(event) => dispatch("navigate", event.detail)}
                        />
                      </div>
                    {:else if field.type === "multi_select" && field.options.length > 0}
                      <div class="metadata-field wide-field">
                        <span class="metadata-field-label">{field.name}</span>
                        <div class="multi-select-chips" aria-label={field.name}>
                          {#each field.options as option}
                            <button
                              class:active={isMultiSelectOptionSelected(fieldId, option.value)}
                              class="multi-select-chip"
                              type="button"
                              on:click={() => toggleMultiSelectOption(fieldId, field, option.value)}
                            >
                              {option.label ?? option.value}
                            </button>
                          {/each}
                        </div>
                      </div>
                    {:else}
                      <label class:wide-field={field.type === "computed"}>
                        {field.name}
                        {#if fieldId === "status"}
                          <ColoredSelect
                            value={status}
                            options={field.options}
                            ariaLabel={field.name}
                            placeholder="(no status)"
                            onChange={updateStatus}
                          />
                        {:else if field.type === "select"}
                          <ColoredSelect
                            value={currentValue}
                            options={field.options}
                            ariaLabel={field.name}
                            onChange={(v) => updateMetadataField(fieldId, field, v)}
                          />
                      {:else if field.type === "boolean"}
                        <input
                          type="checkbox"
                          checked={Boolean(metadata[fieldId])}
                          on:change={(event) => updateMetadataField(fieldId, field, event.currentTarget.checked)}
                        />
                      {:else if field.type === "number"}
                        <input
                          type="number"
                          value={currentValue}
                          on:input={(event) => updateMetadataField(fieldId, field, event.currentTarget.value)}
                        />
                      {:else if field.type === "computed"}
                        <input readonly value={computedFieldString(fieldId)} />
                      {:else if field.type === "tags"}
                        <div class="tag-picker-anchor">
                          <div class="tag-field-control">
                            <input
                              value={currentValue}
                              placeholder="Comma-separated values"
                              on:input={(event) => updateMetadataField(fieldId, field, event.currentTarget.value)}
                            />
                            <button class="tag-picker-toggle" type="button" title="Add known tags" on:click={(event) => toggleTagPicker(fieldId, event)}>+</button>
                          </div>
                          {#if tagPickerFieldId === fieldId && tagPickerPosition}
                            <div class="tag-picker" style={`left: ${tagPickerPosition.x}px; top: ${tagPickerPosition.y}px; width: ${tagPickerPosition.width}px;`} aria-label={`${field.name} known tags`}>
                              {#if knownTags.length > 0}
                                {#each knownTags as tag}
                                  <button class:active={hasTag(fieldId, tag)} type="button" on:mousedown|preventDefault on:click={() => addKnownTag(fieldId, field, tag)}>{tag}</button>
                                {/each}
                              {:else}
                                <span>No known tags yet.</span>
                              {/if}
                            </div>
                          {/if}
                        </div>
                      {:else}
                        <input
                          value={currentValue}
                          placeholder={field.type === "multi_select" ? "Comma-separated values" : ""}
                          on:input={(event) => updateMetadataField(fieldId, field, event.currentTarget.value)}
                        />
                        {/if}
                      </label>
                    {/if}
                  {/if}
                {/each}
              </div>
            </div>
          {/if}
        </section>
        <section class="scene-backlinks" aria-label="Incoming references">
          <NodeRow
            title="References"
            groupHeader
            collapsed={!backlinksExpanded}
            onClick={() => (backlinksExpanded = !backlinksExpanded)}
          >
            {#snippet leading()}
              <span class:collapsed={!backlinksExpanded} class="lore-group-caret" aria-hidden="true">▾</span>
            {/snippet}
            {#snippet trailing()}
              <span class="group-count-pill">{backlinks.length}</span>
            {/snippet}
            {#snippet children()}
              <NodeList mode="tree" isEmpty={backlinks.length === 0}>
                {#snippet whenEmpty()}
                  <p class="muted">No incoming references.</p>
                {/snippet}
                {#each backlinks as link (`${link.id}:${link.field_id}`)}
                  {@const pillHex = backlinkSwatchHex(link)}
                  <NodeRow
                    title={link.title}
                    onClick={() => dispatch("navigate", { id: link.id, kind: link.kind })}
                  >
                    {#snippet trailing()}
                      <span
                        class="backlink-type-pill"
                        class:has-color={!!pillHex}
                        style={pillHex ? `--chip-base: ${pillHex}` : ""}
                      >{metadataSchema?.entry_types[link.entry_type]?.name ?? link.entry_type ?? link.kind}</span>
                    {/snippet}
                  </NodeRow>
                {/each}
              </NodeList>
            {/snippet}
          </NodeRow>
        </section>
      {/if}
    {:else}
      <h2>Select a scene</h2>
    {/if}
  </section>

  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class:empty-editor={editorEmpty}
    class:lore-editor={documentKind === "lore"}
    class:hidden-body={!hasBody}
    class="editor-wrap"
    bind:this={editorFrame}
    on:mousedown={(event) => {
      // Click landed on the wrap itself (the gutter around the centered
      // 780px column or below short content) — focus the editor at the
      // end of the doc so the cursor lands where the user expects.
      // Clicks inside .editor-body bubble here too, but ProseMirror
      // has already handled them; checking event.target === currentTarget
      // restricts our handler to the dead-space case.
      if (event.target === event.currentTarget) {
        event.preventDefault();
        editor?.chain().focus("end").run();
      }
    }}
  >
    {#if aiToolbarPosition.visible && (aiGenerating || aiSuggestionId || aiError)}
      <div
        class="ai-inline-toolbar"
        class:ai-inline-toolbar-loading={aiGenerating}
        class:ai-inline-toolbar-error={aiError && !aiSuggestionId}
        style={`left: ${aiToolbarPosition.x}px; top: ${aiToolbarPosition.y}px;`}
      >
        {#if aiGenerating}
          <span class="ai-toolbar-spinner" aria-hidden="true">⟳</span>
          <span class="ai-toolbar-status">Generating…</span>
        {:else if aiError && !aiSuggestionId}
          <span class="ai-toolbar-status">⚠ {aiError}</span>
          <button type="button" class="ai-toolbar-btn" on:mousedown|preventDefault={dismissAIError} title="Dismiss">
            <span aria-hidden="true">✕</span> Dismiss
          </button>
        {:else if aiSuggestionId}
          <button type="button" class="ai-toolbar-btn ai-toolbar-accept" on:mousedown|preventDefault={acceptAISuggestion} title="Accept (keep the text)">
            <span aria-hidden="true">✓</span> Accept
          </button>
          <button type="button" class="ai-toolbar-btn" on:mousedown|preventDefault={retryAISuggestion} title="Retry (regenerate)" disabled={aiGenerating}>
            <span aria-hidden="true">↻</span> Retry
          </button>
          <button type="button" class="ai-toolbar-btn ai-toolbar-discard" on:mousedown|preventDefault={revertAISuggestion} title="Discard (delete the text)">
            <span aria-hidden="true">✕</span> Discard
          </button>
          {#if aiSuggestionMeta}
            <span class="ai-toolbar-meta">
              {aiSuggestionMeta.wordCount} words, {aiSuggestionMeta.model}{#if aiSuggestionMeta.truncated} · truncated{/if}
              {#if aiSuggestionMeta.usage}
                {@const u = aiSuggestionMeta.usage}
                {@const totalIn = u.input_tokens + u.cached_input_tokens + u.cache_write_tokens}
                {@const cachePct = totalIn > 0 ? Math.round((u.cached_input_tokens / totalIn) * 100) : 0}
                <span class="ai-toolbar-meta-sep" title={`Input: ${totalIn} tok (${u.cached_input_tokens} cached, ${u.cache_write_tokens} written). Output: ${u.output_tokens} tok.`}>
                  · {totalIn} → {u.output_tokens} tok{#if cachePct > 0} · {cachePct}% cached{/if}
                </span>
              {/if}
              {#if aiSuggestionMeta.cost_usd != null}
                <span class="ai-toolbar-meta-cost">· {formatCostEur(aiSuggestionMeta.cost_usd)}</span>
              {/if}
            </span>
          {/if}
        {/if}
      </div>
    {/if}
    {#if selectionMenu.visible}
      <div class:below={selectionMenu.placement === "below"} class="selection-toolbar" style={`left: ${selectionMenu.x}px; top: ${selectionMenu.y}px;`}>
        <span class="selection-count">{selectionMenu.wordCount} {selectionMenu.wordCount === 1 ? "word" : "words"}</span>
        {#each selectionToolbarActions as action}
          {#if action.kind === "button"}
            <button type="button" on:mousedown|preventDefault={() => focusAndRun(action.run)}>{action.label}</button>
          {:else}
            <div class="toolbar-menu">
              <button
                class:open={openToolbarMenuId === action.id}
                type="button"
                on:mousedown|preventDefault={() => toggleToolbarMenu(action.id)}
              >
                {action.label}
              </button>
              {#if openToolbarMenuId === action.id}
                <div class:below={selectionMenu.placement === "below"} class="toolbar-menu-popover">
                  {#each action.items as item}
                    <button type="button" on:mousedown|preventDefault={() => focusAndRun(item.run)}>{item.label}</button>
                  {/each}
                </div>
              {/if}
            </div>
          {/if}
        {/each}
      </div>
    {/if}

    {#if slashMenu.visible}
      <div class:table-mode={slashMenu.mode === "table-grid"} class="slash-menu" style={`left: ${slashMenu.x}px; top: ${slashMenu.y}px;`}>
        {#if slashMenu.mode === "table-grid"}
          <div class="table-grid">
            {#each Array(TABLE_GRID_MAX_ROWS) as _, rowIndex}
              <div class="table-grid-row">
                {#each Array(TABLE_GRID_MAX_COLS) as _, colIndex}
                  <button
                    class:active={rowIndex < slashMenu.gridRows && colIndex < slashMenu.gridCols}
                    type="button"
                    aria-label={`${rowIndex + 1} rows by ${colIndex + 1} columns`}
                    on:mouseenter={() => (slashMenu = { ...slashMenu, gridRows: rowIndex + 1, gridCols: colIndex + 1 })}
                    on:mousedown|preventDefault={() => insertTableFromGrid(rowIndex + 1, colIndex + 1)}
                  ></button>
                {/each}
              </div>
            {/each}
          </div>
          <div class="table-grid-label">{slashMenu.gridCols} × {slashMenu.gridRows}</div>
        {:else}
          {#if slashFilterText}
            <div class="slash-filter-indicator">filter: <code>{slashFilterText}</code></div>
          {/if}
          {#if filteredSlashCommands.length === 0}
            <div class="slash-empty">No commands match "<code>{slashFilterText}</code>"</div>
          {/if}
          {#each filteredSlashCommands as command, index}
            {#if index === 0 || filteredSlashCommands[index - 1].group !== command.group}
              <div class="slash-group">{command.group}</div>
            {/if}
            <button
              class:active={index === slashMenu.selectedIndex}
              type="button"
              on:mouseenter={() => (slashMenu = { ...slashMenu, selectedIndex: index })}
              on:mousedown|preventDefault={() => runSlashCommand(command)}
            >
              <strong>{command.label}</strong>
              <span>{command.description}</span>
            </button>
          {/each}
        {/if}
      </div>
    {/if}

    {#if tableMenu.visible}
      <div class="table-toolbar" style={`left: ${tableMenu.x}px; top: ${tableMenu.y}px;`}>
        <button type="button" title="Insert column before" on:mousedown|preventDefault={() => editor?.chain().focus().addColumnBefore().run()}>+ col ←</button>
        <button type="button" title="Insert column after" on:mousedown|preventDefault={() => editor?.chain().focus().addColumnAfter().run()}>+ col →</button>
        <button type="button" title="Delete column" on:mousedown|preventDefault={() => editor?.chain().focus().deleteColumn().run()}>− col</button>
        <span class="table-toolbar-sep" aria-hidden="true"></span>
        <button type="button" title="Insert row above" on:mousedown|preventDefault={() => editor?.chain().focus().addRowBefore().run()}>+ row ↑</button>
        <button type="button" title="Insert row below" on:mousedown|preventDefault={() => editor?.chain().focus().addRowAfter().run()}>+ row ↓</button>
        <button type="button" title="Delete row" on:mousedown|preventDefault={() => editor?.chain().focus().deleteRow().run()}>− row</button>
        <span class="table-toolbar-sep" aria-hidden="true"></span>
        <button type="button" title="Align left" on:mousedown|preventDefault={() => setCellAlign("left")}>⟵</button>
        <button type="button" title="Align center" on:mousedown|preventDefault={() => setCellAlign("center")}>↔</button>
        <button type="button" title="Align right" on:mousedown|preventDefault={() => setCellAlign("right")}>⟶</button>
        <span class="table-toolbar-sep" aria-hidden="true"></span>
        <button type="button" title="Toggle header row" on:mousedown|preventDefault={() => editor?.chain().focus().toggleHeaderRow().run()}>Hdr row</button>
        <button type="button" title="Toggle header column" on:mousedown|preventDefault={() => editor?.chain().focus().toggleHeaderColumn().run()}>Hdr col</button>
        <span class="table-toolbar-sep" aria-hidden="true"></span>
        <button type="button" title="Delete table" on:mousedown|preventDefault={() => editor?.chain().focus().deleteTable().run()}>Delete</button>
      </div>
    {/if}

    {#if rawBodyMode}
      <div class="raw-body-editor">
        <CodeEditor bind:value={rawBody} language={rawBodyLanguage} diagnostics={documentKind === "prompt" ? promptPreviewDiagnostics : []} />
      </div>
    {/if}
    <div bind:this={editorElement} class:hidden={rawBodyMode}></div>

    {#if documentKind === "prompt" && scene}
      <button
        type="button"
        class="prompt-help-button"
        bind:this={helpButtonEl}
        class:active={cheatsheetPopoverOpen}
        title="Variables & helpers — what you can reference in &lbrace;&lbrace; … &rbrace;&rbrace; and &lbrace;% … %&rbrace;"
        aria-label="Show variables and helpers reference"
        aria-expanded={cheatsheetPopoverOpen}
        on:click={toggleCheatsheetPopover}
      >?</button>
    {/if}

  </div>

  {#if documentKind === "prompt" && scene}
      {#if cheatsheetPopoverOpen}
        <div class="prompt-help-popover" role="dialog" aria-label="Variables and helpers" style="top: {popoverPos.top}px; right: {popoverPos.right}px;">
          <header class="prompt-help-popover-header">
            <strong>Variables &amp; helpers</strong>
            <small>what you can reference in <code>&lbrace;&lbrace; … &rbrace;&rbrace;</code> and <code>&lbrace;% … %&rbrace;</code></small>
            <button type="button" class="prompt-help-popover-close" aria-label="Close" on:click={() => (cheatsheetPopoverOpen = false)}>×</button>
          </header>
        <div class="prompt-cheatsheet-body">
          <section>
            <h4>Variables</h4>
            <dl>
              <dt><code>scene</code></dt>
              <dd>The target scene. <code>scene.title</code>, <code>scene.body_markdown</code>, <code>scene.entry_type</code>, <code>scene.&lt;field&gt;</code> for any field on the scene (e.g. <code>scene.summary</code>, <code>scene.pov.title</code>). Entity-ref fields auto-resolve.</dd>
              <dt><code>project</code> / <code>novel</code></dt>
              <dd>Project info (title, root path, AI policy). Both names point to the same value.</dd>
              <dt><code>text_before</code> / <code>text_after</code></dt>
              <dd>Body markdown around the cursor in the current scene. Empty string when not dispatched from an editor.</dd>
              <dt><code>selection</code></dt>
              <dd>The selected text in the editor, or empty string.</dd>
              <dt><code>date</code></dt>
              <dd>Today as an ISO string (e.g. <code>2026-06-20</code>). Also <code>date.today</code> and <code>date.iso</code>.</dd>
              <dt><code>input.&lt;id&gt;</code></dt>
              <dd>The value of an input declared on this prompt (see the Inputs panel below).</dd>
            </dl>
          </section>
          <section>
            <h4>Helpers</h4>
            <dl>
              <dt><code>pov(scene)</code></dt>
              <dd>POV character as an EntryRef, or <code>None</code> when the scene has no <code>pov</code> ref.</dd>
              <dt><code>relevant_lore(scene, mode="implicit", partition="all")</code></dt>
              <dd>XML <code>&lt;lore&gt;</code> block of entries in scope for the scene. Modes: <code>implicit</code>, <code>explicit</code>, <code>pinned_only</code>. Partitions (session-bound): <code>all</code>, <code>stable</code>, <code>volatile</code>.</dd>
              <dt><code>scenes_before(scene)</code></dt>
              <dd>XML <code>&lt;story_so_far&gt;</code> of prior scenes' summaries in manuscript order.</dd>
              <dt><code>last_words(text, n)</code></dt>
              <dd>Trailing <code>n</code> words of a string. Pure helper — useful for continuation prompts.</dd>
              <dt><code>full_outline()</code></dt>
              <dd>Nested list of outline nodes (<code>.title</code>, <code>.summary</code>, <code>.children</code>) — the whole book's shape.</dd>
              <dt><code>full_text()</code></dt>
              <dd>Every scene's prose in manuscript order (<code>.title</code>, <code>.body</code>). Heavy.</dd>
              <dt><code>entry(id_or_ref)</code></dt>
              <dd>Wrap a raw entry id as an EntryRef so you can walk its fields: <code>&lbrace;&lbrace; entry(scene.metadata.pov).title &rbrace;&rbrace;</code>. Also accepts the value of a <code>context_pick</code> input (first picked ref wins) — <code>&lbrace;&lbrace; entry(input.character).title &rbrace;&rbrace;</code>.</dd>
              <dt><code>character_thread(scene, character)</code></dt>
              <dd>Per-character chat thread for the Roleplay sub-type. Walks the scene body's <code>data-character</code> spans: focus character → <code>assistant</code> turns, others → <code>user</code> prefixed <code>[Name]:</code>, untagged narration → plain <code>user</code>. No markers yet → whole body as one user message. <strong>Use OUTSIDE any <code>&lbrace;% role %&rbrace;</code> block</strong> — emits its own role boundaries. See <code>docs/roleplay.md</code>.</dd>
            </dl>
          </section>
        </div>
      </div>
      {/if}

    <details class="entry-inputs-editor" bind:open={entryInputsExpanded}>
      <summary>
        Inputs <small>{entryInputDrafts.length}</small>
        <small class="entry-inputs-hint">declared on this prompt · use as <code>&lbrace;&lbrace; input.&lt;id&gt; &rbrace;&rbrace;</code></small>
      </summary>
      {#if entryInputDrafts.length === 0}
        <p class="muted entry-inputs-empty">No inputs yet. Click + Input to declare one.</p>
      {/if}
      {#each entryInputDrafts as draft, index (draft.clientId)}
        {#if draft.type === "context_pick"}
          <!-- PR 2: context_pick owns its entire row (chevron · label ·
               id · type select · Required · Multiple · ×). Generic
               input types still render the .prompt-input-grid below. -->
          <div
            class="prompt-input-row prompt-input-row-context"
            class:dragging={inputDragFromIndex === index}
            class:drop-before={inputDragOverIndex === index && inputDragOverPosition === "before"}
            class:drop-after={inputDragOverIndex === index && inputDragOverPosition === "after"}
            on:dragover={(e) => handleInputDragOver(e, index)}
            on:drop={(e) => handleInputDrop(e, index)}
          >
            <span
              class="tree-handle prompt-input-handle"
              draggable="true"
              role="button"
              tabindex="-1"
              aria-label="Drag to reorder"
              on:dragstart={(e) => handleInputDragStart(e, index)}
              on:dragend={handleInputDragEnd}
            >⋮⋮</span>
            <NodePickerConfigEditor
              config={draft.nodePickerConfig}
              metadataSchema={metadataSchema}
              label={draft.label}
              name={draft.name}
              required={draft.required}
              on:change={(event) => updateEntryInputNodePickerConfig(index, event.detail.config)}
              on:labelchange={(event) => updateEntryInputLabel(index, event.detail.value)}
              on:namechange={(event) => updateEntryInputName(index, event.detail.value)}
              on:requiredchange={(event) => updateEntryInput(index, { required: event.detail.value })}
              on:typechange={(event) => updateEntryInput(index, { type: event.detail.value })}
              on:remove={() => removeEntryInput(index)}
            />
          </div>
        {:else}
          <div
            class="prompt-input-row"
            class:dragging={inputDragFromIndex === index}
            class:drop-before={inputDragOverIndex === index && inputDragOverPosition === "before"}
            class:drop-after={inputDragOverIndex === index && inputDragOverPosition === "after"}
            on:dragover={(e) => handleInputDragOver(e, index)}
            on:drop={(e) => handleInputDrop(e, index)}
          >
            <span
              class="tree-handle prompt-input-handle"
              draggable="true"
              role="button"
              tabindex="-1"
              aria-label="Drag to reorder"
              on:dragstart={(e) => handleInputDragStart(e, index)}
              on:dragend={handleInputDragEnd}
            >⋮⋮</span>
            <div class="prompt-input-grid">
              <label>
                Label
                <input value={draft.label} placeholder="Topic to brainstorm" on:input={(e) => updateEntryInputLabel(index, (e.currentTarget as HTMLInputElement).value)} />
              </label>
              <label>
                ID
                <input value={draft.name} placeholder="topic_to_brainstorm" on:input={(e) => updateEntryInputName(index, (e.currentTarget as HTMLInputElement).value)} />
                {#if draft.name}
                  <small class="prompt-input-accessor"><code>&lbrace;&lbrace; input.{draft.name} &rbrace;&rbrace;</code></small>
                {/if}
              </label>
              <label>
                Type
                <select value={draft.type} on:change={(e) => updateEntryInput(index, { type: (e.currentTarget as HTMLSelectElement).value as import("./types").PromptInputType })}>
                  <option value="text">Text</option>
                  <option value="long_text">Long Text</option>
                  <option value="number">Number</option>
                  <option value="boolean">Boolean</option>
                  <option value="select">Select</option>
                  <option value="entity_ref">Entity Reference</option>
                  <option value="entity_ref_list">Entity Reference List</option>
                  <option value="context_pick">Context Picker</option>
                </select>
              </label>
              <label>
                Default
                <input value={draft.defaultValue} placeholder="" on:input={(e) => updateEntryInput(index, { defaultValue: (e.currentTarget as HTMLInputElement).value })} />
              </label>
              {#if draft.type === "select"}
                <label class="prompt-input-options">
                  Options
                  <input value={draft.options} placeholder="quick, thorough" on:input={(e) => updateEntryInput(index, { options: (e.currentTarget as HTMLInputElement).value })} />
                </label>
              {/if}
              {#if draft.type === "entity_ref" || draft.type === "entity_ref_list"}
                <label>
                  Target kind
                  <select value={draft.targetKind} on:change={(e) => updateEntryInput(index, { targetKind: (e.currentTarget as HTMLSelectElement).value as "" | "scene" | "lore" })}>
                    <option value="">Any</option>
                    <option value="scene">Scene</option>
                    <option value="lore">Lore</option>
                  </select>
                </label>
                <label>
                  Target entry type
                  <input value={draft.targetEntryType} placeholder="" on:input={(e) => updateEntryInput(index, { targetEntryType: (e.currentTarget as HTMLInputElement).value })} />
                </label>
              {/if}
              <label class="prompt-input-required">
                <input type="checkbox" checked={draft.required} on:change={(e) => updateEntryInput(index, { required: (e.currentTarget as HTMLInputElement).checked })} />
                Required
              </label>
              <button type="button" class="prompt-input-remove" title="Remove input" on:click={() => removeEntryInput(index)}>×</button>
            </div>
          </div>
        {/if}
      {/each}
      <div class="entry-inputs-add">
        <button type="button" on:click={addEntryInput}>+ Input</button>
      </div>
    </details>
    <!-- Vertical split: editor above gets the remaining space when the
         preview is expanded; collapsed by default so the body editor is
         the primary focus. The header toggles open/closed; the handle
         between editor and preview resizes the preview when expanded. -->
    {#if !promptPreviewCollapsed}
      <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
      <div
        class="prompt-preview-resize"
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize prompt preview"
        on:mousedown={startPromptPreviewResize}
      ></div>
    {/if}
    <section
      class="prompt-preview-pane"
      class:collapsed={promptPreviewCollapsed}
      style={promptPreviewCollapsed ? "" : `height: ${promptPreviewPaneHeight}px;`}
    >
      <header class="prompt-preview-pane-header">
        <button
          type="button"
          class="prompt-preview-toggle"
          aria-expanded={!promptPreviewCollapsed}
          on:click={() => (promptPreviewCollapsed = !promptPreviewCollapsed)}
        >
          <span class="prompt-preview-caret" aria-hidden="true">{promptPreviewCollapsed ? "▸" : "▾"}</span>
          <strong>Preview</strong>
        </button>
        <div class="prompt-preview-pane-meta">
          {#if promptPreviewRunning}
            <span class="prompt-preview-status">rendering…</span>
          {:else if promptPreviewResult}
            <span class="prompt-preview-status">{promptPreviewResult.messages.length} msg · {promptPreviewResult.char_count} chars</span>
            {#if promptPreviewResult.estimated_tokens}
              <span class="prompt-preview-cost" title="Estimated tokens (universal tokenizer; provider-specific counts may vary slightly).">
                · {formatTokens(promptPreviewResult.estimated_tokens)} tok
              </span>
            {/if}
            {#if promptPreviewResult.estimated_cost_usd != null}
              <span class="prompt-preview-cost" title="Estimated input cost (output cost depends on the response; not included).">
                · {formatCostEur(promptPreviewResult.estimated_cost_usd)}
              </span>
            {/if}
          {/if}
          {#if !promptPreviewCollapsed}
            <button type="button" disabled={promptPreviewRunning || !rawBody.trim()} on:click={runPromptPreview}>
              {promptPreviewRunning ? "Rendering…" : "Render now"}
            </button>
          {/if}
        </div>
      </header>

      {#if !promptPreviewCollapsed}
      <div class="prompt-preview-pane-controls">
        {#if promptPreviewDeclaredInputs.length > 0}
          <div class="prompt-preview-inputs">
            <div class="prompt-preview-inputs-heading">
              Inputs
              <small>{promptPreviewDeclaredInputs.length}</small>
              <small class="prompt-preview-inputs-hint">use in template as <code>&lbrace;&lbrace; input.&lt;name&gt; &rbrace;&rbrace;</code></small>
            </div>
            {#each promptPreviewDeclaredInputs as inputDef (inputDef.name)}
              {@const draft = promptPreviewInputDrafts[inputDef.name]}
              {@const isMissing = inputDef.required && (draft === undefined || draft === null || (typeof draft === "string" && !draft.trim()))}
              <label class="prompt-preview-field" class:missing-required={isMissing}>
                <span class="prompt-preview-field-label">
                  <span class="prompt-preview-field-name">
                    {inputDef.label || inputDef.name}{#if inputDef.required}<span class="required-marker"> *</span>{/if}
                  </span>
                  <button
                    type="button"
                    class="prompt-preview-field-accessor"
                    title="Click to copy"
                    on:click|preventDefault={() => navigator.clipboard?.writeText(`{{ input.${inputDef.name} }}`).catch(() => {})}
                  ><code>&lbrace;&lbrace; input.{inputDef.name} &rbrace;&rbrace;</code></button>
                </span>
                <PromptInputField
                  input={inputDef}
                  value={draft ?? ""}
                  metadataSchema={metadataSchema}
                  excludeId={scene?.id ?? null}
                  ariaLabel={inputDef.label || inputDef.name}
                  structure={structure}
                  loreEntries={loreEntries}
                  promptEntries={promptEntries}
                  on:change={(event) => promptPreviewInputDrafts = {...promptPreviewInputDrafts, [inputDef.name]: event.detail.value}}
                />
              </label>
            {/each}
          </div>
        {/if}
      </div>

      {#if promptPreviewResult && promptPreviewResult.cache_blocks && promptPreviewResult.cache_blocks.length > 1 && promptPreviewResult.caching_style === "explicit"}
        <div class="prompt-preview-cache-strip" title="Per-cache-block token sizes. The first segment is the cacheable prefix.">
          {#each promptPreviewResult.cache_blocks as block, i}
            <span class="prompt-preview-cache-chip" class:cache-strip-break={block.cache_break_after}>
              {block.label} {formatTokens(block.tokens)}
            </span>
            {#if i < promptPreviewResult.cache_blocks.length - 1}<span class="prompt-preview-cache-sep">·</span>{/if}
          {/each}
        </div>
      {/if}

      <div class="prompt-preview-pane-body">
        {#if promptPreviewError}
          <p class="prompt-preview-error">{promptPreviewError}</p>
        {/if}
        {#if promptPreviewMissingRequired.length > 0}
          <p class="prompt-preview-required-notice">
            {promptPreviewMissingRequired.length} required input{promptPreviewMissingRequired.length === 1 ? "" : "s"} empty:
            {promptPreviewMissingRequired.map((i) => i.label || i.name).join(", ")} — the rendered output below will have empty slots wherever this is referenced.
          </p>
        {/if}

        {#if !rawBody.trim()}
          <p class="prompt-preview-empty muted">Type a template above to see the rendered output here.</p>
        {:else if promptPreviewResult}
          {#if promptPreviewResult.warnings.length > 0}
            <div class="prompt-preview-warnings">
              <strong>Warnings</strong>
              {#each promptPreviewResult.warnings as warning}
                <p>{warning}</p>
              {/each}
            </div>
          {/if}
          {#each promptPreviewResult.messages as message}
            <div class="prompt-preview-message prompt-preview-message-{message.role}">
              <header class="prompt-preview-message-role">{message.role}</header>
              {#each message.blocks as block}
                <pre class="prompt-preview-block">{block.text}</pre>
                {#if block.cache_break_after}
                  <div class="prompt-preview-cache-break" aria-label="cache breakpoint">cache_break</div>
                {/if}
              {/each}
            </div>
          {/each}
        {:else if !promptPreviewRunning && !promptPreviewError}
          <p class="prompt-preview-empty muted">Waiting for first render…</p>
        {/if}
      </div>
      {/if}
    </section>
  {/if}

  <footer class="status">
    {#if scene}
      {dirty ? "Unsaved changes" : `Loaded ${scene.title}`}
    {:else}
      No scene open
    {/if}
  </footer>
</div>

{#if inputsDialogEntry}
  {@const declaredInputs = effectivePromptInputs(inputsDialogEntry)}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="inputs-dialog-backdrop" role="presentation" on:mousedown|self={cancelInputsDialog}>
    <div class="inputs-dialog" role="dialog" aria-label={`Run ${inputsDialogEntry.title}`} aria-modal="true" tabindex="-1" on:keydown={handleInputsDialogKeydown}>
      <header>
        <strong>{inputsDialogEntry.title}</strong>
        <small>{promptEntryDescription(inputsDialogEntry)}</small>
      </header>
      {#if inputsDialogError}
        <div class="inputs-dialog-error" role="alert">{inputsDialogError}</div>
      {/if}
      <div class="inputs-dialog-fields">
        {#each declaredInputs as input (input.name)}
          <label>
            {input.label || input.name}{#if input.required}<span class="required-marker"> *</span>{/if}
            <PromptInputField
              input={input}
              value={inputsDialogDrafts[input.name] ?? ""}
              metadataSchema={metadataSchema}
              excludeId={scene?.id ?? null}
              ariaLabel={input.label || input.name}
              structure={structure}
              loreEntries={loreEntries}
              promptEntries={promptEntries}
              on:change={(event) => updateInputsDialogDraft(input.name, event.detail.value)}
            />
          </label>
        {/each}
        <label>
          Assistant
          <select bind:value={inputsDialogAssistantId}>
            <option value="">Default ({assistantDisplayName(defaultAssistantId) || "use machine default"})</option>
            {#each assistantEntries as assistant (assistant.id)}
              <option value={assistant.id}>{assistant.title}</option>
            {/each}
          </select>
        </label>
      </div>
      {#if inputsDialogEstimate}
        <div class="chat-estimate-strip" title="Estimated input cost for this continuation. Output cost depends on the response.">
          <span class="chat-estimate-tokens">{formatTokens(inputsDialogEstimate.tokens)} tok</span>
          {#if inputsDialogEstimate.cost_usd != null}
            <span class="chat-estimate-sep">·</span>
            <span class="chat-estimate-cost">{formatCostEur(inputsDialogEstimate.cost_usd)}</span>
          {/if}
          {#if inputsDialogEstimate.caching_style === "explicit" && inputsDialogEstimate.cache_blocks.length > 1}
            <span class="chat-estimate-sep">·</span>
            {#each inputsDialogEstimate.cache_blocks as block, i}
              <span class="chat-estimate-chip">{block.label} {formatTokens(block.tokens)}</span>
              {#if i < inputsDialogEstimate.cache_blocks.length - 1}<span class="chat-estimate-sep">·</span>{/if}
            {/each}
          {/if}
        </div>
      {/if}
      <div class="inputs-dialog-actions">
        <button type="button" on:click={cancelInputsDialog}>Cancel</button>
        <button type="button" class="primary" on:click={submitInputsDialog}>Run</button>
      </div>
      <small class="inputs-dialog-hint">Ctrl/⌘+Enter to run · Esc to cancel</small>
    </div>
  </div>
{/if}
