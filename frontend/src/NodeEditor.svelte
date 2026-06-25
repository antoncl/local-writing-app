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
  import BacklinksPanel from "./BacklinksPanel.svelte";
  import MetadataPanel from "./MetadataPanel.svelte";
  import InputsDialog from "./InputsDialog.svelte";
  import FieldsOnlyView from "./FieldsOnlyView.svelte";
  import CodeBodyView from "./CodeBodyView.svelte";
  import { coerceInputValue, type EntryInputDraft } from "./promptInputs";
  import { resolveColor } from "./colors";
  import { api, HttpError } from "./api";
  import { formatCostEur, formatTokens } from "./money";
  import PromptInputField from "./PromptInputField.svelte";
  import type { AIPreviewResponse, AssistantEntrySummary, Backlink, BodyShape, ChatUsage, EditableDocument, EntryBodyLanguage, EntryMetadata, EntryTypeDefinition, MetadataFieldDefinition, MetadataSchema, MetadataValue, PromptEntrySummary, PromptInputDefinition } from "./types";

  // Effective body shape for an entry type. Falls back through the
  // legacy has_body / body_editor pair when body_shape is absent
  // (existing on-disk schemas don't carry it). See
  // decisions-node-editor-modularization + decisions-node-editor-body-spec.
  export function deriveBodyShape(def: EntryTypeDefinition | null | undefined): BodyShape {
    if (def?.body_shape) return def.body_shape;
    if (def?.has_body === false) return "none";
    if (def?.body_editor === "code") return "code";
    return "prose";
  }

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
  $: bodyShape = deriveBodyShape(entryTypeDef);
  $: rawBodyMode = bodyShape === "code";
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
  let backlinks: Backlink[] = [];
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

  // --- Per-entry prompt inputs (declaration side) ---
  // Inputs live on the entry now, not the entry-type. The drafts here are
  // the editor-side form state; on every edit we rebuild the canonical
  // PromptInputDefinition[] and emit it as part of the change event.
  // App.svelte stores it on the pane and persists on save. The actual
  // editor UI lives in CodeBodyView; this file owns the drafts state +
  // reseed-on-scene-change + canonical serialization for save.
  let entryInputDrafts: EntryInputDraft[] = [];
  let entryInputDraftCounter = 0;
  function nextInputDraftId(): string {
    entryInputDraftCounter += 1;
    return `__input_${entryInputDraftCounter}`;
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
  $: metadataFieldIds = ((metadataSchema?.entry_types[entryType] ?? metadataSchema?.entry_types[defaultEntryType()])?.fields ?? []).filter((fieldId) => fieldId !== "color");
  $: hasBody = bodyShape !== "none";
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
    // Branch on the FRESHLY-resolved entry-type's body shape — the `rawBodyMode`
    // reactive hasn't recomputed yet (Svelte updates on the next microtask), so
    // reading it here would reflect the PREVIOUS entry. For a prompt opened
    // after a scene that meant we fell through to the WYSIWYG branch and lost
    // the Jinja2 source view.
    const nextRawBodyMode = deriveBodyShape(nextEntryDefinition) === "code";
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

<div class="editor-panel" class:body-hidden={bodyShape === "none"}>
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
        <MetadataPanel
          metadataSchema={metadataSchema}
          entryType={entryType}
          status={status}
          metadata={metadata}
          documentKind={documentKind}
          documentLabel={documentLabel}
          documentEntryTypes={documentEntryTypes}
          metadataFieldIds={metadataFieldIds}
          metadataSummaryText={metadataSummaryText}
          expanded={metadataExpanded}
          knownTags={knownTags}
          loreEntries={loreEntries}
          promptEntries={promptEntries}
          structure={structure}
          implicitContextMatcher={implicitContextMatcher}
          excludeId={scene?.id ?? null}
          computedFieldString={computedFieldString}
          on:entryTypeChange={(event) => updateEntryType(event.detail.entryType)}
          on:statusChange={(event) => updateStatus(event.detail.status)}
          on:metadataChange={(event) => {
            metadata = event.detail.metadata;
            emitChange();
          }}
          on:customData={() => dispatch("custom-data", { entryType, kind: documentKind })}
          on:navigate={(event) => dispatch("navigate", event.detail)}
          on:toggleExpanded={() => (metadataExpanded = !metadataExpanded)}
        />
        {#key scene?.id ?? ""}
          <BacklinksPanel
            backlinks={backlinks}
            metadataSchema={metadataSchema}
            loreEntries={loreEntries}
            structure={structure}
            on:navigate={(event) => dispatch("navigate", event.detail)}
          />
        {/key}
      {/if}
    {:else}
      <h2>Select a scene</h2>
    {/if}
  </section>

  {#if bodyShape === "none"}
    <FieldsOnlyView />
  {/if}
  {#if bodyShape === "code"}
    <CodeBodyView
      bind:rawBody
      bind:entryInputDrafts
      {scene}
      {documentKind}
      {metadataSchema}
      {structure}
      {loreEntries}
      {promptEntries}
      {availableScenes}
      {rawBodyLanguage}
      {loadedSceneId}
      {nextInputDraftId}
      {entrySlugify}
      on:inputsChange={emitInputsChange}
    />
  {/if}
  <!-- Prose body wrap stays mounted in EVERY body shape so the TipTap
       instance keeps its DOM anchor across body-shape switches (onMount
       runs once per pane lifetime; tearing down + recreating ProseMirror
       on every switch is fragile). CSS hides it when the active shape is
       not "prose". 2d ProseBodyView will properly extract this. -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class:empty-editor={editorEmpty}
    class:lore-editor={documentKind === "lore"}
    class:body-region-hidden={bodyShape !== "prose"}
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

    <div bind:this={editorElement}></div>

  </div>

  <footer class="status">
    {#if scene}
      {dirty ? "Unsaved changes" : `Loaded ${scene.title}`}
    {:else}
      No scene open
    {/if}
  </footer>
</div>

{#if inputsDialogEntry}
  <InputsDialog
    entry={inputsDialogEntry}
    description={promptEntryDescription(inputsDialogEntry)}
    declaredInputs={effectivePromptInputs(inputsDialogEntry)}
    drafts={inputsDialogDrafts}
    assistantId={inputsDialogAssistantId}
    defaultAssistantLabel={assistantDisplayName(defaultAssistantId) || "use machine default"}
    assistantEntries={assistantEntries}
    error={inputsDialogError}
    estimate={inputsDialogEstimate}
    metadataSchema={metadataSchema}
    structure={structure}
    loreEntries={loreEntries}
    promptEntries={promptEntries}
    excludeId={scene?.id ?? null}
    implicitContextMatcher={implicitContextMatcher}
    on:updateDraft={(event) => updateInputsDialogDraft(event.detail.name, event.detail.value)}
    on:updateAssistant={(event) => (inputsDialogAssistantId = event.detail.assistantId)}
    on:cancel={cancelInputsDialog}
    on:submit={() => void submitInputsDialog()}
  />
{/if}
