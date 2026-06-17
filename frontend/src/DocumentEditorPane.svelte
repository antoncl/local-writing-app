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
  import MetadataLongTextEditor from "./MetadataLongTextEditor.svelte";
  import ReferencePicker from "./ReferencePicker.svelte";
  import { api } from "./api";
  import type { Backlink, EditableDocument, EntryMetadata, MetadataFieldDefinition, MetadataSchema, MetadataValue } from "./types";

  export let scene: EditableDocument | null = null;
  export let documentKind: "scene" | "lore" = "scene";
  export let metadataSchema: MetadataSchema | null = null;
  export let knownTags: string[] = [];
  export let metadataReload: { token: number; metadata: EntryMetadata; status?: string; entryType: string } | null = null;
  export let titleReload: { token: number; title: string } | null = null;
  export let dirty = false;
  export let todoStatusHint = "";

  const dispatch = createEventDispatcher<{
    change: { title: string; bodyMarkdown: string; status: string; entryType: string; metadata: EntryMetadata };
    focus: void;
    "custom-data": { entryType: string; kind: "scene" | "lore" };
    embeddedTodos: { todos: EmbeddedTodo[] };
    navigate: { id: string; kind: string };
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
    run: () => void | Promise<void>;
  };

  const TABLE_GRID_MAX_ROWS = 8;
  const TABLE_GRID_MAX_COLS = 8;

  // Built-in template for "continue from cursor". Will move to a prompt node in M5.
  const CONTINUE_SCENE_TEMPLATE = `{% role "system" %}
You are an expert fiction writer. Continue the scene in the same voice and style as the existing prose. Match register, POV, and prose rhythm. Do not conclude the scene — push it forward by one beat only.
{% endrole %}

{% role "user" %}
{% if pov(scene) %}POV: {{ pov(scene).title }}
{% endif %}
{{ relevant_lore(scene) }}
{% if scenes_before(scene) %}

The story so far:
{{ scenes_before(scene) }}
{% endif %}

{% if text_before %}
Here is the scene so far:
<<<
{{ text_before }}
>>>

Continue from where it left off. Write about {{ input.words | default(250) }} words. Output prose only — no preamble, no explanation, no closing remarks.
{% else %}
Open the scene. Write about {{ input.words | default(250) }} words to start it. Output prose only — no preamble.
{% endif %}
{% endrole %}`;
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
  let aiSuggestionMeta: { provider: string; model: string; latency_ms: number; truncated: boolean; wordCount: number } | null = null;
  let aiToolbarPosition: { x: number; y: number; visible: boolean } = { x: 0, y: 0, visible: false };
  let aiNextSuggestionId = 1;

  $: slashCommands = editor && documentKind === "scene" ? getSlashCommands() : [];
  $: activeSlashCommand = slashCommands[slashMenu.selectedIndex];
  $: selectionToolbarActions = editor ? getSelectionToolbarActions() : [];
  $: documentLabel = documentKind === "lore" ? "Entry" : "Scene";
  $: documentNameLabel = documentKind === "lore" ? "Name" : "Title";
  $: documentEntryTypes = Object.entries(metadataSchema?.entry_types ?? {}).filter(([, definition]) => definition.kind === documentKind && !definition.abstract);
  $: activeEntryType = metadataSchema?.entry_types[entryType] ?? metadataSchema?.entry_types[defaultEntryType()];
  $: metadataFieldIds = activeEntryType?.fields ?? [];
  $: hasBody = activeEntryType?.has_body ?? true;
  $: metadataSummaryText = buildMetadataSummary(activeEntryType?.name ?? entryType, status, liveWordCount, hasBody);

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

  $: if (editor && scene && scene.id !== loadedSceneId) {
    void loadScene(scene);
  }

  $: if (editor && !scene && loadedSceneId !== null) {
    loadedSceneId = null;
    title = "";
    status = defaultStatus();
    entryType = defaultEntryType();
    metadata = {};
    tagPickerFieldId = null;
    tagPickerPosition = null;
    liveWordCount = 0;
    editor.commands.clearContent(false);
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
        TodoAnchor,
        Table.configure({ resizable: true }),
        TableRow,
        AlignedTableHeader,
        AlignedTableCell,
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
      },
      onUpdate: () => {
        if (!enforceUniqueTodoAnchors()) {
          emitChange();
        }
        if (aiSuggestionId) updateAIToolbarPosition();
      },
      onSelectionUpdate: () => {
        updateSelectionMenu();
        updateTableMenu();
        if (aiSuggestionId) updateAIToolbarPosition();
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

  async function loadScene(nextScene: Scene) {
    const sceneId = nextScene.id;
    title = nextScene.title;
    status = documentStatus(nextScene);
    entryType = nextScene.entry_type || defaultEntryType();
    metadata = cloneMetadata(nextScene.metadata);
    // Drop any pending AI suggestion state when changing documents.
    aiSuggestionId = null;
    aiSuggestionMeta = null;
    aiError = null;
    const nextEntryDefinition = metadataSchema?.entry_types[entryType];
    const nextHasBody = nextEntryDefinition?.has_body ?? true;
    metadataExpanded = documentKind === "lore" || !nextHasBody;
    tagPickerFieldId = null;
    tagPickerPosition = null;
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
    if (!scene || !editor) return;
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

  function handleEditorKeydown(view: EditorView, event: KeyboardEvent) {
    if (documentKind !== "scene") {
      if (slashMenu.visible) closeSlashMenu();
      return false;
    }

    // Ctrl/⌘+J: AI continue at cursor (regardless of slash menu state).
    if (event.key.toLowerCase() === "j" && (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey) {
      event.preventDefault();
      void runAIContinue();
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
      if (event.key === "ArrowDown") {
        event.preventDefault();
        slashMenu = { ...slashMenu, selectedIndex: (slashMenu.selectedIndex + 1) % slashCommands.length };
        return true;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        slashMenu = {
          ...slashMenu,
          selectedIndex: (slashMenu.selectedIndex - 1 + slashCommands.length) % slashCommands.length,
        };
        return true;
      }
      if (event.key === "Enter" && activeSlashCommand) {
        event.preventDefault();
        runSlashCommand(activeSlashCommand);
        return true;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeSlashMenu();
        return true;
      }
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

  function isSlashTriggerContext() {
    if (documentKind !== "scene") return false;
    if (!editor) return false;
    const { selection } = editor.state;
    return selection.empty && selection.$from.parent.type.name === "paragraph" && selection.$from.parent.textContent.trim() === "/";
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
    if (paragraphText.trim() === "/") {
      editor.chain().focus().deleteRange({ from: paragraphStart, to: paragraphStart + paragraphText.length }).run();
    }
  }

  function runSlashCommand(command: SlashCommand) {
    command.run();
    clearSlashTrigger();
    if (slashMenu.mode === "commands") {
      closeSlashMenu();
      syncEditorEmpty();
    }
  }

  async function runAIContinue() {
    if (!editor || !scene || aiGenerating || documentKind !== "scene") return;
    if (aiSuggestionId) {
      aiError = "Accept or revert the pending suggestion before generating another.";
      return;
    }
    const cursorPos = editor.state.selection.from;
    const docSize = editor.state.doc.content.size;
    const textBefore = editor.state.doc.textBetween(0, cursorPos, "\n\n", " ");
    const textAfter = editor.state.doc.textBetween(cursorPos, docSize, "\n\n", " ");

    aiError = null;
    aiGenerating = true;
    try {
      const response = await api.aiGenerate({
        template_source: CONTINUE_SCENE_TEMPLATE,
        target_scene_id: scene.id,
        session_id: scene.id,
        inputs: {},
        text_before: textBefore,
        text_after: textAfter,
        commit: false,
      });
      if (!response.ok) {
        aiError = response.error ?? "Unknown error";
        return;
      }
      if (!response.content.trim()) {
        aiError = "Model returned empty output.";
        return;
      }
      insertAISuggestion(response.content);
      aiSuggestionMeta = {
        provider: response.provider,
        model: response.model,
        latency_ms: response.latency_ms,
        truncated: response.truncated,
        wordCount: countWords(response.content),
      };
    } catch (e) {
      aiError = (e as Error).message;
    } finally {
      aiGenerating = false;
    }
  }

  function updateAIToolbarPosition() {
    if (!editor || !editorFrame || !aiSuggestionId) {
      if (aiToolbarPosition.visible) aiToolbarPosition = { x: 0, y: 0, visible: false };
      return;
    }
    const range = findAISuggestionRange(aiSuggestionId);
    if (!range) {
      aiToolbarPosition = { x: 0, y: 0, visible: false };
      return;
    }
    try {
      const coords = editor.view.coordsAtPos(range.from);
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

  function acceptAISuggestion() {
    if (!editor || !aiSuggestionId) return;
    const range = findAISuggestionRange(aiSuggestionId);
    if (range) {
      editor
        .chain()
        .focus()
        .setTextSelection(range)
        .unsetMark("aiSuggestion")
        .setTextSelection(range.to)
        .run();
    }
    aiSuggestionId = null;
    aiSuggestionMeta = null;
    aiError = null;
    aiToolbarPosition = { x: 0, y: 0, visible: false };
  }

  function revertAISuggestion() {
    if (!editor || !aiSuggestionId) return;
    const range = findAISuggestionRange(aiSuggestionId);
    if (range) {
      editor.chain().focus().deleteRange(range).run();
    }
    aiSuggestionId = null;
    aiSuggestionMeta = null;
    aiError = null;
    aiToolbarPosition = { x: 0, y: 0, visible: false };
  }

  async function retryAISuggestion() {
    if (!aiSuggestionId || aiGenerating) return;
    revertAISuggestion();
    await runAIContinue();
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
        description: "Pick the size, then click to insert.",
        run: () => openTableGrid(),
      },
      {
        group: "AI",
        label: "AI: Continue scene",
        description: "Generate the next beat at the cursor.",
        run: () => {
          clearSlashTrigger();
          void runAIContinue();
        },
      },
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
        {#if todoStatusHint}
          {todoStatusHint}
        {:else if editorEmpty}
          {documentKind === "scene" ? "Start writing, or type / for commands." : "Start writing."}
        {:else}
          {documentKind === "scene" ? "Select text for formatting. Type / on an empty line for insert commands." : "Select text for formatting."}
        {/if}
      </div>
      {#if metadataSchema}
        <section class="scene-metadata" aria-label={`${documentLabel} metadata`}>
          <div class="metadata-stripe">
            <button class="metadata-toggle" type="button" on:click={() => (metadataExpanded = !metadataExpanded)}>
              <strong>{metadataExpanded ? "Hide Metadata" : "Show Metadata"}</strong>
              <span>{metadataSummaryText}</span>
            </button>
            <button
              class="metadata-custom-button"
              type="button"
              on:click={() => dispatch("custom-data", { entryType, kind: documentKind })}
            >
              Custom data
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
                          on:change={(event) => updateMetadataField(fieldId, field, event.detail.value)}
                        />
                      </div>
                    {:else if field.type === "entity_ref" || field.type === "entity_ref_list"}
                      <div class="metadata-field wide-field">
                        <span class="metadata-field-label">{field.name}</span>
                        <ReferencePicker
                          {field}
                          value={metadataReferenceValue(field, metadata[fieldId])}
                          metadataSchema={metadataSchema}
                          excludeId={scene?.id ?? null}
                          ariaLabel={field.name}
                          on:change={(event) => updateMetadataField(fieldId, field, event.detail.value)}
                        />
                      </div>
                    {:else if field.type === "multi_select" && field.options.length > 0}
                      <div class="metadata-field wide-field">
                        <span class="metadata-field-label">{field.name}</span>
                        <div class="multi-select-chips" aria-label={field.name}>
                          {#each field.options as option}
                            <button
                              class:active={isMultiSelectOptionSelected(fieldId, option)}
                              class="multi-select-chip"
                              type="button"
                              on:click={() => toggleMultiSelectOption(fieldId, field, option)}
                            >
                              {option}
                            </button>
                          {/each}
                        </div>
                      </div>
                    {:else}
                      <label class:wide-field={field.type === "computed"}>
                        {field.name}
                        {#if fieldId === "status"}
                        <select value={status} on:change={(event) => updateStatus(event.currentTarget.value)}>
                          {#if status && !field.options.includes(status)}
                            <option value={status}>{status}</option>
                          {/if}
                          {#each field.options as option}
                            <option value={option}>{option}</option>
                          {/each}
                        </select>
                        {:else if field.type === "select"}
                        {#key `${fieldId}:${currentValue}:${field.options.join("\u0000")}`}
                          <select data-metadata-field-id={fieldId} use:syncSelectValue={currentValue} on:change={(event) => updateMetadataField(fieldId, field, event.currentTarget.value)}>
                            <option value="" selected={currentValue === ""}></option>
                            {#if currentValue && !field.options.includes(currentValue)}
                              <option value={currentValue} selected>{currentValue}</option>
                            {/if}
                            {#each field.options as option}
                              <option value={option} selected={option === currentValue}>{option}</option>
                            {/each}
                          </select>
                        {/key}
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
          <div class="backlinks-stripe">
            <button class="backlinks-toggle" type="button" on:click={() => (backlinksExpanded = !backlinksExpanded)}>
              <strong>{backlinksExpanded ? "Hide References" : "Show References"}</strong>
              <span>{backlinks.length} incoming</span>
            </button>
          </div>
          {#if backlinksExpanded}
            <div class="backlinks-panel">
              {#if backlinks.length === 0}
                <div class="backlinks-empty">No incoming references.</div>
              {:else}
                {#each backlinks as link (`${link.id}:${link.field_id}`)}
                  <button class="backlink-row" type="button" on:click={() => dispatch("navigate", { id: link.id, kind: link.kind })}>
                    <span class="backlink-title">{link.title}</span>
                    <span class="backlink-field">{link.field_name}</span>
                  </button>
                {/each}
              {/if}
            </div>
          {/if}
        </section>
      {/if}
    {:else}
      <h2>Select a scene</h2>
    {/if}
  </section>

  <div class:empty-editor={editorEmpty} class:lore-editor={documentKind === "lore"} class:hidden-body={!hasBody} class="editor-wrap" bind:this={editorFrame}>
    {#if aiGenerating || aiError}
      <div class="ai-banner" class:ai-banner-error={!!aiError} class:ai-banner-loading={aiGenerating}>
        {#if aiGenerating}
          <span class="ai-banner-label">AI generating…</span>
        {:else if aiError}
          <span class="ai-banner-label">AI error: {aiError}</span>
          <button type="button" on:click={() => (aiError = null)}>Dismiss</button>
        {/if}
      </div>
    {/if}
    {#if aiSuggestionId && aiToolbarPosition.visible}
      <div class="ai-inline-toolbar" style={`left: ${aiToolbarPosition.x}px; top: ${aiToolbarPosition.y}px;`}>
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
          </span>
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
          {#each slashCommands as command, index}
            {#if index === 0 || slashCommands[index - 1].group !== command.group}
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
