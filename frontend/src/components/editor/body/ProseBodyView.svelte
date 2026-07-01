<!--
  ProseBodyView — body region for entry types with body_shape === "prose"
  (today: scenes and lore). Owns the TipTap editor, all custom extensions
  (AISuggestion / CharacterMark / TodoAnchor), the slash menu, selection
  toolbar, table toolbar, and embedded TODO mark reconciliation.

  The inline AI-suggestion pipeline (fire a prompt → stream deltas into the
  doc as a pending suggestion → accept/revert/retry) lives in its own
  AiSuggestionController (lib/editor-core/aiSuggestion.svelte.ts); this
  component instantiates one (`aiSuggestion`), injecting live editor / scene /
  prompt-context accessors plus the cost-prop sinks. The editor surfaces that
  drive it — slash AI commands, the selection-toolbar Revise list, and the
  Ctrl+J keymap — call `aiSuggestion.runPromptEntry(...)`. The inputs DIALOG
  (modal UI + draft state) stays in NodeEditor — the controller fires
  `onRequestInputsDialog` when it needs inputs, and NodeEditor calls back via
  `proseBodyView.runPromptEntryWithInputsExternal(...)` from submitInputsDialog.

  See decisions-node-editor-modularization for the architectural plan
  and outstanding-work-2026-06-25-phase-2 for the contract design.
-->
<script lang="ts">

  import { onMount } from "svelte";
  import { Editor } from "@tiptap/core";
  import { Fragment, type Node as ProseMirrorNode } from "@tiptap/pm/model";
  import { TextSelection } from "@tiptap/pm/state";
  import type { EditorView } from "@tiptap/pm/view";
  import StarterKit from "@tiptap/starter-kit";
  import Table from "@tiptap/extension-table";
  import TableCell from "@tiptap/extension-table-cell";
  import TableHeader from "@tiptap/extension-table-header";
  import TableRow from "@tiptap/extension-table-row";
  import { editorHtmlToSceneMarkdown, sceneMarkdownToHtml } from "@/lib/utils/markdown";
  import { sanitizePastedHtml } from "@/lib/utils/sanitizePastedHtml";
  import { ImplicitContextHighlight, REBUILD_META } from "@/lib/editor-core/implicitContextHighlight";
  import { AISuggestion, TodoAnchor, createCharacterMark, createMutationMark } from "@/lib/editor-core/proseMarks";
  import MutationAuthoringForm, { type MutationDraft } from "./MutationAuthoringForm.svelte";
  import {
    parseSlashBody,
    parseTableDims,
    tokenizeSlashArgs,
    matchesSlashFilter,
    filterSlashCommands,
  } from "@/lib/editor-core/slashParsing";
  import {
    TABLE_GRID_MAX_ROWS,
    TABLE_GRID_MAX_COLS,
    type SlashCommand,
    type SlashMenuState,
  } from "@/lib/editor-core/slashMenu";
  import {
    type FloatingMenuState,
    type ToolbarAction,
  } from "@/lib/editor-core/selectionToolbar";
  import ProseSlashMenu from "./ProseSlashMenu.svelte";
  import ProseSelectionToolbar from "./ProseSelectionToolbar.svelte";
  import ProseTableToolbar from "./ProseTableToolbar.svelte";
  import ProseAIToolbar from "./ProseAIToolbar.svelte";
  import { api } from "@/lib/api";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import {
    type PromptResolutionContext,
    promptEntriesForSurface,
    promptEntryDescription,
    defaultPromptForSurface,
    resolvePromptPositionalArgs,
  } from "@/lib/editor-core/promptResolution";
  import { AiSuggestionController } from "@/lib/editor-core/aiSuggestion.svelte";
  import { countWords } from "@/lib/utils/wordCount";
  import { resolveColor } from "@/lib/utils/colors";
  import type {
    DocumentKind,
    EditableDocument,
    LoreEntrySummary,
    PromptEntrySummary,
  } from "@/lib/types";

  // ---------- Local types ----------
  type BlockWrapType = "blockquote" | "bulletList" | "orderedList";

  

  // bound out so MetadataPanel's computedFieldString and the editor-hint
  
  // Per-scene continuation cost rollup. Bound out so the parent's header
  // chip can render it (the AI streaming machinery that produces these
  
  // Per-character cost rollup for THIS scene, summed from the persisted
  // ai_invocations log. Bound out so NodeEditor's footer can render the
  
  interface Props {
    // ---------- Props ----------
    scene?: EditableDocument | null;
    documentKind?: DocumentKind;
    promptEntries?: PromptEntrySummary[];
    loreEntries?: LoreEntrySummary[];
    availableScenes?: { id: string; title: string }[];
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    documentLabel?: string;
    // string in the parent can read them.
    liveWordCount?: number;
    editorEmpty?: boolean;
    // values lives here, but the chip lives in the shell header).
    lastInvocationCostUsd?: number | null;
    sceneSessionCostUsd?: number;
    // per-character mini-chips next to the session chip.
    characterCostUsd?: Record<string, number>;
    // Outbound events as callback props (#14: runes — replaces the dispatcher).
    // NodeEditor (the funnel) passes these.
    onBodyChange?: () => void;
    onFocus?: () => void;
    onOpenChat?: (payload: { entry: PromptEntrySummary; inputs: Record<string, unknown>; sceneId: string | null; assistantId: string }) => void;
    onRequestInputsDialog?: (payload: {
      entry: PromptEntrySummary;
      prefilledDrafts?: Record<string, string>;
      unresolved?: Array<{ name: string; label: string; token: string }>;
    }) => void;
  }

  let {
    scene = null,
    documentKind = "scene",
    promptEntries = [],
    loreEntries = [],
    availableScenes = [],
    implicitContextMatcher = null,
    documentLabel = "Scene",
    liveWordCount = $bindable(0),
    editorEmpty = $bindable(true),
    lastInvocationCostUsd = $bindable(null),
    sceneSessionCostUsd = $bindable(0),
    characterCostUsd = $bindable({}),
    onBodyChange,
    onFocus,
    onOpenChat,
    onRequestInputsDialog,
  }: Props = $props();

  // ---------- Custom TipTap extensions ----------
  // AISuggestion / TodoAnchor are imported verbatim. CharacterMark needs the
  // reactive lore/schema lookups below, so it's built from the factory.

  // Per-character mark color. Walks the full resolver: instance
  // (metadata.color on the lore entry) → entry-type color → parent
  // chain → kind-default. Only falls back to the deterministic hash
  // when the resolver returns null — so authors who set an explicit
  // color get it, but uncolored characters still get a stable hue.
  function characterColorFromId(id: string): string {
    const entry = loreEntries.find((e) => e.id === id);
    const instanceColor = typeof entry?.metadata?.color === "string" ? entry.metadata.color : null;
    const swatch = resolveColor(instanceColor, entry?.entry_type, "lore", metadataSchema);
    if (swatch) return swatch.hex;
    let hash = 0;
    for (let i = 0; i < id.length; i++) {
      hash = (hash * 31 + id.charCodeAt(i)) | 0;
    }
    const hue = ((hash % 360) + 360) % 360;
    return `hsl(${hue}, 62%, 48%)`;
  }

  function characterTitleFromId(id: string): string {
    const entry = loreEntries.find((e) => e.id === id);
    return entry?.title || "Unresolved character";
  }

  const CharacterMark = createCharacterMark({
    colorForId: characterColorFromId,
    titleForId: characterTitleFromId,
  });

  // Mutation pill label ("Honor · rank → Captain"), read live at render time
  // from the reactive lore lookup (mirrors CharacterMark's resolvers).
  function mutationLabelFromMarker(entityId: string, field: string, value: string): string {
    const entry = loreEntries.find((e) => e.id === entityId);
    const name = entry?.title || entityId || "entity";
    return `${name} · ${field} → ${value}`;
  }

  const MutationMark = createMutationMark({ labelForMarker: mutationLabelFromMarker });

  // ---------- State ----------
  let editorFrame = $state<HTMLDivElement>();
  let editorElement = $state<HTMLDivElement>();
  let editor: Editor | null = $state(null);
  let loadedSceneId: string | null = $state(null);
  let selectionMenu: FloatingMenuState = $state({ visible: false, x: 0, y: 0, wordCount: 0, placement: "above" });
  let slashMenu: SlashMenuState = $state({ visible: false, x: 0, y: 0, selectedIndex: 0, mode: "commands", gridRows: 1, gridCols: 1 });
  let tableMenu: { visible: boolean; x: number; y: number } = $state({ visible: false, x: 0, y: 0 });
  let openToolbarMenuId: string | null = $state(null);
  let reconcilingTodoAnchors = false;
  let highlightedTodoId: string | null = null;

  // V2: per-scene continuation cost rollup. Resets when you switch
  // scenes or reload the page. Frontend-only. Bound out as props above.
  let lastSeenSceneIdForCost: string | null = $state(null);

  // The inline AI-suggestion pipeline (fire prompt → stream into the doc →
  // accept/revert/retry). Owns its own AI `$state`; the host reads it for the
  // toolbar (`aiSuggestion.generating`/`.error`/...) and writes the bindable
  // cost props through the injected sinks. Getters are used (not one-time
  // values) because `scene`/`editor`/`promptCtx` change over the pane's life.
  const aiSuggestion = new AiSuggestionController({
    getEditor: () => editor,
    getEditorFrame: () => editorFrame,
    getScene: () => scene,
    getDocumentKind: () => documentKind,
    getPromptCtx: () => promptCtx,
    onInvocationCost: (cost) => {
      lastInvocationCostUsd = cost;
      sceneSessionCostUsd += cost;
    },
    addCharacterCost: (characterId, cost) => {
      characterCostUsd = {
        ...characterCostUsd,
        [characterId]: (characterCostUsd[characterId] ?? 0) + cost,
      };
    },
    onRequestInputsDialog: (payload) => onRequestInputsDialog?.(payload),
    onOpenChat: (payload) => onOpenChat?.(payload),
  });

  let slashFilterText = $state("");



  async function loadCharacterCostUsd(sceneId: string): Promise<void> {
    try {
      const result = await api.aiListInvocations({ scene_id: sceneId });
      // Race guard: scene may have changed during the fetch.
      if (scene?.id !== sceneId) return;
      const totals: Record<string, number> = {};
      for (const inv of result.invocations) {
        const characterId = inv.character_id;
        if (!characterId) continue;
        const cost = inv.cost_usd;
        if (typeof cost !== "number") continue;
        totals[characterId] = (totals[characterId] ?? 0) + cost;
      }
      characterCostUsd = totals;
    } catch (err) {
      console.warn("Failed to load per-character invocation cost:", err);
    }
  }

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


  // ---------- Public methods (called via bind:this from parent) ----------
  export function getBody(): string {
    if (!editor) return "";
    return editorHtmlToSceneMarkdown(editor.getHTML());
  }

  export async function loadScene(nextScene: EditableDocument): Promise<void> {
    const sceneId = nextScene.id;
    // Drop any pending AI suggestion state when changing documents.
    aiSuggestion.reset();
    const html = await sceneMarkdownToHtml(nextScene.body || "");
    if (!editor || scene?.id !== sceneId) return;
    editor.commands.setContent(html || "<p></p>", false);
    loadedSceneId = sceneId;
    enforceUniqueTodoAnchors();
    syncTodoAnchorDomState(true);
    updateLiveWordCount();
    syncEditorEmpty();
    updateSelectionMenu();
    updateTableMenu();
  }

  export function clearEditor(): void {
    editor?.commands.clearContent(false);
    loadedSceneId = null;
    liveWordCount = 0;
    syncEditorEmpty();
  }

  export function highlightEmbeddedTodo(todoId: string): void {
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

  // Called from NodeEditor.submitInputsDialog after the user fills inputs.
  export async function runPromptEntryWithInputsExternal(
    entry: PromptEntrySummary,
    inputs: Record<string, unknown>,
    assistantId: string = "",
  ): Promise<void> {
    await aiSuggestion.runPromptEntryWithInputs(entry, inputs, assistantId);
  }

  // ---------- Helpers ----------
  function clamp(value: number, min: number, max: number) {
    return Math.min(Math.max(value, min), max);
  }

  function updateLiveWordCount() {
    if (!editor) {
      liveWordCount = 0;
      return;
    }
    liveWordCount = countWords(editor.state.doc.textBetween(0, editor.state.doc.content.size, " "));
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

  // ---------- Slash menu ----------
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

  function openSlashMenu() {
    if (documentKind !== "scene") return;
    if (!editor || !editorFrame || !editor.isFocused) return;
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
      {
        group: "Insert",
        label: "Mutate lore",
        description: "Record a mid-scene change to a lore field (rank, title, …).",
        autocompleteTo: "mutate",
        run: () => {
          clearSlashTrigger();
          openMutationDialog();
        },
      },
      ...promptEntriesForSurface(promptCtx, "append_to_body")
        .map((entry) => ({
          group: "AI",
          label: entry.title,
          description: promptEntryDescription(promptCtx, entry),
          autocompleteTo: entry.entry_type,
          run: (args?: string[]) => {
            clearSlashTrigger();
            const resolved = args && args.length > 0
              ? resolvePromptPositionalArgs(promptCtx, entry, args)
              : {
                  inputs: undefined as Record<string, unknown> | undefined,
                  satisfied: false,
                  unresolved: [] as Array<{ name: string; label: string; token: string }>,
                };
            if (resolved.inputs && resolved.satisfied) {
              void aiSuggestion.runPromptEntry(entry, resolved.inputs);
            } else if (resolved.inputs) {
              // Partial: ask the parent to open the dialog with the resolved
              // drafts populated; unresolved tokens get cleared on the parent
              // side so the user sees no stale values.
              const prefilled: Record<string, string> = {};
              for (const [name, value] of Object.entries(resolved.inputs)) {
                prefilled[name] = String(value);
              }
              for (const { name } of resolved.unresolved) {
                prefilled[name] = "";
              }
              onRequestInputsDialog?.({
                entry,
                prefilledDrafts: prefilled,
                unresolved: resolved.unresolved,
              });
            } else {
              void aiSuggestion.runPromptEntry(entry);
            }
          },
        })),
    ];
  }

  // ---------- Table toolbar ----------
  function setCellAlign(align: "left" | "center" | "right") {
    if (!editor) return;
    const { state, view } = editor;
    const { $from: fromR } = state.selection;
    let tablePos = -1;
    let tableNode: ProseMirrorNode | null = null;
    let tableDepth = -1;
    for (let d = fromR.depth; d >= 0; d--) {
      const node = fromR.node(d);
      if (node.type.name === "table") {
        tablePos = fromR.before(d);
        tableNode = node;
        tableDepth = d;
        break;
      }
    }
    if (!tableNode || tablePos < 0 || fromR.depth < tableDepth + 2) {
      editor.chain().focus().setCellAttribute("align", align).run();
      return;
    }
    const cellIndex = fromR.index(tableDepth + 1);
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

  // ---------- Selection toolbar ----------
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

  async function focusAndRun(command: () => void | Promise<void>) {
    try {
      await command();
    } catch {
      // Parent action surfaces failures through app-level error state.
    } finally {
      openToolbarMenuId = null;
      updateSelectionMenu();
    }
  }

  function toggleToolbarMenu(actionId: string) {
    openToolbarMenuId = openToolbarMenuId === actionId ? null : actionId;
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
    const { $from: fromR, $to: toR, from, to } = selection;
    const parent = fromR.parent;
    const paragraphType = state.schema.nodes.paragraph;

    if (
      selection.empty ||
      !paragraphType ||
      !fromR.sameParent(toR) ||
      fromR.depth !== 1 ||
      !parent.isTextblock
    ) {
      return false;
    }

    const parentStart = fromR.start();
    const parentEnd = fromR.end();
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
    ].filter((n): n is NonNullable<typeof n> => n !== null);

    const transaction = state.tr.replaceWith(fromR.before(), fromR.after(), replacementNodes);
    view.dispatch(transaction.scrollIntoView());
    view.focus();
    return true;
  }

  function createParagraphNode(content: Fragment) {
    if (!editor || content.size === 0) return null;
    return editor.state.schema.nodes.paragraph.create(null, content);
  }

  function getSelectionToolbarActions(): ToolbarAction[] {
    if (!editor) return [];
    const reviseEntries = promptEntriesForSurface(promptCtx, "replace_selection");
    const reviseAction: ToolbarAction | null =
      reviseEntries.length === 0
        ? null
        : reviseEntries.length === 1
          ? {
              kind: "button",
              id: `ai-revise:${reviseEntries[0].id}`,
              label: `✨ ${reviseEntries[0].title}`,
              run: () => focusAndRun(() => aiSuggestion.runPromptEntry(reviseEntries[0])),
            }
          : {
              kind: "menu",
              id: "ai-revise",
              label: "✨ Revise",
              items: reviseEntries.map((entry) => ({
                id: `ai-revise:${entry.id}`,
                label: entry.title,
                run: () => focusAndRun(() => aiSuggestion.runPromptEntry(entry)),
              })),
            };
    return [
      {
        kind: "button",
        id: "bold",
        label: "B",
        run: () => void editor?.chain().focus().toggleBold().run(),
      },
      {
        kind: "button",
        id: "italic",
        label: "I",
        run: () => void editor?.chain().focus().toggleItalic().run(),
      },
      {
        kind: "button",
        id: "strike",
        label: "S",
        run: () => void editor?.chain().focus().toggleStrike().run(),
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

  // ---------- TODO anchors ----------
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

  function createMutationId() {
    const randomId = globalThis.crypto?.randomUUID?.().replace(/-/g, "") ?? Math.random().toString(16).slice(2);
    return `mut_${randomId.slice(0, 12)}`;
  }

  // `/mutate` authoring dialog (#33). Opened from the slash menu; inserts one
  // mutation pill (client-minted id) per selected field at the cursor. The
  // marker round-trips to a scene-body comment via the turndown rule on save.
  let mutationDialogOpen = $state(false);

  function openMutationDialog() {
    mutationDialogOpen = true;
  }

  function insertMutations(drafts: MutationDraft[]) {
    mutationDialogOpen = false;
    if (!editor || drafts.length === 0) return;
    const chain = editor.chain().focus();
    for (const draft of drafts) {
      chain.insertContent({
        type: "mutation",
        attrs: {
          entity: draft.entity,
          field: draft.field,
          value: draft.value,
          markerId: createMutationId(),
        },
      });
    }
    chain.run();
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

  function syncTodoAnchorDomState(_force = false) {
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


  // ---------- Editor lifecycle ----------
  function isEmptyTextblock(view: EditorView) {
    const { selection } = view.state;
    return selection.empty && selection.$from.parent.type.name === "paragraph" && selection.$from.parent.textContent.length === 0;
  }

  function handleEditorKeydown(view: EditorView, event: KeyboardEvent) {
    if (documentKind !== "scene") {
      if (slashMenu.visible) closeSlashMenu();
      return false;
    }

    if (event.key.toLowerCase() === "j" && (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey) {
      event.preventDefault();
      const entry = defaultPromptForSurface(promptCtx, "append_to_body");
      if (entry) void aiSuggestion.runPromptEntry(entry);
      return true;
    }
    if (event.key.toLowerCase() === "j" && (event.ctrlKey || event.metaKey) && !event.altKey && event.shiftKey) {
      event.preventDefault();
      const entry = defaultPromptForSurface(promptCtx, "replace_selection");
      if (entry) void aiSuggestion.runPromptEntry(entry);
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

  // Body-change orchestration: TipTap's onUpdate fires per keystroke. We
  // emit one `body-change` event to the parent (NodeEditor) so it can
  // compose its full save payload (title + body + status + ...).
  function handleEditorUpdate() {
    if (!enforceUniqueTodoAnchors()) {
      // Skip the body-change emit when the unique-anchor reconciler made a doc
      // change — its own transaction re-fires onUpdate, so the non-reconciler
      // edits below run on that second pass.
      syncEditorEmpty();
      updateSelectionMenu();
      updateTableMenu();
      updateSlashMenuFromContent();
      syncTodoAnchorDomState(true);
      updateLiveWordCount();
      onBodyChange?.();
    }
    if (aiSuggestion.suggestionId) aiSuggestion.updateToolbarPosition();
    refreshSlashFilterText();
  }

  function handleEditorSelectionUpdate() {
    updateSelectionMenu();
    updateTableMenu();
    if (aiSuggestion.suggestionId) aiSuggestion.updateToolbarPosition();
    refreshSlashFilterText();
  }

  function handleEditorBlur() {
    hideSelectionMenu();
    tableMenu = { ...tableMenu, visible: false };
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
        MutationMark,
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
            onFocus?.();
            return false;
          },
        },
        // External clipboard HTML ships inline styles + classes that can't
        // round-trip through our Markdown serializer. Strip at paste time.
        transformPastedHTML: (html) => sanitizePastedHtml(html),
      },
      onUpdate: handleEditorUpdate,
      onSelectionUpdate: handleEditorSelectionUpdate,
      onBlur: handleEditorBlur,
    });

    if (scene) {
      void loadScene(scene);
    }

    return () => editor?.destroy();
  });

  // Surface the cost rollup to the editor-hint chip via documentLabel
  // wrap-around — actually the chip lives in the parent's header. We
  // bind it via slot down the line; for now it stays in the parent and
  // reads scene-session totals through these props.
  // (No-op: the chip is rendered in NodeEditor's header, not here.)
  $effect.pre(() => {
    void documentLabel;
  });
  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  let metadataSchema = $derived($metadataSchemaStore);
  // Snapshot consumed by the pure prompt-resolution helpers (slash menu,
  // selection toolbar, and the AI pipeline all read it).
  let promptCtx = $derived<PromptResolutionContext>({
    metadataSchema,
    promptEntries,
    loreEntries,
    availableScenes,
  });
  // ---------- Reactives ----------
  let slashCommands = $derived(editor && documentKind === "scene" ? getSlashCommands() : []);
  let parsedSlash = $derived(parseSlashBody(slashFilterText) ?? { command: slashFilterText, args: "" });
  let slashArgTokens = $derived(tokenizeSlashArgs(parsedSlash.args));
  let filteredSlashCommands = $derived(filterSlashCommands(slashCommands, parsedSlash.command, parsedSlash.args.length > 0));
  let activeSlashCommand = $derived(filteredSlashCommands[slashMenu.selectedIndex]);
  $effect.pre(() => {
    clampSlashSelectedIndex(filteredSlashCommands.length);
  });
  let selectionToolbarActions = $derived(editor ? getSelectionToolbarActions() : []);
  // Reset the per-scene cost tally when the active scene changes. Reading
  // scene?.id directly so Svelte tracks the dependency
  // ([[feedback-svelte5-reactivity-traps]] — function calls in `$:` don't).
  $effect.pre(() => {
    const currentSceneId = scene?.id ?? null;
    if (lastSeenSceneIdForCost !== currentSceneId) {
      lastSeenSceneIdForCost = currentSceneId;
      sceneSessionCostUsd = 0;
      lastInvocationCostUsd = null;
      characterCostUsd = {};
      if (currentSceneId) {
        void loadCharacterCostUsd(currentSceneId);
      }
    }
  });
  // Reactively poke the ImplicitContextHighlight extension when the
  // matcher reference changes (lore added/edited at the App level).
  $effect.pre(() => {
    if (editor) updateImplicitMatcher(implicitContextMatcher);
  });
  // Suppress unused-warning for slashArgTokens (reserved for future slash UX).
  $effect.pre(() => {
    void slashArgTokens;
  });
  // ---------- Scene loading reactive ----------
  // Loads the scene's body into the editor when:
  //   - the editor is mounted AND
  //   - the scene's id differs from the currently-loaded one
  // Discriminating by id (not reference) preserves in-flight user edits
  // across save→reload cycles where the parent passes a fresh scene
  // object with the same id but a bumped revision.
  $effect.pre(() => {
    if (editor && scene && scene.id !== loadedSceneId) {
      void loadScene(scene);
    }
  });
  $effect.pre(() => {
    if (!scene && loadedSceneId !== null) {
      clearEditor();
    }
  });
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class:empty-editor={editorEmpty}
  class:lore-editor={documentKind === "lore"}
  class="editor-wrap"
  bind:this={editorFrame}
  onmousedown={(event) => {
    // Click landed on the wrap itself (the gutter around the centered
    // 780px column or below short content) — focus the editor at the
    // end of the doc so the cursor lands where the user expects.
    if (event.target === event.currentTarget) {
      event.preventDefault();
      editor?.chain().focus("end").run();
    }
  }}
>
  <ProseAIToolbar
    position={aiSuggestion.toolbarPosition}
    generating={aiSuggestion.generating}
    suggestionId={aiSuggestion.suggestionId}
    error={aiSuggestion.error}
    meta={aiSuggestion.meta}
    onAccept={() => aiSuggestion.accept()}
    onRetry={() => aiSuggestion.retry()}
    onDiscard={() => aiSuggestion.revert()}
    onDismissError={() => aiSuggestion.dismissError()}
  />
  <ProseSelectionToolbar
    menu={selectionMenu}
    actions={selectionToolbarActions}
    openMenuId={openToolbarMenuId}
    onRun={focusAndRun}
    onToggleMenu={toggleToolbarMenu}
  />

  <ProseSlashMenu
    menu={slashMenu}
    filterText={slashFilterText}
    commands={filteredSlashCommands}
    onRunCommand={runSlashCommand}
    onInsertTable={insertTableFromGrid}
    onHoverCommand={(index) => (slashMenu = { ...slashMenu, selectedIndex: index })}
    onHoverGrid={(rows, cols) => (slashMenu = { ...slashMenu, gridRows: rows, gridCols: cols })}
  />

  <ProseTableToolbar menu={tableMenu} {editor} onAlign={setCellAlign} />

  <div bind:this={editorElement}></div>
</div>

{#if mutationDialogOpen}
  <MutationAuthoringForm
    {loreEntries}
    schema={metadataSchema}
    onSubmit={insertMutations}
    onCancel={() => (mutationDialogOpen = false)}
  />
{/if}
