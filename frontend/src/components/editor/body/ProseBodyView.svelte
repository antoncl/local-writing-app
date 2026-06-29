<script lang="ts" module>
  // Re-exported by NodeEditor / App.svelte for the embedded-todos dispatch
  // shape. Lives in <script module> because Svelte 5 disallows type exports
  // from instance scripts.
  export type EmbeddedTodo = {
    id: string;
    text: string;
    status: "open" | "done";
    note: string;
  };
</script>

<!--
  ProseBodyView — body region for entry types with body_shape === "prose"
  (today: scenes and lore). Owns the TipTap editor, all custom extensions
  (AISuggestion / CharacterMark / TodoAnchor), the slash menu, selection
  toolbar, table toolbar, AI inline suggestion flow, embedded TODO mark
  reconciliation, and the inline prompt invocation pipeline (the half
  that fires from the editor — selection-toolbar Revise, slash AI
  commands, and the AI suggestion Retry button).

  Why prompt invocation lives here: runPromptEntry → runPromptEntryWithInputs
  streams AI deltas into the editor doc, mutates the TipTap state with
  the AISuggestion mark, and tracks the in-flight suggestion. Keeping
  the orchestrator next to the target is simpler than threading event /
  method plumbing for every keystroke of streaming. The inputs DIALOG
  (modal UI + draft state) stays in NodeEditor — ProseBodyView dispatches
  `request-inputs-dialog` when it needs the user to fill inputs, and
  NodeEditor calls back via `proseBodyView.runPromptEntryWithInputs(...)`
  from submitInputsDialog.

  See decisions-node-editor-modularization for the architectural plan
  and outstanding-work-2026-06-25-phase-2 for the contract design.
-->
<script lang="ts">
  import { preventDefault } from 'svelte/legacy';

  import { onMount } from "svelte";
  import { Editor, Mark, mergeAttributes } from "@tiptap/core";
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
  import { api } from "@/lib/api";
  import { metadataSchemaStore } from "@/lib/stores/schema";
  import { formatCostEur } from "@/lib/utils/money";
  import { coerceInputValue } from "@/lib/utils/promptInputs";
  import { resolveColor } from "@/lib/utils/colors";
  import type {
    ChatUsage,
    DocumentKind,
    EditableDocument,
    LoreEntrySummary,
    MetadataSchema,
    PromptEntrySummary,
    PromptInputDefinition,
  } from "@/lib/types";

  // ---------- Local types ----------
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
    autocompleteTo?: string;
    run: (args?: string[]) => void | Promise<void>;
  };
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

  // ---------- Constants ----------
  const TABLE_GRID_MAX_ROWS = 8;
  const TABLE_GRID_MAX_COLS = 8;
  const REVISE_CONTEXT_CHARS = 600;
  const WORD_PATTERN = /[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?/g;
  const SLASH_COMMAND_PATTERN = /^[a-zA-Z0-9_-]*$/;
  const SLASH_WITH_ARGS_PATTERN = /^([a-zA-Z0-9_-]+)\s+(.*)$/;

  

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
    onEmbeddedTodos?: (payload: { todos: EmbeddedTodo[] }) => void;
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
    onEmbeddedTodos,
    onOpenChat,
    onRequestInputsDialog,
  }: Props = $props();

  // ---------- Custom TipTap extensions ----------
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
              title: characterTitleFromId(id),
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

  // AI suggestion state. v1 supports a single pending suggestion at a time.
  let aiGenerating = $state(false);
  let aiError: string | null = $state(null);
  let aiSuggestionId: string | null = $state(null);
  let aiSuggestionMeta: {
    provider: string;
    model: string;
    latency_ms: number;
    truncated: boolean;
    wordCount: number;
    usage?: ChatUsage | null;
    cost_usd?: number | null;
  } | null = $state(null);
  // V2: per-scene continuation cost rollup. Resets when you switch
  // scenes or reload the page. Frontend-only. Bound out as props above.
  let lastSeenSceneIdForCost: string | null = $state(null);
  let aiToolbarPosition: { x: number; y: number; visible: boolean } = $state({ x: 0, y: 0, visible: false });
  let aiNextSuggestionId = 1;
  let aiSuggestionOriginal: string | null = null;
  let aiAnchorPos: number | null = null;
  let lastInvokedEntryId: string | null = null;
  let lastInvokedInputs: Record<string, unknown> = {};
  let lastInvokedAssistantId: string = "";

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
    aiSuggestionId = null;
    aiSuggestionMeta = null;
    aiSuggestionOriginal = null;
    aiAnchorPos = null;
    aiError = null;
    aiToolbarPosition = { x: 0, y: 0, visible: false };
    const html = await sceneMarkdownToHtml(nextScene.body || "");
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

  export function clearEditor(): void {
    editor?.commands.clearContent(false);
    loadedSceneId = null;
    liveWordCount = 0;
    syncEditorEmpty();
  }

  export function updateEmbeddedTodo(todoId: string, updates: { status?: "open" | "done"; note?: string }): void {
    if (!editor) return;
    updateTodoMark(todoId, updates);
  }

  export function deleteEmbeddedTodo(todoId: string): void {
    if (removeTodoAnchors((anchorId) => anchorId === todoId)) {
      onBodyChange?.();
    }
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
    await runPromptEntryWithInputs(entry, inputs, assistantId);
  }

  // ---------- Helpers ----------
  function countWords(text: string) {
    return Array.from(text.matchAll(WORD_PATTERN)).length;
  }

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
    return entry.inputs ?? [];
  }

  function findPromptEntry(entryId: string | null): PromptEntrySummary | null {
    if (!entryId) return null;
    return promptEntries.find((entry) => entry.id === entryId) ?? null;
  }

  function defaultPromptForSurface(surface: "append_to_body" | "replace_selection"): PromptEntrySummary | null {
    return promptEntriesForSurface(surface)[0] ?? null;
  }

  // Resolve a positional-string token against a context_pick input.
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
    return {
      inputs,
      satisfied: !missingRequired && unresolved.length === 0,
      unresolved,
    };
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

  // Pull the first lore id from a context_pick input value.
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

  // ---------- Slash menu ----------
  function parseSlashBody(text: string): { command: string; args: string } | null {
    if (SLASH_COMMAND_PATTERN.test(text)) return { command: text, args: "" };
    const m = text.match(SLASH_WITH_ARGS_PATTERN);
    if (m) return { command: m[1], args: m[2] };
    return null;
  }

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

  function matchesSlashFilter(haystack: string, needle: string): boolean {
    const lower = needle.toLowerCase();
    return haystack.toLowerCase().split(/\s+/).some((word) => word.startsWith(lower));
  }

  function filterSlashCommands(commands: SlashCommand[], command: string, argsPresent: boolean): SlashCommand[] {
    if (!command) return commands;
    const lower = command.toLowerCase();
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
      ...promptEntriesForSurface("append_to_body")
        .map((entry) => ({
          group: "AI",
          label: entry.title,
          description: promptEntryDescription(entry),
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
              void runPromptEntry(entry);
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

  // ---------- AI inline suggestion ----------
  function updateAIToolbarPosition() {
    if (!editor || !editorFrame) {
      if (aiToolbarPosition.visible) aiToolbarPosition = { x: 0, y: 0, visible: false };
      return;
    }
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

  function acceptAISuggestion() {
    if (!editor || !aiSuggestionId) return;
    const range = findAISuggestionRange(aiSuggestionId);
    const lastEntry = findPromptEntry(lastInvokedEntryId);
    const characterId =
      range && isRoleplayPromptEntry(lastEntry)
        ? characterIdFromInputValue(lastInvokedInputs.character)
        : null;
    if (range) {
      let chain = editor.chain().focus().setTextSelection(range).unsetMark("aiSuggestion");
      if (characterId) {
        chain = chain.setMark("character", { characterId });
      }
      chain.setTextSelection(range.to).run();
    }
    persistAcceptedInvocation(lastEntry, characterId);
    aiSuggestionId = null;
    aiSuggestionMeta = null;
    aiSuggestionOriginal = null;
    aiAnchorPos = null;
    aiError = null;
    aiToolbarPosition = { x: 0, y: 0, visible: false };
  }

  function persistAcceptedInvocation(
    entry: PromptEntrySummary | null,
    characterId: string | null,
  ) {
    // Telemetry write — the `cost` computed field on the scene and the
    // per-character cost row in the footer both project from this log.
    // Fire-and-forget; a failed POST shouldn't block accept.
    if (!scene || !aiSuggestionMeta) return;
    const meta = aiSuggestionMeta;
    const cost = meta.cost_usd;
    if (characterId && typeof cost === "number") {
      // Optimistic per-character rollup. The next scene-load reconciles
      // against the backend; for this session we trust the local write.
      characterCostUsd = {
        ...characterCostUsd,
        [characterId]: (characterCostUsd[characterId] ?? 0) + cost,
      };
    }
    api
      .aiAppendInvocation({
        prompt_entry_id: entry?.id ?? lastInvokedEntryId ?? "",
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

  function revertAISuggestion() {
    if (!editor || !aiSuggestionId) return;
    const range = findAISuggestionRange(aiSuggestionId);
    if (range) {
      if (aiSuggestionOriginal !== null) {
        editor
          .chain()
          .focus()
          .setTextSelection(range)
          .deleteSelection()
          .insertContent(aiSuggestionOriginal)
          .run();
      } else {
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
      const restoredTo = range.from + original.length;
      editor.chain().focus().setTextSelection({ from: range.from, to: restoredTo }).run();
    }
    await runPromptEntry(entry, lastInvokedInputs, lastInvokedAssistantId);
  }

  // ---------- Prompt invocation pipeline ----------
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
      onRequestInputsDialog?.({ entry });
      return;
    }
    await runPromptEntryWithInputs(entry, prefilledInputs ?? {}, assistantId);
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
      onOpenChat?.({ entry, inputs, sceneId: scene.id, assistantId });
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
        template_source: entry.body,
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

  function dispatchEmbeddedTodos() {
    onEmbeddedTodos?.({ todos: collectEmbeddedTodos() });
  }

  function collectEmbeddedTodos(): EmbeddedTodo[] {
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
      onBodyChange?.();
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
      const entry = defaultPromptForSurface("append_to_body");
      if (entry) void runPromptEntry(entry);
      return true;
    }
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
      // Skip the body-change emit if the reconciler made a doc change —
      // it queues its own emit via the dispatch in deleteEmbeddedTodo /
      // updateTodoMark flows. The non-reconciler edits below need it.
      syncEditorEmpty();
      updateSelectionMenu();
      updateTableMenu();
      updateSlashMenuFromContent();
      syncTodoAnchorDomState(true);
      updateLiveWordCount();
      dispatchEmbeddedTodos();
      onBodyChange?.();
    }
    if (aiSuggestionId) updateAIToolbarPosition();
    refreshSlashFilterText();
  }

  function handleEditorSelectionUpdate() {
    updateSelectionMenu();
    updateTableMenu();
    if (aiSuggestionId) updateAIToolbarPosition();
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
        <button type="button" class="ai-toolbar-btn" onmousedown={preventDefault(dismissAIError)} title="Dismiss">
          <span aria-hidden="true">✕</span> Dismiss
        </button>
      {:else if aiSuggestionId}
        <button type="button" class="ai-toolbar-btn ai-toolbar-accept" onmousedown={preventDefault(acceptAISuggestion)} title="Accept (keep the text)">
          <span aria-hidden="true">✓</span> Accept
        </button>
        <button type="button" class="ai-toolbar-btn" onmousedown={preventDefault(retryAISuggestion)} title="Retry (regenerate)" disabled={aiGenerating}>
          <span aria-hidden="true">↻</span> Retry
        </button>
        <button type="button" class="ai-toolbar-btn ai-toolbar-discard" onmousedown={preventDefault(revertAISuggestion)} title="Discard (delete the text)">
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
          <button type="button" onmousedown={preventDefault(() => focusAndRun(action.run))}>{action.label}</button>
        {:else}
          <div class="toolbar-menu">
            <button
              class:open={openToolbarMenuId === action.id}
              type="button"
              onmousedown={preventDefault(() => toggleToolbarMenu(action.id))}
            >
              {action.label}
            </button>
            {#if openToolbarMenuId === action.id}
              <div class:below={selectionMenu.placement === "below"} class="toolbar-menu-popover">
                {#each action.items as item}
                  <button type="button" onmousedown={preventDefault(() => focusAndRun(item.run))}>{item.label}</button>
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
                  onmouseenter={() => (slashMenu = { ...slashMenu, gridRows: rowIndex + 1, gridCols: colIndex + 1 })}
                  onmousedown={preventDefault(() => insertTableFromGrid(rowIndex + 1, colIndex + 1))}
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
            onmouseenter={() => (slashMenu = { ...slashMenu, selectedIndex: index })}
            onmousedown={preventDefault(() => runSlashCommand(command))}
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
      <button type="button" title="Insert column before" onmousedown={preventDefault(() => editor?.chain().focus().addColumnBefore().run())}>+ col ←</button>
      <button type="button" title="Insert column after" onmousedown={preventDefault(() => editor?.chain().focus().addColumnAfter().run())}>+ col →</button>
      <button type="button" title="Delete column" onmousedown={preventDefault(() => editor?.chain().focus().deleteColumn().run())}>− col</button>
      <span class="table-toolbar-sep" aria-hidden="true"></span>
      <button type="button" title="Insert row above" onmousedown={preventDefault(() => editor?.chain().focus().addRowBefore().run())}>+ row ↑</button>
      <button type="button" title="Insert row below" onmousedown={preventDefault(() => editor?.chain().focus().addRowAfter().run())}>+ row ↓</button>
      <button type="button" title="Delete row" onmousedown={preventDefault(() => editor?.chain().focus().deleteRow().run())}>− row</button>
      <span class="table-toolbar-sep" aria-hidden="true"></span>
      <button type="button" title="Align left" onmousedown={preventDefault(() => setCellAlign("left"))}>⟵</button>
      <button type="button" title="Align center" onmousedown={preventDefault(() => setCellAlign("center"))}>↔</button>
      <button type="button" title="Align right" onmousedown={preventDefault(() => setCellAlign("right"))}>⟶</button>
      <span class="table-toolbar-sep" aria-hidden="true"></span>
      <button type="button" title="Toggle header row" onmousedown={preventDefault(() => editor?.chain().focus().toggleHeaderRow().run())}>Hdr row</button>
      <button type="button" title="Toggle header column" onmousedown={preventDefault(() => editor?.chain().focus().toggleHeaderColumn().run())}>Hdr col</button>
      <span class="table-toolbar-sep" aria-hidden="true"></span>
      <button type="button" title="Delete table" onmousedown={preventDefault(() => editor?.chain().focus().deleteTable().run())}>Delete</button>
    </div>
  {/if}

  <div bind:this={editorElement}></div>
</div>

<style>
  /* ProseBodyView's own editor-overlay UI (selection toolbar, slash menu,
     table toolbar/grid, AI inline toolbar), co-located from styles.css (#14).
     All real Svelte-template DOM → scoped, no :global. The editor CONTENT
     styling (.editor-body prose/table, .ai-suggestion / .character-mark /
     .todo-anchor marks) stays global — .editor-body is shared across four
     editor components. */
  .selection-toolbar {
    position: fixed;
    z-index: 20;
    display: flex;
    align-items: center;
    max-width: min(720px, calc(100% - 24px));
    overflow: visible;
    border: 1px solid var(--toolbar-border);
    border-radius: 7px;
    background: var(--toolbar-surface);
    box-shadow: 0 14px 28px rgba(25, 40, 35, 0.22);
    transform: translate(-50%, calc(-100% - 8px));
  }

  .selection-toolbar.below {
    transform: translate(-50%, 0);
  }

  .selection-toolbar button,
  .selection-count {
    height: 34px;
    border: 0;
    border-right: 1px solid var(--toolbar-divider);
    border-radius: 0;
    background: transparent;
    color: var(--toolbar-text);
    font-size: 13px;
    font-weight: 700;
    white-space: nowrap;
  }

  .selection-toolbar button {
    min-width: 38px;
    padding: 0 10px;
  }

  .selection-toolbar button:hover {
    background: var(--toolbar-hover);
  }

  .selection-toolbar button.open {
    background: var(--toolbar-hover);
  }

  .selection-count {
    display: inline-flex;
    align-items: center;
    padding: 0 12px;
    color: var(--divider);
  }

  .toolbar-menu {
    position: relative;
  }

  .toolbar-menu > button::after {
    content: " ▾";
    font-size: 11px;
  }

  .toolbar-menu-popover {
    position: absolute;
    left: 0;
    bottom: calc(100% + 6px);
    z-index: 30;
    display: grid;
    min-width: 144px;
    overflow: hidden;
    border: 1px solid var(--toolbar-border);
    border-radius: 7px;
    background: var(--toolbar-surface);
    box-shadow: 0 14px 28px rgba(25, 40, 35, 0.22);
  }

  .toolbar-menu-popover.below {
    top: calc(100% + 6px);
    bottom: auto;
  }

  .toolbar-menu-popover button {
    justify-content: start;
    width: 100%;
    min-width: 0;
    height: 32px;
    border-right: 0;
    border-bottom: 1px solid var(--toolbar-divider);
    text-align: left;
  }

  .toolbar-menu-popover button:last-child {
    border-bottom: 0;
  }

  .slash-menu {
    position: absolute;
    z-index: 25;
    display: grid;
    width: min(380px, calc(100% - 32px));
    max-height: min(420px, calc(100% - 32px));
    overflow: auto;
    padding: 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    box-shadow: 0 18px 42px rgba(25, 40, 35, 0.22);
  }

  .slash-menu.table-mode {
    width: max-content;
    padding: 4px;
  }

  .table-toolbar {
    position: absolute;
    z-index: 22;
    display: flex;
    align-items: center;
    overflow: visible;
    border: 1px solid var(--toolbar-border);
    border-radius: 7px;
    background: var(--toolbar-surface);
    box-shadow: 0 14px 28px rgba(25, 40, 35, 0.22);
    white-space: nowrap;
  }

  .table-toolbar button {
    height: 34px;
    min-width: 38px;
    padding: 0 10px;
    border: 0;
    border-right: 1px solid var(--toolbar-divider);
    border-radius: 0;
    background: transparent;
    color: var(--toolbar-text);
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
  }

  .table-toolbar button:first-child {
    border-top-left-radius: 6px;
    border-bottom-left-radius: 6px;
  }

  .table-toolbar button:last-child {
    border-right: 0;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
  }

  .table-toolbar button:hover {
    background: var(--toolbar-hover);
  }

  .table-toolbar-sep {
    display: inline-block;
    width: 1px;
    height: 22px;
    background: var(--toolbar-divider);
  }

  .slash-group {
    padding: 8px 6px 5px;
    color: var(--text-3);
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .slash-filter-indicator {
    padding: 6px 10px;
    background: var(--inset);
    border-bottom: 1px solid var(--border);
    font-size: 12px;
    color: var(--text-2);
  }

  .slash-filter-indicator code {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
    color: var(--accent-deep);
    background: transparent;
  }

  .slash-empty {
    padding: 14px 12px;
    color: var(--text-3);
    font-size: 13px;
    font-style: italic;
    text-align: center;
  }

  .slash-empty code {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-style: normal;
    color: var(--text-2);
  }

  .slash-menu button {
    display: grid;
    gap: 3px;
    width: 100%;
    min-height: 58px;
    padding: 9px 10px;
    border-color: transparent;
    background: transparent;
    text-align: left;
  }

  .slash-menu button.active,
  .slash-menu button:hover {
    background: var(--accent-soft);
  }

  .slash-menu button strong {
    color: var(--text);
    font-size: 13px;
  }

  .slash-menu button span {
    color: var(--text-3);
    font-size: 12px;
    line-height: 1.35;
  }

  .slash-menu .table-grid {
    display: flex;
    flex-direction: column;
    gap: 1px;
    padding: 6px 10px 2px;
    width: max-content;
  }

  .slash-menu .table-grid-row {
    display: flex;
    gap: 1px;
  }

  .slash-menu .table-grid button {
    display: block;
    width: 13px;
    height: 13px;
    min-width: 13px;
    min-height: 13px;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 2px;
    background: var(--surface);
    cursor: pointer;
  }

  .slash-menu .table-grid button.active {
    background: var(--accent);
    border-color: var(--accent-deep);
  }

  .slash-menu .table-grid button:hover {
    background: var(--surface);
  }

  .slash-menu .table-grid button.active:hover {
    background: var(--accent);
  }

  .slash-menu .table-grid button:focus {
    outline: none;
  }

  .slash-menu .table-grid-label {
    padding: 4px 12px 10px;
    color: var(--text-2);
    font-size: 12px;
    text-align: center;
  }

  .ai-inline-toolbar {
    position: absolute;
    display: inline-flex;
    align-items: center;
    gap: 2px;
    padding: 4px 6px;
    background: rgba(34, 44, 40, 0.96);
    border-radius: 6px;
    font-size: 12px;
    color: var(--toolbar-text);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.22);
    z-index: 30;
    white-space: nowrap;
    user-select: none;
    transform: translateY(-2px);
  }

  .ai-toolbar-btn {
    background: transparent;
    border: none;
    color: inherit;
    padding: 4px 9px;
    font-size: 12px;
    font-weight: 500;
    cursor: pointer;
    border-radius: 4px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    line-height: 1;
  }

  .ai-toolbar-btn:hover {
    background: rgba(255, 255, 255, 0.13);
  }

  .ai-toolbar-btn:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }

  .ai-toolbar-accept {
    /* Light mint on the dark ai inline toolbar — correct in both themes
       (the toolbar surface never flips), so no palette token applies. */
    color: #9adfba;
  }

  .ai-toolbar-discard {
    color: var(--danger-border);
  }

  .ai-toolbar-meta {
    padding: 0 8px 0 6px;
    color: var(--border);
    font-style: italic;
    border-left: 1px solid rgba(255, 255, 255, 0.15);
    margin-left: 2px;
  }

  .ai-toolbar-status {
    padding: 2px 8px;
    font-style: italic;
  }

  .ai-toolbar-spinner {
    display: inline-block;
    padding-left: 6px;
    animation: ai-spin 1.1s linear infinite;
    transform-origin: center;
    font-size: 14px;
    line-height: 1;
  }

  @keyframes ai-spin {
    to { transform: rotate(360deg); }
  }

  .ai-inline-toolbar-loading {
    background: rgba(34, 60, 50, 0.96);
  }

  .ai-inline-toolbar-error {
    background: rgba(80, 30, 25, 0.97);
  }

  .ai-inline-toolbar-error .ai-toolbar-status {
    /* Light pink on the dark error toolbar — intentional in both themes. */
    color: #ffd4cc;
    font-style: normal;
  }
</style>
