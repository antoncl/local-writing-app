<script lang="ts">
  import { onMount, tick } from "svelte";
  import { api } from "./api";
  import CodeEditor from "./CodeEditor.svelte";
  import DocumentEditorPane from "./DocumentEditorPane.svelte";
  import PromptInputField from "./PromptInputField.svelte";
  import TopBar from "./TopBar.svelte";
  import type {
    AIHealthResponse,
    AIPolicy,
    AssistantEntry,
    AssistantEntrySummary,
    Backlink,
    ChatMessage,
    ChatSession,
    ChatSessionContextItem,
    ChatSessionMessage,
    ChatSessionSummary,
    DirectoryListing,
    EditableDocument,
    EntryMetadata,
    EntryTypeDefinition,
    LoreEntry,
    LoreEntrySummary,
    PromptEntry,
    PromptEntrySummary,
    Scene,
    MachineSettingsUpdate,
    MachineSettingsView,
    MetadataFieldDefinition,
    MetadataFieldType,
    MetadataSchema,
    MetadataSchemaLayer,
    MetadataSchemaOverview,
    PromptContextStrategy,
    PromptEntryTypeExtras,
    PromptInputDefinition,
    ProjectInfo,
    ProjectNode,
    RecentProject,
    ProjectValidation,
    SearchHit,
    StructureDocument,
    StructureNode,
    StructureNodeDeletePreview,
    TodoItem,
  } from "./types";

  type AppState =
    | { name: "needsProject" }
    | { name: "projectOpen"; project: ProjectInfo };
  type DocumentRef = { type: "scene" | "lore" | "prompt" | "assistant" | "project"; id: string };
  type PaneId = "project" | "outline" | "lore" | "todo" | "search" | string;
  type MetadataReloadSignal = { token: number; metadata: EntryMetadata; status: string; entryType: string };
  type LoreEntryGroup = {
    id: string;
    label: string;
    entries: LoreEntrySummary[];
    depth: number;
  };
  type NodeTypeOption = {
    id: string;
    label: string;
    depth: number;
    definition: EntryTypeDefinition;
  };
  type NodeTypeTreeNode = NodeTypeOption & {
    children: NodeTypeTreeNode[];
  };
  type PaneState = {
    title: string;
    x: number;
    y: number;
    width: number;
    height: number;
    z: number;
  };
  type EditorPaneState = {
    id: string;
    document: DocumentRef | null;
    scene: EditableDocument | null;
    pinned: boolean;
    dirty: boolean;
    draftTitle: string;
    draftMarkdown: string;
    draftStatus: string;
    draftEntryType: string;
    draftMetadata: EntryMetadata;
    // Per-entry prompt inputs. Only meaningful when document.type === "prompt";
    // ignored for other kinds. Persisted in the entry's YAML on save.
    draftInputs: PromptInputDefinition[];
    saving: boolean;
  };

  type ConfirmationState = {
    title: string;
    message: string;
    details?: string[];
    confirmLabel: string;
    destructive: boolean;
    onConfirm: () => Promise<void>;
  };
  type EmbeddedTodo = {
    id: string;
    text: string;
    status: "open" | "done";
    note: string;
    paneId: string;
    sceneId: string;
    sceneTitle: string;
  };

  let projectPath = "";
  let projectTitle = "Untitled Project";
  let directoryPickerOpen = false;
  let directoryListing: DirectoryListing | null = null;
  let directoryPickerLoading = false;
  // Tracks why the directory picker was opened so the "Select This Folder"
  // button does the right thing on confirm. Null = picker not open.
  // "openProject" → immediately open the picked folder as a project.
  // "newProjectOverride" → set newProjectOverridePath (don't create yet).
  let directoryPickerMode: "openProject" | "newProjectOverride" | null = null;

  let aiPolicy: AIPolicy = "off";
  let aiDefaultProvider = "";
  let aiDefaultModelClass = "";
  let aiHealthResult: AIHealthResponse | null = null;
  let aiHealthChecking = false;

  let machineSettings: MachineSettingsView | null = null;
  let machineSettingsOpen = false;

  // Recent projects + default base folder come from machine settings.
  // Reloaded after open/create (which push onto the recents list) and after
  // machine-settings saves (which can change the default folder).
  let recentProjects: RecentProject[] = [];
  let defaultProjectsFolder = "";

  // New Project modal — separate from the path/title state used by the
  // (now-removed) inline create form. Kept self-contained so closing the
  // modal doesn't bleed into the rest of the app.
  let newProjectModalOpen = false;
  let newProjectName = "";
  let newProjectOverrideFolder = false;
  let newProjectOverridePath = "";

  // AI chat pane state.
  const DEFAULT_CHAT_SYSTEM_PROMPT =
    "You are a brainstorming partner for a fiction writer. " +
    "Be concise, propose options, and don't write prose unless asked.";
  let chatSystemPrompt = DEFAULT_CHAT_SYSTEM_PROMPT;
  // "" means: use the user's default assistant (resolved server-side).
  let chatAssistantId = "";
  let chatInput = "";
  let chatHistory: { role: "user" | "assistant"; content: string; truncated?: boolean; thinking?: string }[] = [];
  let chatRunning = false;
  let chatError: string | null = null;
  let chatLastMeta: { provider: string; model: string; latency_ms: number } | null = null;
  let chatScrollEl: HTMLDivElement | null = null;
  let chatActivePromptEntry: { id: string; title: string } | null = null;
  type ChatContextKind = "scene" | "lore" | "snippet" | "preset";
  type ChatContextItem = {
    id: string;
    kind: ChatContextKind;
    title: string;
    entryType: string;
  };
  let chatContextItems: ChatContextItem[] = [];
  let chatContextMenuOpen = false;
  let chatContextCategory: ChatContextKind | null = null;
  let chatContextSearch = "";
  let chatSessions: ChatSessionSummary[] = [];
  let activeChatId: string | null = null;
  let activeChatTitle = "Untitled chat";
  let activeChatPinned = false;
  // The locked prompt for the active chat. Empty string means "freeform" (no
  // prompt). Once chatHistory has messages, this becomes immutable for the
  // session — switching prompts creates a new chat.
  let chatPromptEntryId = "";
  let promptPickerOpen = false;
  let promptPickerSearch = "";
  // Inputs dialog for chat-routed prompts that declare {{ input.* }} fields.
  // Opens between picker selection and applying the preset; the user fills
  // values, then we materialize the template and seed the chat.
  let chatInputsDialogEntry: PromptEntrySummary | null = null;
  let chatInputsDialogDrafts: Record<string, string> = {};
  let chatInputsDialogError = "";
  // Remember last-used inputs per prompt id so re-picking the same prompt
  // prefills with the user's last values instead of resetting to defaults.
  let chatInputsLastUsed: Record<string, Record<string, string>> = {};
  // Preview disclosure state. The text is computed on demand (composing the
  // context block requires async fetches) and invalidated when the user changes
  // assistant / brief / context / prompt.
  let promptPreviewText: string | null = null;
  let promptPreviewLoading = false;
  let promptPreviewError: string | null = null;
  type MachineSettingsDraft = {
    anthropic_api_key: string;
    openai_api_key: string;
    openrouter_api_key: string;
    ollama_host: string;
    default_provider: string;
    default_models: Record<string, string>;
    default_projects_folder: string;
  };
  let machineSettingsDraft: MachineSettingsDraft | null = null;
  let appState: AppState = { name: "needsProject" };
  $: project = appState.name === "projectOpen" ? appState.project : null;
  $: isProjectOpen = appState.name === "projectOpen";
  let structure: StructureDocument | null = null;
  let loreEntries: LoreEntrySummary[] = [];
  let knownTags: string[] = [];
  let focusedEditorPaneId: string | null = null;
  $: focusedEditorPane = editorPanes.find((pane) => pane.id === focusedEditorPaneId) ?? editorPanes[0] ?? null;
  $: activeScene = focusedEditorPane?.document?.type === "scene" ? focusedEditorPane.scene : null;
  let activeParentId: string | undefined = undefined;
  let addMenuOpenFor: string | null = null;
  let editingNodeId: string | null = null;
  let editingTitle = "";
  let draftTitleByScene = new Map<string, string>();
  let draggedNodeId: string | null = null;
  let dragOverNodeId: string | null = null;
  let dragOverPosition: "before" | "after" | "into" | null = null;
  let todos: TodoItem[] = [];
  let validation: ProjectValidation | null = null;
  let metadataSchema: MetadataSchema | null = null;
  let metadataSchemaOverview: MetadataSchemaOverview | null = null;
  let metadataSchemaLayers: MetadataSchemaLayer[] = [];
  let schemaFieldKind: "scene" | "lore" | "prompt" | "assistant" | "project" = "scene";
  let schemaFieldLayerId = "";
  let schemaFieldEntryType = "scene";
  let schemaFieldId = "";
  let schemaFieldName = "";
  let schemaFieldType: MetadataFieldType = "text";
  let schemaFieldAllowMultiple = false;
  let schemaFieldReferenceTarget: "scene" | "lore" = "lore";
  let schemaFieldReferenceEntryType = "";
  let schemaFieldOptions = "";
  let schemaFieldReadonlyTypeLabel = "";
  let selectedSchemaFieldId: string | null = null;
  let schemaFieldReadonly = false;
  let schemaPaneOpen = false;
  let schemaFieldPaneOpen = false;
  let schemaTypePaneOpen = false;
  let schemaTypeLayerId = "";
  let schemaTypeId = "";
  let schemaTypeName = "";
  let schemaTypeKind: "scene" | "lore" | "prompt" | "assistant" | "project" = "lore";
  let schemaTypeParent = "";
  let schemaTypeAbstract = false;
  let schemaTypeReadonly = false;
  let selectedSchemaTypeId: string | null = null;
  let draggedSchemaTypeId: string | null = null;
  let schemaSelectedEntryType: EntryTypeDefinition | null = null;
  let schemaNodeTypeOptions: NodeTypeOption[] = [];
  let schemaNodeTypeTree: NodeTypeTreeNode[] = [];
  let promptsPaneOpen = false;
  let assistantsPaneOpen = false;
  let chatsPaneOpen = false;
  let promptSystemPrompt = "";
  let promptModelClass = "";
  let promptProviderPolicy: AIPolicy | "" = "";
  let promptContextTargetKind = "";
  let promptContextTargetRequired = false;
  let promptScanSurface = "";
  let promptOutputKind = "";
  let promptOutputReview = "";
  let promptEntries: PromptEntrySummary[] = [];
  let assistantEntries: AssistantEntrySummary[] = [];
  let newTodo = "";
  let searchQuery = "";
  let loreSearchQuery = "";
  let collapsedLoreGroups: Record<string, boolean> = {};
  let collapsedSchemaFieldsByType: Record<string, boolean> = {};
  let searchOpenTodos = false;
  let searchHits: SearchHit[] = [];
  let confirmation: ConfirmationState | null = null;
  let error = "";
  let status = "No project open";
  let nextZ = 10;
  let nextEditorPaneIndex = 1;
  let dragState: { id: PaneId; element: HTMLElement; offsetX: number; offsetY: number } | null = null;
  let resizeState:
    | { id: PaneId; element: HTMLElement; startX: number; startY: number; startWidth: number; startHeight: number }
    | null = null;
  let panes: Record<PaneId, PaneState> = {
    project: { title: "Project", x: 18, y: 18, width: 380, height: 340, z: 1 },
    outline: { title: "Manuscript Outline", x: 18, y: 260, width: 300, height: 420, z: 2 },
    lore: { title: "Lore", x: 330, y: 260, width: 300, height: 320, z: 3 },
    schema: { title: "Detail Types", x: 330, y: 260, width: 360, height: 420, z: 3 },
    schema_field: { title: "Detail Field", x: 708, y: 260, width: 360, height: 420, z: 4 },
    schema_type: { title: "Detail Type", x: 708, y: 260, width: 440, height: 560, z: 4 },
    prompts: { title: "Prompts", x: 330, y: 260, width: 360, height: 420, z: 3 },
    assistants: { title: "Assistants", x: 330, y: 260, width: 340, height: 420, z: 3 },
    chats: { title: "Chats", x: 330, y: 260, width: 320, height: 420, z: 3 },
    todo: { title: "TODO", x: 1126, y: 18, width: 310, height: 320, z: 4 },
    search: { title: "Search", x: 1126, y: 360, width: 310, height: 320, z: 5 },
    chat: { title: "AI Chat", x: 1210, y: 18, width: 420, height: 600, z: 7 },
  };
  let editorPanes: EditorPaneState[] = [];
  let nextMetadataReloadToken = 1;
  let metadataReloadsByPane: Record<string, MetadataReloadSignal> = {};
  let titleReloadsByPane: Record<string, { token: number; title: string }> = {};
  let editorPaneComponents: Record<
    string,
    | {
        updateEmbeddedTodo: (todoId: string, updates: { status?: "open" | "done"; note?: string }) => void;
        deleteEmbeddedTodo: (todoId: string) => void;
        highlightEmbeddedTodo: (todoId: string) => void;
      }
    | undefined
  > = {};
  let embeddedTodosByPane: Record<string, EmbeddedTodo[]> = {};
  let embeddedTodoStatusHintsByPane: Record<string, string> = {};
  let allEmbeddedTodos: EmbeddedTodo[] = [];

  $: allEmbeddedTodos = Object.values(embeddedTodosByPane).flat();
  $: embeddedTodoStatusHintsByPane = buildEmbeddedTodoStatusHintsByPane(embeddedTodosByPane);
  $: filteredLoreEntries = filterLoreEntries(loreEntries, loreSearchQuery);
  $: draftTitleByScene = computeDraftTitleOverrides(editorPanes);

  function computeDraftTitleOverrides(panes: EditorPaneState[]): Map<string, string> {
    const map = new Map<string, string>();
    for (const pane of panes) {
      const sceneId = pane.scene?.id;
      if (!sceneId) continue;
      const trimmed = pane.draftTitle.trim();
      if (trimmed && trimmed !== pane.scene?.title) {
        map.set(sceneId, trimmed);
      }
    }
    return map;
  }
  $: groupedLoreEntries = groupLoreEntriesByType(filteredLoreEntries, metadataSchema);
  $: schemaSelectedEntryType = metadataSchema?.entry_types[schemaFieldEntryType] ?? metadataSchema?.entry_types.scene ?? null;
  $: schemaFieldKind =
    schemaSelectedEntryType?.kind === "lore"
      ? "lore"
      : schemaSelectedEntryType?.kind === "prompt"
        ? "prompt"
        : schemaSelectedEntryType?.kind === "assistant"
          ? "assistant"
          : schemaSelectedEntryType?.kind === "project"
            ? "project"
            : "scene";
  $: schemaNodeTypeOptions = buildNodeTypeOptions(metadataSchema);
  $: schemaNodeTypeTree = buildNodeTypeTree(metadataSchema, schemaFieldKind);
  $: schemaContextHeading =
    schemaFieldKind === "lore"
      ? "Lore Entry Types"
      : schemaFieldKind === "prompt"
        ? "Prompt Types"
        : schemaFieldKind === "assistant"
          ? "Assistant Types"
          : schemaFieldKind === "project"
            ? "Project Types"
            : "Scene Types";
  $: concretePromptSubtypes = Object.entries(metadataSchema?.entry_types ?? {})
    .filter(([id, definition]) => definition.kind === "prompt" && !definition.abstract && id !== "prompt")
    .map(([id, definition]) => ({ id, label: definition.name || id }))
    .sort((a, b) => a.label.localeCompare(b.label));

  onMount(() => {
    fitPanesToViewport();
    document.addEventListener("mousedown", handleDocumentMousedown);
    // Eagerly fetch machine settings so the chat panel and inputs dialog
    // can show the assistant roster without a round-trip when first opened.
    // Failure is non-fatal — both UIs fall back to "default assistant".
    void loadMachineSettings();
    return () => {
      document.removeEventListener("mousemove", movePane);
      document.removeEventListener("mouseup", stopPaneDrag);
      document.removeEventListener("mousemove", resizePane);
      document.removeEventListener("mouseup", stopPaneResize);
      document.removeEventListener("mousedown", handleDocumentMousedown);
    };
  });

  async function loadMachineSettings() {
    try {
      machineSettings = await api.getMachineSettings();
      recentProjects = machineSettings.recent_projects ?? [];
      defaultProjectsFolder = machineSettings.default_projects_folder ?? "";
    } catch {
      // Backend may be offline — leave machineSettings as null; pickers will
      // hide and the request falls back to the backend's default assistant.
    }
    // The file-backed assistant index is canonical for the chat-panel and
    // inputs-dialog pickers; load it eagerly alongside machine settings.
    await refreshAssistantEntries();
  }

  // Re-pull machine settings just to refresh the recents list. Called after
  // open/create routes — they touch_recent_project server-side; the UI
  // needs the new list to render the switcher dropdown.
  async function refreshRecents() {
    try {
      const view = await api.getMachineSettings();
      machineSettings = view;
      recentProjects = view.recent_projects ?? [];
      defaultProjectsFolder = view.default_projects_folder ?? "";
    } catch {
      // Non-fatal — recents stays stale until next reload.
    }
  }

  function handleDocumentMousedown(event: MouseEvent) {
    const target = event.target as HTMLElement | null;
    if (addMenuOpenFor !== null && !target?.closest(".tree-menu-anchor")) {
      addMenuOpenFor = null;
    }
    if (chatContextMenuOpen && !target?.closest(".chat-context-anchor")) {
      chatContextMenuOpen = false;
      chatContextCategory = null;
      chatContextSearch = "";
    }
    if (promptPickerOpen && !target?.closest(".chat-prompt-anchor")) {
      closeChatPromptPicker();
    }
  }

  function createEmptyEditorPane(id: string): EditorPaneState {
    return {
      id,
      document: null,
      scene: null,
      pinned: false,
      dirty: false,
      draftTitle: "",
      draftMarkdown: "",
      draftStatus: "draft",
      draftEntryType: "scene",
      draftMetadata: {},
      draftInputs: [],
      saving: false,
    };
  }

  $: paneStyleMap = buildPaneStyleMap(panes);

  function buildPaneStyleMap(source: Record<PaneId, PaneState>): Record<string, string> {
    const result: Record<string, string> = {};
    for (const [id, pane] of Object.entries(source)) {
      result[id] = `left: ${pane.x}px; top: ${pane.y}px; width: ${pane.width}px; height: ${pane.height}px; z-index: ${pane.z};`;
    }
    return result;
  }

  function paneStyle(id: PaneId) {
    return paneStyleMap[id] ?? "";
  }

  // Reactive function: rebound whenever any visibility-deciding state changes.
  // Templates that call `isPaneVisible(id)` track the function's identity — so
  // when this `$:` recomputes, every callsite re-runs and the pane shows.
  //
  // Why this is necessary: function calls are opaque to Svelte's template
  // dependency analyzer. A plain `function isPaneVisible(id)` that reads
  // `chatsPaneOpen` inside doesn't tell the compiler that flipping
  // `chatsPaneOpen` should re-evaluate `class:hidden-pane={!isPaneVisible("chats")}`.
  // The `$:` rebinding gives the template a tracked dependency.
  $: isPaneVisible = ((
    _isProjectOpen,
    _assistantsPaneOpen,
    _schemaPaneOpen,
    _schemaFieldPaneOpen,
    _schemaTypePaneOpen,
    _promptsPaneOpen,
    _chatsPaneOpen,
    _editorPanes,
  ) => (id: PaneId): boolean => {
    if (id === "project") return true;
    if (id === "assistants") return _assistantsPaneOpen;
    if (!_isProjectOpen) return false;
    if (id === "schema") return _schemaPaneOpen;
    if (id === "schema_field") return _schemaFieldPaneOpen;
    if (id === "schema_type") return _schemaTypePaneOpen;
    if (id === "prompts") return _promptsPaneOpen;
    if (id === "chats") return _chatsPaneOpen;
    return !isEditorPaneId(id) || _editorPanes.some((pane) => pane.id === id);
  })(
    isProjectOpen,
    assistantsPaneOpen,
    schemaPaneOpen,
    schemaFieldPaneOpen,
    schemaTypePaneOpen,
    promptsPaneOpen,
    chatsPaneOpen,
    editorPanes,
  );

  function isEditorPaneId(id: PaneId) {
    return id.startsWith("editor_");
  }

  function openProjectWorkspace(nextProject: ProjectInfo) {
    resetEditorWorkspace();
    projectPath = nextProject.root_path;
    projectTitle = nextProject.title;
    aiPolicy = nextProject.ai_policy;
    aiDefaultProvider = nextProject.ai_default_provider ?? "";
    aiDefaultModelClass = nextProject.ai_default_model_class ?? "";
    aiHealthResult = null;
    appState = { name: "projectOpen", project: nextProject };
    fitPanesToViewport();
    focusPane("outline");
    void hydrateChatSessionsForProject();
  }

  function resetEditorWorkspace() {
    editorPanes = [];
    knownTags = [];
    focusedEditorPaneId = null;
    nextEditorPaneIndex = 1;
    nextMetadataReloadToken = 1;
    metadataReloadsByPane = {};
    titleReloadsByPane = {};
    activeChatId = null;
    activeChatTitle = "Untitled chat";
    activeChatPinned = false;
    chatPromptEntryId = "";
    chatSessions = [];
    clearChat();
    chatSystemPrompt = DEFAULT_CHAT_SYSTEM_PROMPT;
    // Preserve all pane configs. An earlier version stripped chat/preview/
    // prompts/assistants/chats out of `panes`, which made `panes.chats` etc.
    // undefined after a project switch — focusPane then created `{ z }` entries
    // with no left/top/width/height, and paneStyle returned an empty string,
    // so opening those panes did nothing visible. Pane positions and sizes are
    // pure UI state; nothing project-specific lives here.
  }

  function fitPanesToViewport() {
    const margin = 8;
    panes = Object.fromEntries(
      Object.entries(panes).map(([id, pane]) => [
        id,
        {
          ...pane,
          x: Math.min(pane.x, Math.max(margin, window.innerWidth - pane.width - margin)),
          y: Math.min(pane.y, Math.max(margin, window.innerHeight - 48)),
        },
      ]),
    ) as Record<PaneId, PaneState>;
  }

  function focusPane(id: PaneId) {
    if (isEditorPaneId(id) && editorPanes.some((pane) => pane.id === id)) {
      focusedEditorPaneId = id;
    }
    nextZ += 1;
    const z = nextZ;
    panes = {
      ...panes,
      [id]: { ...panes[id], z },
    };
    const pane = document.querySelector<HTMLElement>(`.pane[data-pane-id="${id}"]`);
    if (pane) pane.style.zIndex = String(z);
  }

  function startPaneDrag(event: MouseEvent, id: PaneId) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const element = (event.currentTarget as HTMLElement).closest<HTMLElement>(".pane");
    if (!element) return;
    focusPane(id);
    dragState = {
      id,
      element,
      offsetX: event.clientX - element.offsetLeft,
      offsetY: event.clientY - element.offsetTop,
    };
    document.addEventListener("mousemove", movePane);
    document.addEventListener("mouseup", stopPaneDrag, { once: true });
  }

  function movePane(event: MouseEvent) {
    if (!dragState) return;
    const margin = 8;
    const pane = panes[dragState.id];
    const maxX = Math.max(margin, window.innerWidth - 88);
    const maxY = Math.max(margin, window.innerHeight - 48);
    const x = Math.min(Math.max(margin, event.clientX - dragState.offsetX), maxX);
    const y = Math.min(Math.max(margin, event.clientY - dragState.offsetY), maxY);
    dragState.element.style.left = `${x}px`;
    dragState.element.style.top = `${y}px`;
    panes = {
      ...panes,
      [dragState.id]: { ...pane, x, y },
    };
  }

  function stopPaneDrag() {
    dragState = null;
    document.removeEventListener("mousemove", movePane);
    document.removeEventListener("mouseup", stopPaneDrag);
  }

  function startPaneResize(event: MouseEvent, id: PaneId) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    const element = (event.currentTarget as HTMLElement).closest<HTMLElement>(".pane");
    if (!element) return;
    focusPane(id);
    resizeState = {
      id,
      element,
      startX: event.clientX,
      startY: event.clientY,
      startWidth: element.offsetWidth,
      startHeight: element.offsetHeight,
    };
    document.addEventListener("mousemove", resizePane);
    document.addEventListener("mouseup", stopPaneResize, { once: true });
  }

  function resizePane(event: MouseEvent) {
    if (!resizeState) return;
    const minWidth = isEditorPaneId(resizeState.id) ? 440 : 240;
    const minHeight = isEditorPaneId(resizeState.id) ? 320 : 170;
    const width = Math.max(minWidth, resizeState.startWidth + event.clientX - resizeState.startX);
    const height = Math.max(minHeight, resizeState.startHeight + event.clientY - resizeState.startY);
    resizeState.element.style.width = `${width}px`;
    resizeState.element.style.height = `${height}px`;
    panes = {
      ...panes,
      [resizeState.id]: { ...panes[resizeState.id], width, height },
    };
  }

  function stopPaneResize() {
    resizeState = null;
    document.removeEventListener("mousemove", resizePane);
    document.removeEventListener("mouseup", stopPaneResize);
  }

  function handlePaneHeaderKeydown(event: KeyboardEvent, id: PaneId) {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    focusPane(id);
  }

  function handlePaneResizeKeydown(event: KeyboardEvent, id: PaneId) {
    const step = event.shiftKey ? 40 : 12;
    const pane = panes[id];
    let width = pane.width;
    let height = pane.height;
    if (event.key === "ArrowRight") width += step;
    else if (event.key === "ArrowLeft") width -= step;
    else if (event.key === "ArrowDown") height += step;
    else if (event.key === "ArrowUp") height -= step;
    else return;

    event.preventDefault();
    const minWidth = isEditorPaneId(id) ? 440 : 240;
    const minHeight = isEditorPaneId(id) ? 320 : 170;
    panes = {
      ...panes,
      [id]: { ...pane, width: Math.max(minWidth, width), height: Math.max(minHeight, height) },
    };
  }

  async function run(action: () => Promise<void>) {
    error = "";
    try {
      await action();
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  async function refreshStructure() {
    structure = await api.getStructure();
  }

  async function refreshLoreEntries() {
    loreEntries = (await api.listLoreEntries()).entries;
  }

  async function refreshPromptEntries() {
    promptEntries = (await api.listPromptEntries()).entries;
  }

  $: groupedAssistantEntries = groupAssistantEntriesByLayer(assistantEntries);

  // Drag-drop state for reordering assistants within a layer.
  let assistantDragId: string | null = null;
  let assistantDragLayerId: string | null = null;
  let assistantDropTarget: { id: string; position: "before" | "after" } | null = null;

  function startAssistantDrag(event: DragEvent, entry: AssistantEntrySummary) {
    if (!event.dataTransfer) return;
    assistantDragId = entry.id;
    assistantDragLayerId = entry.source_layer_id ?? "";
    event.dataTransfer.effectAllowed = "move";
    // Some browsers require setData to start a drag.
    event.dataTransfer.setData("text/plain", entry.id);
  }

  function onAssistantDragOver(event: DragEvent, entry: AssistantEntrySummary) {
    if (!assistantDragId || assistantDragLayerId !== (entry.source_layer_id ?? "")) return;
    if (entry.id === assistantDragId) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    const row = event.currentTarget as HTMLElement;
    const rect = row.getBoundingClientRect();
    const position = event.clientY < rect.top + rect.height / 2 ? "before" : "after";
    assistantDropTarget = { id: entry.id, position };
  }

  function onAssistantDragLeave() {
    assistantDropTarget = null;
  }

  function endAssistantDrag() {
    assistantDragId = null;
    assistantDragLayerId = null;
    assistantDropTarget = null;
  }

  async function onAssistantDrop(event: DragEvent, entry: AssistantEntrySummary) {
    event.preventDefault();
    if (!assistantDragId || assistantDragId === entry.id) {
      endAssistantDrag();
      return;
    }
    const layerId = entry.source_layer_id ?? "";
    if (assistantDragLayerId !== layerId) {
      endAssistantDrag();
      return;
    }
    const group = groupedAssistantEntries.find((g) => g.layerId === layerId);
    if (!group) {
      endAssistantDrag();
      return;
    }
    const draggedId = assistantDragId;
    const dropPosition = assistantDropTarget?.position ?? "after";
    const withoutDragged = group.entries.filter((e) => e.id !== draggedId);
    const targetIndex = withoutDragged.findIndex((e) => e.id === entry.id);
    if (targetIndex === -1) {
      endAssistantDrag();
      return;
    }
    const insertAt = dropPosition === "before" ? targetIndex : targetIndex + 1;
    const orderedIds = [
      ...withoutDragged.slice(0, insertAt).map((e) => e.id),
      draggedId,
      ...withoutDragged.slice(insertAt).map((e) => e.id),
    ];
    endAssistantDrag();
    await run(async () => {
      assistantEntries = (await api.reorderAssistants(layerId, orderedIds)).entries;
    });
  }

  function groupAssistantEntriesByLayer(entries: AssistantEntrySummary[]): { layerId: string; layerLabel: string; entries: AssistantEntrySummary[] }[] {
    const groups = new Map<string, { layerId: string; layerLabel: string; entries: AssistantEntrySummary[] }>();
    for (const entry of entries) {
      const key = entry.source_layer_id || "";
      const label = entry.source_layer_label || "Unknown";
      const existing = groups.get(key);
      if (existing) {
        existing.entries.push(entry);
      } else {
        groups.set(key, { layerId: key, layerLabel: label, entries: [entry] });
      }
    }
    // Machine layer first; then alphabetical by label.
    return Array.from(groups.values()).sort((a, b) => {
      if (a.layerLabel === "Machine") return -1;
      if (b.layerLabel === "Machine") return 1;
      return a.layerLabel.localeCompare(b.layerLabel);
    });
  }

  function assistantSubtitle(entry: AssistantEntrySummary): string {
    const provider = entry.metadata?.ai_provider;
    const model = entry.metadata?.ai_model;
    if (provider && model) return `${provider} · ${model}`;
    if (model) return String(model);
    if (provider) return String(provider);
    return "";
  }

  async function refreshAssistantEntries() {
    try {
      assistantEntries = (await api.listAssistantEntries()).entries;
    } catch {
      // Backend may be unavailable; leave previous list in place.
    }
  }

  async function refreshKnownTags() {
    knownTags = (await api.getKnownTags()).tags;
  }

  async function refreshTodos() {
    todos = (await api.getTodos()).items.filter((item) => !item.anchor_id);
  }

  async function refreshMetadataSchema() {
    metadataSchemaOverview = await api.getMetadataSchemaOverview();
    metadataSchema = metadataSchemaOverview.effective_schema;
    metadataSchemaLayers = metadataSchemaOverview.layers;
    if (!metadataSchema.entry_types[schemaFieldEntryType]) {
      schemaFieldEntryType = metadataSchema.entry_types.scene ? "scene" : Object.keys(metadataSchema.entry_types)[0] ?? "scene";
    }
    if (!schemaFieldLayerId || !metadataSchemaLayers.some((layer) => layer.id === schemaFieldLayerId)) {
      schemaFieldLayerId = projectSchemaLayerId();
    }
    if (!schemaTypeLayerId || !metadataSchemaLayers.some((layer) => layer.id === schemaTypeLayerId)) {
      schemaTypeLayerId = projectSchemaLayerId();
    }
  }

  async function openDirectoryPicker(event?: MouseEvent) {
    event?.preventDefault();
    event?.stopPropagation();
    directoryPickerOpen = true;
    await loadDirectory(projectPath.trim() || undefined);
  }

  async function loadDirectory(path?: string | null) {
    await run(async () => {
      directoryPickerLoading = true;
      try {
        directoryListing = await api.listDirectories(path ?? undefined);
      } finally {
        directoryPickerLoading = false;
      }
    });
  }

  function useDirectory(path: string) {
    const mode = directoryPickerMode;
    directoryPickerOpen = false;
    directoryPickerMode = null;
    if (mode === "openProject") {
      void openProjectAt(path);
    } else if (mode === "newProjectOverride") {
      newProjectOverridePath = path;
      newProjectOverrideFolder = true;
    } else {
      // Legacy fallback — preserved for any leftover callers.
      projectPath = path;
    }
  }

  function openDirectoryPickerForOpenProject() {
    directoryPickerMode = "openProject";
    void openDirectoryPicker();
  }

  function openDirectoryPickerForNewProjectOverride() {
    directoryPickerMode = "newProjectOverride";
    void openDirectoryPicker();
  }

  // ------ New Project modal -----------------------------------------------

  function openNewProjectModal() {
    newProjectName = "";
    newProjectOverrideFolder = false;
    newProjectOverridePath = "";
    newProjectModalOpen = true;
  }

  function closeNewProjectModal() {
    newProjectModalOpen = false;
  }

  // Slugify mirrors the Python slugifyFieldId convention used elsewhere —
  // lowercase, [a-z0-9-]+, no consecutive separators, no leading/trailing
  // dashes. Used to derive the project folder name from the title.
  function slugifyProjectName(name: string): string {
    const lowered = name.toLowerCase();
    const cleaned = lowered.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
    return cleaned || "new-project";
  }

  function joinPath(base: string, child: string): string {
    if (!base) return child;
    const sep = base.includes("\\") ? "\\" : "/";
    const trimmed = base.replace(/[/\\]+$/, "");
    return `${trimmed}${sep}${child}`;
  }

  $: newProjectResolvedPath = (() => {
    if (newProjectOverrideFolder && newProjectOverridePath) {
      return joinPath(newProjectOverridePath, slugifyProjectName(newProjectName));
    }
    return joinPath(defaultProjectsFolder, slugifyProjectName(newProjectName));
  })();

  async function confirmNewProject() {
    if (!newProjectName.trim()) {
      error = "Project name is required.";
      return;
    }
    const baseFolder = newProjectOverrideFolder && newProjectOverridePath
      ? newProjectOverridePath
      : defaultProjectsFolder;
    if (!baseFolder) {
      error = "No projects folder set. Open Settings to set a default.";
      return;
    }
    const path = joinPath(baseFolder, slugifyProjectName(newProjectName));
    closeNewProjectModal();
    await createProjectAt(path, newProjectName.trim(), baseFolder);
  }

  // Create a project at the given path with the given title. Optional
  // base folder lets callers override the default; omit to use the
  // project's parent folder (matches the backend's fallback).
  async function createProjectAt(path: string, title: string, baseFolder?: string) {
    await run(async () => {
      const openedProject = await api.createProject(path, title, baseFolder ?? "");
      openProjectWorkspace(openedProject);
      await refreshStructure();
      await refreshLoreEntries();
      await refreshPromptEntries();
      await refreshMetadataSchema();
      await refreshKnownTags();
      await refreshTodos();
      const initialSceneId = findFirstSceneId(structure?.root);
      if (initialSceneId) {
        await openSceneInEditorPane(initialSceneId);
      }
      await refreshRecents();
      status = `Created ${openedProject.title}`;
    });
  }

  async function openProjectAt(path: string) {
    await run(async () => {
      const openedProject = await api.openProject(path, "");
      openProjectWorkspace(openedProject);
      await refreshStructure();
      await refreshLoreEntries();
      await refreshPromptEntries();
      await refreshMetadataSchema();
      await refreshKnownTags();
      await refreshTodos();
      await refreshRecents();
      status = `Opened ${openedProject.title}`;
    });
  }

  async function updateProjectAISettings() {
    if (!isProjectOpen) return;
    await run(async () => {
      const updatedProject = await api.updateProjectSettings({
        ai_policy: aiPolicy,
        ai_default_provider: aiDefaultProvider || null,
        ai_default_model_class: aiDefaultModelClass || null,
      });
      appState = { name: "projectOpen", project: updatedProject };
      aiPolicy = updatedProject.ai_policy;
      aiDefaultProvider = updatedProject.ai_default_provider ?? "";
      aiDefaultModelClass = updatedProject.ai_default_model_class ?? "";
      status = "Updated AI settings";
    });
  }

  async function openMachineSettings() {
    await run(async () => {
      machineSettings = await api.getMachineSettings();
      machineSettingsDraft = {
        anthropic_api_key: machineSettings.providers.anthropic_api_key,
        openai_api_key: machineSettings.providers.openai_api_key,
        openrouter_api_key: machineSettings.providers.openrouter_api_key,
        ollama_host: machineSettings.providers.ollama_host,
        default_provider: machineSettings.default_provider,
        default_models: { ...machineSettings.default_models },
        default_projects_folder: machineSettings.default_projects_folder ?? "",
      };
      machineSettingsOpen = true;
    });
  }

  async function saveMachineSettings() {
    if (!machineSettings || !machineSettingsDraft) return;
    await run(async () => {
      const update: MachineSettingsUpdate = {
        providers: {
          anthropic_api_key: machineSettingsDraft!.anthropic_api_key,
          openai_api_key: machineSettingsDraft!.openai_api_key,
          openrouter_api_key: machineSettingsDraft!.openrouter_api_key,
          ollama_host: machineSettingsDraft!.ollama_host,
        },
        default_provider: machineSettingsDraft!.default_provider,
        default_models: machineSettingsDraft!.default_models,
        default_projects_folder: machineSettingsDraft!.default_projects_folder,
      };
      machineSettings = await api.updateMachineSettings(update);
      recentProjects = machineSettings.recent_projects ?? [];
      defaultProjectsFolder = machineSettings.default_projects_folder ?? "";
      machineSettingsOpen = false;
      status = "Saved machine settings";
    });
  }

  async function seedChatFromPromptEntry(
    entry: PromptEntrySummary,
    inputs: Record<string, unknown>,
    sceneId: string | null,
    assistantId: string = "",
  ) {
    if (!sceneId) {
      error = "Open a scene before invoking a chat prompt — context needs a target.";
      return;
    }
    await run(async () => {
      const preview = await api.aiPreview({
        template_source: entry.body_markdown,
        target_scene_id: sceneId,
        inputs,
        commit: false,
      });
      const messages = preview.messages ?? [];
      const flatten = (blocks: { text: string }[]) => blocks.map((b) => b.text).join("");
      const systemBlocks = messages.filter((m) => m.role === "system").map((m) => flatten(m.blocks));
      const turns = messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role as "user" | "assistant", content: flatten(m.blocks) }));

      chatSystemPrompt = systemBlocks.join("\n\n") || DEFAULT_CHAT_SYSTEM_PROMPT;
      chatHistory = turns;
      chatError = null;
      chatLastMeta = null;
      chatInput = "";
      chatActivePromptEntry = { id: entry.id, title: entry.title };
      // Carry the assistant pick from the inputs dialog into the chat panel
      // so the first (and subsequent) turns use it.
      chatAssistantId = assistantId;

      focusPane("chat");

      const lastTurn = turns[turns.length - 1];
      if (lastTurn?.role === "user") {
        await sendChatTurn();
      }
      status = `Loaded ${entry.title} into chat`;
    });
  }

  async function streamAssistantReply(onError: () => void): Promise<void> {
    // Appends an empty assistant message and mutates its content as deltas
    // arrive. On error, removes the placeholder and calls onError() so the
    // caller can decide whether to also rewind the user turn.
    const contextBlock = await composeContextBlocks();
    chatHistory = [...chatHistory, { role: "assistant", content: "" }];
    const idx = chatHistory.length - 1;
    let scrollPending = false;
    const scheduleScroll = async () => {
      if (scrollPending) return;
      scrollPending = true;
      await tick();
      scrollPending = false;
      if (chatScrollEl) chatScrollEl.scrollTop = chatScrollEl.scrollHeight;
    };
    let errored = false;
    for await (const ev of api.aiChatStream({
      assistant_id: chatAssistantId || null,
      system_prompt: buildEffectiveChatSystemPrompt(contextBlock),
      // Send history WITHOUT the placeholder we just pushed.
      messages: chatHistory.slice(0, idx).map(({ role, content }) => ({ role, content })),
    })) {
      if (ev.type === "delta") {
        chatHistory[idx].content += ev.text;
        chatHistory = chatHistory;
        scheduleScroll();
      } else if (ev.type === "thinking") {
        chatHistory[idx].thinking = (chatHistory[idx].thinking ?? "") + ev.text;
        chatHistory = chatHistory;
        scheduleScroll();
      } else if (ev.type === "done") {
        chatHistory[idx].truncated = ev.truncated;
        chatHistory = chatHistory;
        chatLastMeta = { provider: ev.provider, model: ev.model, latency_ms: ev.latency_ms };
      } else if (ev.type === "error") {
        errored = true;
        chatError = ev.error || "Unknown error";
        // Drop the empty assistant placeholder.
        chatHistory = chatHistory.slice(0, idx);
        onError();
      }
    }
    if (!errored && !chatHistory[idx]?.content && !chatHistory[idx]?.thinking) {
      // Stream ended without any deltas and without an error — treat as empty.
      chatHistory = chatHistory.slice(0, idx);
      chatError = "Model returned empty output.";
      onError();
    } else if (!errored) {
      // Persist the new turn — crash-safe so the user never loses a reply.
      void persistActiveChat();
    }
  }

  async function sendChatTurn() {
    if (chatRunning) return;
    chatRunning = true;
    chatError = null;
    try {
      await streamAssistantReply(() => {});
    } catch (e) {
      chatError = (e as Error).message;
    } finally {
      chatRunning = false;
      await tick();
      if (chatScrollEl) {
        chatScrollEl.scrollTop = chatScrollEl.scrollHeight;
      }
    }
  }

  async function sendChat() {
    if (chatRunning) return;
    const text = chatInput.trim();
    if (!text) return;
    chatError = null;
    const userTurn: ChatMessage = { role: "user", content: text };
    chatHistory = [...chatHistory, userTurn];
    const userIdx = chatHistory.length - 1;
    chatInput = "";
    chatRunning = true;
    const rewindUser = () => {
      // Drop the user turn at userIdx so they can fix and re-send.
      chatHistory = chatHistory.filter((_, i) => i !== userIdx);
      chatInput = text;
    };
    try {
      await streamAssistantReply(rewindUser);
    } catch (e) {
      chatError = (e as Error).message;
      rewindUser();
    } finally {
      chatRunning = false;
      await tick();
      if (chatScrollEl) {
        chatScrollEl.scrollTop = chatScrollEl.scrollHeight;
      }
    }
  }

  function handleChatInputKeydown(event: KeyboardEvent) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      sendChat();
    }
  }

  function clearChat() {
    chatHistory = [];
    chatLastMeta = null;
    chatError = null;
    chatActivePromptEntry = null;
    chatContextItems = [];
  }

  // --- Chat sessions (Phase 3) ---

  async function refreshChatSessions() {
    try {
      const listing = await api.listChatSessions();
      chatSessions = listing.sessions;
    } catch {
      chatSessions = [];
    }
  }

  function deriveChatTitleFromHistory(): string | null {
    const firstUser = chatHistory.find((m) => m.role === "user");
    if (!firstUser) return null;
    const text = firstUser.content.trim().replace(/\s+/g, " ");
    if (!text) return null;
    return text.length > 50 ? text.slice(0, 50).trim() + "…" : text;
  }

  function currentChatSessionPayload(): SaveChatSessionRequest {
    // Auto-title once: if the user hasn't renamed it and we have a user turn,
    // derive a title from the first user message so the Chats pane is scannable.
    let title = activeChatTitle || "Untitled chat";
    if (title === "Untitled chat") {
      const derived = deriveChatTitleFromHistory();
      if (derived) title = derived;
    }
    return {
      title,
      prompt_entry_id: chatPromptEntryId,
      assistant_id: chatAssistantId,
      system_prompt: chatSystemPrompt,
      pinned: activeChatPinned,
      context_items: chatContextItems.map((item) => ({
        kind: item.kind,
        id: item.id,
        entry_type: item.entryType,
        title: item.title,
      })),
      messages: chatHistory.map((m) => ({
        role: m.role,
        content: m.content,
        thinking: m.thinking ?? "",
        truncated: !!m.truncated,
      })),
    };
  }

  function applyChatSession(session: ChatSession) {
    activeChatId = session.id;
    activeChatTitle = session.title || "Untitled chat";
    activeChatPinned = session.pinned;
    chatPromptEntryId = session.prompt_entry_id || "";
    chatAssistantId = session.assistant_id || "";
    // Materialised brief from the session. When a prompt is locked in, this
    // came from the prompt's rendered system blocks (possibly empty). Don't
    // overlay DEFAULT_CHAT_SYSTEM_PROMPT here — for prompt-driven chats the
    // overlay would silently corrupt the locked system message; for freeform
    // chats with an empty system, an empty default is the honest answer.
    chatSystemPrompt = session.system_prompt || (session.prompt_entry_id ? "" : DEFAULT_CHAT_SYSTEM_PROMPT);
    invalidateChatPromptPreview();
    chatContextItems = (session.context_items || []).map((item: ChatSessionContextItem) => ({
      kind: item.kind,
      id: item.id,
      title: item.title || item.id,
      entryType: item.entry_type || "",
    }));
    chatHistory = (session.messages || []).map((m: ChatSessionMessage) => ({
      role: m.role,
      content: m.content,
      truncated: !!m.truncated,
      thinking: m.thinking || undefined,
    }));
    chatLastMeta = null;
    chatError = null;
    chatActivePromptEntry = null;
    chatInput = "";
  }

  async function persistActiveChat(): Promise<void> {
    if (!activeChatId) return;
    try {
      const saved = await api.saveChatSession(activeChatId, currentChatSessionPayload());
      activeChatTitle = saved.title;
      activeChatPinned = saved.pinned;
      void refreshChatSessions();
    } catch (e) {
      // Non-fatal; surface in chat error band so the user notices.
      chatError = `Couldn't save chat: ${(e as Error).message}`;
    }
  }

  async function openChatSession(chatId: string): Promise<void> {
    if (activeChatId === chatId) {
      focusPane("chat");
      return;
    }
    // Save current chat before switching so in-flight edits aren't lost.
    if (activeChatId) {
      await persistActiveChat();
    }
    try {
      const session = await api.getChatSession(chatId);
      applyChatSession(session);
      focusPane("chat");
    } catch (e) {
      error = `Couldn't open chat: ${(e as Error).message}`;
    }
  }

  async function createNewChatSession(opts: {
    promptEntryId?: string;
    assistantId?: string;
    systemPrompt?: string;
    title?: string;
  } = {}): Promise<void> {
    if (activeChatId) {
      await persistActiveChat();
    }
    try {
      const session = await api.createChatSession({
        prompt_entry_id: opts.promptEntryId ?? "",
        assistant_id: opts.assistantId ?? chatAssistantId,
        system_prompt: opts.systemPrompt ?? "",
        title: opts.title,
      });
      applyChatSession(session);
      await refreshChatSessions();
      focusPane("chat");
    } catch (e) {
      error = `Couldn't create chat: ${(e as Error).message}`;
    }
  }

  // --- Prompt picker (chat composer) ---

  function chatRoutedPromptEntries(): PromptEntrySummary[] {
    if (!metadataSchema) return [];
    return promptEntries.filter((entry) => {
      const def = metadataSchema?.entry_types[entry.entry_type];
      return def?.prompt?.context_strategy?.output?.kind === "chat_panel";
    });
  }

  function filteredChatPromptEntries(): PromptEntrySummary[] {
    const list = chatRoutedPromptEntries();
    const q = promptPickerSearch.trim().toLowerCase();
    if (!q) return list.slice().sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
    return list
      .filter((e) => e.title.toLowerCase().includes(q) || (e.entry_type || "").toLowerCase().includes(q))
      .sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
  }

  // Rebound on every change to chatPromptEntryId / promptEntries so Svelte's
  // template-side reactivity sees the dependency. A plain function would be
  // called once and never re-run when those reactive vars change.
  $: activePromptTitle = ((id: string, entries: PromptEntrySummary[]) => {
    if (!id) return "Freeform";
    return entries.find((p) => p.id === id)?.title || "Unknown prompt";
  })(chatPromptEntryId, promptEntries);

  function chatSessionPromptTitle(session: ChatSessionSummary): string {
    if (!session.prompt_entry_id) return "";
    const entry = promptEntries.find((p) => p.id === session.prompt_entry_id);
    return entry?.title || "Unknown prompt";
  }

  function preferredAssistantForPrompt(entry: PromptEntrySummary): string {
    const raw = (entry.metadata ?? {})["preferred_assistant_id"];
    return typeof raw === "string" ? raw : "";
  }

  function isActiveChatLocked(): boolean {
    return chatHistory.length > 0;
  }

  function toggleChatPromptPicker() {
    promptPickerOpen = !promptPickerOpen;
    promptPickerSearch = "";
    if (promptPickerOpen) {
      tick().then(() => {
        const input = document.querySelector<HTMLInputElement>(".chat-prompt-picker-search");
        input?.focus();
      });
    }
  }

  function closeChatPromptPicker() {
    promptPickerOpen = false;
    promptPickerSearch = "";
  }

  async function pickPromptForChat(entry: PromptEntrySummary): Promise<void> {
    closeChatPromptPicker();
    // If the prompt declares inputs, gather them in a modal before rendering
    // the template. Prompts with no declared inputs apply immediately.
    if ((entry.inputs ?? []).length > 0) {
      openChatInputsDialog(entry);
      return;
    }
    await applyChatPromptPreset(entry, {});
  }

  function openChatInputsDialog(entry: PromptEntrySummary) {
    const drafts: Record<string, string> = {};
    const prior = chatInputsLastUsed[entry.id] ?? {};
    for (const input of entry.inputs ?? []) {
      const previous = prior[input.name];
      if (previous !== undefined && previous !== null) {
        drafts[input.name] = previous;
      } else if (input.default !== undefined && input.default !== null) {
        drafts[input.name] = String(input.default);
      } else {
        drafts[input.name] = input.type === "boolean" ? "false" : "";
      }
    }
    chatInputsDialogDrafts = drafts;
    chatInputsDialogError = "";
    chatInputsDialogEntry = entry;
  }

  function cancelChatInputsDialog() {
    chatInputsDialogEntry = null;
    chatInputsDialogDrafts = {};
    chatInputsDialogError = "";
  }

  function updateChatInputsDraft(name: string, value: string) {
    chatInputsDialogDrafts = { ...chatInputsDialogDrafts, [name]: value };
  }

  function coerceChatInputValue(raw: string, type: PromptInputDefinition["type"]): unknown {
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

  async function submitChatInputsDialog() {
    const entry = chatInputsDialogEntry;
    if (!entry) return;
    const declared = entry.inputs ?? [];
    const missing = declared.filter((input) => {
      if (!input.required) return false;
      const raw = chatInputsDialogDrafts[input.name];
      if (input.type === "entity_ref_list") {
        try {
          const parsed = JSON.parse(raw || "[]");
          return !Array.isArray(parsed) || parsed.length === 0;
        } catch {
          return true;
        }
      }
      return !raw?.trim();
    });
    if (missing.length > 0) {
      chatInputsDialogError = `Missing required: ${missing.map((i) => i.label || i.name).join(", ")}.`;
      return;
    }
    const values: Record<string, unknown> = {};
    for (const input of declared) {
      const raw = chatInputsDialogDrafts[input.name] ?? "";
      const coerced = coerceChatInputValue(raw, input.type);
      if (coerced !== null && coerced !== "") values[input.name] = coerced;
    }
    // Remember for next time the user picks this prompt.
    chatInputsLastUsed = { ...chatInputsLastUsed, [entry.id]: { ...chatInputsDialogDrafts } };
    const target = entry;
    chatInputsDialogEntry = null;
    chatInputsDialogDrafts = {};
    chatInputsDialogError = "";
    await applyChatPromptPreset(target, values);
  }

  function handleChatInputsDialogKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      cancelChatInputsDialog();
    } else if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      void submitChatInputsDialog();
    }
  }

  async function applyChatPromptPreset(
    entry: PromptEntrySummary,
    inputs: Record<string, unknown>,
  ): Promise<void> {
    // Lock check: never replace the prompt of a chat with history. Start a new
    // chat instead. The backend would reject the save anyway — failing here is
    // a nicer UX.
    const mustCreateNew = !activeChatId || isActiveChatLocked();
    try {
      // Materialize the brief by rendering the template with the collected
      // inputs (empty object if the prompt declared none).
      const preview = await api.aiPreview({
        template_source: entry.body_markdown,
        target_scene_id: "",
        inputs,
        commit: false,
      });
      const messages = preview.messages ?? [];
      const flatten = (blocks: { text: string }[]) => blocks.map((b) => b.text).join("");
      const systemBlocks = messages.filter((m) => m.role === "system").map((m) => flatten(m.blocks));
      const initialTurns = messages
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({ role: m.role as "user" | "assistant", content: flatten(m.blocks) }));
      // Use the prompt's rendered system blocks verbatim. Critically, do NOT
      // fall back to DEFAULT_CHAT_SYSTEM_PROMPT here — that overlay used to
      // bleed the brainstorming-partner copy into every prompt that didn't
      // declare its own {% role "system" %}, conflicting with the prompt's
      // user-block instructions.
      const brief = systemBlocks.join("\n\n");
      const preferredAssistantId = preferredAssistantForPrompt(entry);

      invalidateChatPromptPreview();
      if (mustCreateNew) {
        // Auto-name the new chat with the prompt's title so it's scannable in
        // the Chats pane immediately.
        await createNewChatSession({
          promptEntryId: entry.id,
          assistantId: preferredAssistantId || chatAssistantId,
          systemPrompt: brief,
          title: entry.title,
        });
        if (initialTurns.length > 0) {
          chatHistory = initialTurns;
        }
        await persistActiveChat();
      } else {
        // Empty active chat — apply preset in-place.
        chatPromptEntryId = entry.id;
        chatSystemPrompt = brief;
        if (preferredAssistantId) chatAssistantId = preferredAssistantId;
        chatHistory = initialTurns;
        activeChatTitle = entry.title;
        await persistActiveChat();
      }
    } catch (e) {
      chatError = `Couldn't apply prompt: ${(e as Error).message}`;
    }
  }

  async function handlePromptPreviewToggle(event: Event): Promise<void> {
    const details = event.currentTarget as HTMLDetailsElement | null;
    if (!details?.open) return;
    // Cache miss → compose and store. Cache survives until something the
    // preview depends on changes (see invalidateChatPromptPreview).
    if (promptPreviewText !== null && !promptPreviewError) return;
    promptPreviewLoading = true;
    promptPreviewError = null;
    try {
      const contextBlock = await composeContextBlocks();
      promptPreviewText = buildEffectiveChatSystemPrompt(contextBlock);
    } catch (e) {
      promptPreviewError = (e as Error).message || "Couldn't compose preview.";
      promptPreviewText = null;
    } finally {
      promptPreviewLoading = false;
    }
  }

  function invalidateChatPromptPreview(): void {
    promptPreviewText = null;
    promptPreviewError = null;
  }

  function clearChatPrompt() {
    // Drop the locked prompt — only meaningful before any messages exist.
    if (isActiveChatLocked()) return;
    chatPromptEntryId = "";
    chatSystemPrompt = DEFAULT_CHAT_SYSTEM_PROMPT;
    activeChatTitle = "Untitled chat";
    invalidateChatPromptPreview();
    void persistActiveChat();
  }

  async function deleteChatSessionFromPane(chatId: string): Promise<void> {
    try {
      const listing = await api.deleteChatSession(chatId);
      chatSessions = listing.sessions;
      if (activeChatId === chatId) {
        activeChatId = null;
        activeChatTitle = "Untitled chat";
        activeChatPinned = false;
        chatPromptEntryId = "";
        clearChat();
        chatSystemPrompt = DEFAULT_CHAT_SYSTEM_PROMPT;
      }
    } catch (e) {
      error = `Couldn't delete chat: ${(e as Error).message}`;
    }
  }

  async function hydrateChatSessionsForProject(): Promise<void> {
    await refreshChatSessions();
    if (chatSessions.length === 0) {
      // Auto-create a first chat so the panel always has somewhere to write.
      try {
        const session = await api.createChatSession({});
        chatSessions = [{
          id: session.id,
          title: session.title,
          assistant_id: session.assistant_id,
          pinned: session.pinned,
          created_at: session.created_at,
          updated_at: session.updated_at,
          message_count: 0,
        }];
        applyChatSession(session);
      } catch {
        // Backend may be offline at boot — leave the chat panel in transient
        // mode; user can retry by clicking + New Chat.
      }
      return;
    }
    // Pick the most-recently-updated chat as the active session on open.
    const first = chatSessions[0];
    try {
      const session = await api.getChatSession(first.id);
      applyChatSession(session);
    } catch {
      // Ignore; user can pick manually from the Chats pane.
    }
  }

  function clearActivePromptOnEdit() {
    // If the user edits the system prompt, the active prompt indicator no longer
    // accurately reflects what's running. Drop it.
    chatActivePromptEntry = null;
  }

  function toggleContextMenu() {
    chatContextMenuOpen = !chatContextMenuOpen;
    chatContextCategory = null;
    chatContextSearch = "";
  }

  function openContextCategory(kind: ChatContextKind) {
    chatContextCategory = kind;
    chatContextSearch = "";
    tick().then(() => {
      const input = document.querySelector<HTMLInputElement>(".chat-context-search");
      input?.focus();
    });
  }

  function backToContextCategories() {
    chatContextCategory = null;
    chatContextSearch = "";
  }

  function addContextItem(item: ChatContextItem) {
    if (chatContextItems.some((existing) => existing.id === item.id && existing.kind === item.kind)) {
      chatContextMenuOpen = false;
      return;
    }
    chatContextItems = [...chatContextItems, item];
    chatContextMenuOpen = false;
    chatContextSearch = "";
    invalidateChatPromptPreview();
    void persistActiveChat();
  }

  function removeContextItem(id: string, kind: ChatContextKind) {
    chatContextItems = chatContextItems.filter((item) => !(item.id === id && item.kind === kind));
    invalidateChatPromptPreview();
    void persistActiveChat();
  }

  function handleChatAssistantChange() {
    void persistActiveChat();
  }

  function handleChatSystemPromptBlur() {
    invalidateChatPromptPreview();
    void persistActiveChat();
  }

  async function toggleActiveChatPin(): Promise<void> {
    if (!activeChatId) return;
    activeChatPinned = !activeChatPinned;
    await persistActiveChat();
  }

  async function togglePinForChat(chatId: string): Promise<void> {
    // Pin/unpin a chat from the Chats pane row (not necessarily the active one).
    if (chatId === activeChatId) {
      await toggleActiveChatPin();
      return;
    }
    // For other chats, read-then-save so we don't disturb panel state.
    try {
      const session = await api.getChatSession(chatId);
      await api.saveChatSession(chatId, {
        title: session.title,
        assistant_id: session.assistant_id,
        system_prompt: session.system_prompt,
        pinned: !session.pinned,
        context_items: session.context_items,
        messages: session.messages,
      });
      await refreshChatSessions();
    } catch (e) {
      error = `Couldn't update chat: ${(e as Error).message}`;
    }
  }

  async function renameActiveChat(): Promise<void> {
    if (!activeChatId) return;
    const proposed = window.prompt("Rename chat", activeChatTitle);
    if (proposed === null) return;
    const trimmed = proposed.trim();
    if (!trimmed || trimmed === activeChatTitle) return;
    activeChatTitle = trimmed;
    await persistActiveChat();
  }

  function titleMatchesQuery(title: string, query: string): boolean {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return title.toLowerCase().includes(q);
  }

  function snippetEntriesFor(query: string): PromptEntrySummary[] {
    const schema = metadataSchema;
    if (!schema) return [];
    const isSnippetType = (typeId: string | undefined | null): boolean => {
      if (!typeId) return false;
      const seen = new Set<string>();
      let current: string | undefined = typeId;
      while (current && !seen.has(current)) {
        if (current === "snippet") return true;
        seen.add(current);
        current = schema.entry_types[current]?.parent ?? undefined;
      }
      return false;
    };
    return promptEntries
      .filter((entry) => isSnippetType(entry.entry_type) && titleMatchesQuery(entry.title, query))
      .sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: "base" }));
  }

  function filteredStructureScenes(root: StructureNode | null | undefined, query: string): { id: string; title: string }[] {
    return flattenStructureScenes(root).filter((s) => titleMatchesQuery(s.title, query));
  }

  function loreEntriesGroupedByType(query: string): { typeId: string; typeName: string; entries: LoreEntrySummary[] }[] {
    const groups = new Map<string, { typeId: string; typeName: string; entries: LoreEntrySummary[] }>();
    for (const entry of loreEntries) {
      if (!titleMatchesQuery(entry.title, query)) continue;
      const key = entry.entry_type || "lore_note";
      const existing = groups.get(key);
      if (existing) {
        existing.entries.push(entry);
      } else {
        groups.set(key, {
          typeId: key,
          typeName: loreEntryTypeName(entry),
          entries: [entry],
        });
      }
    }
    return Array.from(groups.values()).sort((a, b) => a.typeName.localeCompare(b.typeName, undefined, { sensitivity: "base" }));
  }

  function escapeXmlAttr(value: string): string {
    return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  async function composeContextBlocks(): Promise<string> {
    if (chatContextItems.length === 0) return "";
    const blocks: string[] = [];
    for (const item of chatContextItems) {
      try {
        if (item.kind === "scene") {
          const scene = await api.getScene(item.id);
          blocks.push(
            `<scene title="${escapeXmlAttr(scene.title)}" id="${escapeXmlAttr(scene.id)}">\n${scene.body_markdown.trim()}\n</scene>`,
          );
        } else if (item.kind === "lore") {
          const entry = await api.getLoreEntry(item.id);
          blocks.push(
            `<lore_entry entry_type="${escapeXmlAttr(entry.entry_type)}" title="${escapeXmlAttr(entry.title)}" id="${escapeXmlAttr(entry.id)}">\n${entry.body_markdown.trim()}\n</lore_entry>`,
          );
        } else if (item.kind === "preset") {
          const preset = await api.aiContextPreset(item.id as "full_outline" | "full_text");
          if (preset.content.trim()) {
            blocks.push(preset.content);
          }
        } else {
          const entry = await api.getPromptEntry(item.id);
          blocks.push(
            `<snippet title="${escapeXmlAttr(entry.title)}" id="${escapeXmlAttr(entry.id)}">\n${entry.body_markdown.trim()}\n</snippet>`,
          );
        }
      } catch {
        // Skip items we can't fetch (e.g., deleted entry).
      }
    }
    return blocks.length ? `<context>\n${blocks.join("\n\n")}\n</context>` : "";
  }

  function buildEffectiveChatSystemPrompt(contextBlock: string): string {
    const trimmed = chatSystemPrompt.trim();
    if (!contextBlock) return chatSystemPrompt;
    if (!trimmed) return contextBlock;
    return `${chatSystemPrompt}\n\n${contextBlock}`;
  }

  function flattenStructureScenes(node: StructureNode | null | undefined, acc: { id: string; title: string }[] = []): { id: string; title: string }[] {
    if (!node) return acc;
    if (node.scene_id && isLeafNode(node)) {
      acc.push({ id: node.scene_id, title: node.title });
    }
    for (const child of node.children ?? []) {
      flattenStructureScenes(child, acc);
    }
    return acc;
  }

  async function runAIHealthCheck() {
    await run(async () => {
      aiHealthChecking = true;
      try {
        aiHealthResult = await api.aiHealth(aiDefaultProvider || undefined);
      } finally {
        aiHealthChecking = false;
      }
    });
  }

  function projectSchemaLayerId() {
    return metadataSchemaLayers[metadataSchemaLayers.length - 1]?.id ?? "";
  }

  function layerLabel(layerId: string | undefined | null) {
    if (!layerId) return "Unknown";
    if (layerId === "built_in") return "Built-in";
    return metadataSchemaLayers.find((layer) => layer.id === layerId)?.label ?? "Unknown";
  }

  function assistantNameFor(assistantId: string): string {
    if (!assistantId) return "";
    return assistantEntries.find((a) => a.id === assistantId)?.title ?? "";
  }

  function defaultAssistantEntryId(): string {
    return assistantEntries.find((a) => Boolean(a.metadata?.is_default))?.id ?? "";
  }

  function paneEntryFromAncestor(pane: EditorPaneState): boolean {
    const layerId = pane.scene?.source_layer_id;
    if (!layerId) return false;
    const projectLayer = projectSchemaLayerId();
    if (!projectLayer) return false;
    return layerId !== projectLayer;
  }

  function fieldEntriesForEntryType(entryTypeId: string) {
    const entryType = metadataSchema?.entry_types[entryTypeId];
    const fieldIds = entryType?.own_fields ?? entryType?.fields ?? [];
    return fieldIds
      .map((fieldId) => {
        const field = metadataSchema?.fields[fieldId];
        return field ? ([fieldId, field] as [string, MetadataFieldDefinition]) : null;
      })
      .filter((entry): entry is [string, MetadataFieldDefinition] => Boolean(entry));
  }

  function fieldAppliesToEntryType(fieldId: string, entryTypeId: string) {
    return Boolean(metadataSchema?.entry_types[entryTypeId]?.fields.includes(fieldId));
  }

  function toggleSchemaFieldsForType(entryTypeId: string) {
    const fieldsCollapsed = collapsedSchemaFieldsByType[entryTypeId] ?? true;
    collapsedSchemaFieldsByType = {
      ...collapsedSchemaFieldsByType,
      [entryTypeId]: !fieldsCollapsed,
    };
  }

  function buildNodeTypeOptions(schema: MetadataSchema | null): NodeTypeOption[] {
    const entryTypes = schema?.entry_types ?? {};
    const childrenByParent: Record<string, string[]> = {};
    const roots: string[] = [];
    for (const [typeId, definition] of Object.entries(entryTypes)) {
      const parent = definition.parent;
      if (parent && entryTypes[parent]) {
        childrenByParent[parent] = [...(childrenByParent[parent] ?? []), typeId];
      } else {
        roots.push(typeId);
      }
    }
    const compareByName = (left: string, right: string) => nodeTypeDisplayName(left, entryTypes[left]).localeCompare(nodeTypeDisplayName(right, entryTypes[right]));
    roots.sort((left, right) => {
      if (left === "scene") return -1;
      if (right === "scene") return 1;
      if (left === "lore_entry") return -1;
      if (right === "lore_entry") return 1;
      return compareByName(left, right);
    });
    for (const children of Object.values(childrenByParent)) {
      children.sort(compareByName);
    }

    const options: NodeTypeOption[] = [];
    const append = (typeId: string, depth: number) => {
      const definition = entryTypes[typeId];
      if (!definition) return;
      options.push({
        id: typeId,
        label: nodeTypeDisplayName(typeId, definition),
        depth,
        definition,
      });
      for (const childId of childrenByParent[typeId] ?? []) {
        append(childId, depth + 1);
      }
    };
    for (const rootId of roots) {
      append(rootId, 0);
    }
    return options;
  }

  function buildNodeTypeTree(schema: MetadataSchema | null, kind: "scene" | "lore" | "prompt" | "assistant" | "project"): NodeTypeTreeNode[] {
    const entryTypes = schema?.entry_types ?? {};
    const childrenByParent: Record<string, string[]> = {};
    const roots: string[] = [];
    for (const [typeId, definition] of Object.entries(entryTypes)) {
      if (definition.kind !== kind) continue;
      const parent = definition.parent;
      if (parent && entryTypes[parent]?.kind === kind) {
        childrenByParent[parent] = [...(childrenByParent[parent] ?? []), typeId];
      } else {
        roots.push(typeId);
      }
    }
    const compareByName = (left: string, right: string) => nodeTypeDisplayName(left, entryTypes[left]).localeCompare(nodeTypeDisplayName(right, entryTypes[right]));
    for (const children of Object.values(childrenByParent)) {
      children.sort(compareByName);
    }
    const rootIds =
      kind === "lore" && entryTypes.lore_entry
        ? ["lore_entry"]
        : kind === "prompt" && entryTypes.prompt
          ? ["prompt"]
          : roots.sort(compareByName);
    const buildNode = (typeId: string, depth: number): NodeTypeTreeNode | null => {
      const definition = entryTypes[typeId];
      if (!definition || definition.kind !== kind) return null;
      const children = (childrenByParent[typeId] ?? [])
        .map((childId) => buildNode(childId, depth + 1))
        .filter((child): child is NodeTypeTreeNode => Boolean(child));
      return {
        id: typeId,
        label: nodeTypeDisplayName(typeId, definition),
        depth,
        definition,
        children,
      };
    };
    return rootIds.map((typeId) => buildNode(typeId, 0)).filter((node): node is NodeTypeTreeNode => Boolean(node));
  }

  function nodeTypeDisplayName(typeId: string, definition: EntryTypeDefinition | undefined) {
    if (typeId === "scene") return "Scenes";
    if (typeId === "lore_entry") return "Lore Entries";
    if (typeId === "prompt") return "Prompts";
    return definition?.name ?? typeId;
  }

  function schemaTypeSource(typeId: string | null) {
    return typeId ? metadataSchemaOverview?.entry_type_sources[typeId] : null;
  }

  function sourceLayerIndex(source: { layer_id: string; built_in: boolean } | undefined | null) {
    if (!source || source.built_in) return 0;
    return Math.max(0, metadataSchemaLayers.findIndex((layer) => layer.id === source.layer_id) + 1);
  }

  function sourceBadgeLabel(source: { layer_label: string; built_in: boolean } | undefined | null) {
    return source?.built_in ? "System" : (source?.layer_label ?? "Unknown");
  }

  function fieldTypeLabel(type: MetadataFieldType) {
    const labels: Record<MetadataFieldType, string> = {
      text: "Text",
      long_text: "Long Text",
      number: "Number",
      boolean: "Checkbox",
      date: "Date",
      select: "Select",
      multi_select: "List",
      entity_ref: "Entry Reference",
      entity_ref_list: "Entry Reference, Multiple",
      tags: "Tags",
      computed: "Computed",
    };
    return labels[type] ?? type;
  }

  function openSchemaFieldDetail(fieldId: string, entryTypeId = schemaFieldEntryType) {
    const field = metadataSchema?.fields[fieldId];
    if (!field) return;
    const targetEntryTypeId = fieldAppliesToEntryType(fieldId, entryTypeId)
      ? entryTypeId
      : (entryTypeIdsForField(fieldId, schemaFieldKind)[0] ?? defaultSchemaEntryType(schemaFieldKind));
    selectedSchemaFieldId = fieldId;
    schemaFieldId = fieldId;
    schemaFieldName = field.name;
    schemaFieldReadonly = Boolean(metadataSchemaOverview?.field_sources[fieldId]?.built_in);
    schemaFieldReadonlyTypeLabel = "";
    schemaFieldAllowMultiple = field.type === "multi_select" || field.type === "entity_ref_list";
    schemaFieldReferenceEntryType = field.target?.entry_type ?? "";
    schemaFieldReferenceTarget = resolveReferenceKind(field.target, schemaFieldReferenceEntryType);
    schemaFieldType = schemaFieldReadonly
      ? field.type
      : field.type === "multi_select"
        ? "select"
        : field.type === "entity_ref_list"
          ? "entity_ref"
          : field.type === "computed"
            ? "text"
            : field.type;
    schemaFieldOptions = field.options.join(", ");
    schemaFieldLayerId = metadataSchemaOverview?.field_sources[fieldId]?.built_in ? projectSchemaLayerId() : (metadataSchemaOverview?.field_sources[fieldId]?.layer_id ?? projectSchemaLayerId());
    schemaFieldEntryType = targetEntryTypeId;
    schemaFieldPaneOpen = true;
    focusPane("schema_field");
  }

  function createSchemaFieldDraft(layerId = projectSchemaLayerId(), entryTypeId = schemaFieldEntryType) {
    selectedSchemaFieldId = null;
    schemaFieldId = "";
    schemaFieldName = "";
    schemaFieldType = "text";
    schemaFieldReadonly = false;
    schemaFieldReadonlyTypeLabel = "";
    schemaFieldAllowMultiple = false;
    schemaFieldReferenceTarget = "lore";
    schemaFieldReferenceEntryType = "";
    schemaFieldOptions = "";
    schemaFieldLayerId = layerId;
    schemaFieldEntryType = entryTypeId;
    schemaFieldPaneOpen = true;
    focusPane("schema_field");
  }

  function resolveReferenceKind(target: Record<string, string> | null | undefined, entryTypeId: string): "scene" | "lore" {
    if (target?.kind === "scene") return "scene";
    if (target?.kind === "lore") return "lore";
    if (entryTypeId) {
      const definition = metadataSchema?.entry_types[entryTypeId];
      if (definition?.kind === "scene") return "scene";
    }
    return "lore";
  }

  function createSchemaTypeDraft(layerId = projectSchemaLayerId(), parentTypeId = "") {
    selectedSchemaTypeId = null;
    schemaTypeId = "";
    schemaTypeName = "";
    const parentType = parentTypeId ? metadataSchema?.entry_types[parentTypeId] : null;
    schemaTypeKind =
      parentType?.kind === "scene"
        ? "scene"
        : parentType?.kind === "lore"
          ? "lore"
          : parentType?.kind === "prompt"
            ? "prompt"
            : parentType?.kind === "assistant"
              ? "assistant"
              : schemaFieldKind;
    schemaTypeParent = parentTypeId || (schemaSelectedEntryType?.abstract || schemaFieldEntryType !== "scene" ? schemaFieldEntryType : defaultSchemaParentType(schemaFieldKind));
    schemaTypeAbstract = false;
    schemaTypeReadonly = false;
    schemaTypeLayerId = layerId;
    resetPromptExtrasForm();
    schemaTypePaneOpen = true;
    focusPane("schema_type");
  }

  function resetPromptExtrasForm() {
    promptSystemPrompt = "";
    promptModelClass = "";
    promptProviderPolicy = "";
    promptContextTargetKind = "";
    promptContextTargetRequired = false;
    promptScanSurface = "";
    promptOutputKind = "";
    promptOutputReview = "";
  }

  function loadPromptExtrasFromEntryType(entryType: EntryTypeDefinition | undefined | null) {
    const extras = entryType?.prompt ?? null;
    promptSystemPrompt = extras?.system_prompt ?? "";
    promptModelClass = extras?.model_class ?? "";
    promptProviderPolicy = extras?.provider_policy ?? "";
    const contextStrategy = extras?.context_strategy ?? null;
    promptContextTargetKind =
      typeof contextStrategy?.target?.kind === "string" ? (contextStrategy.target.kind as string) : "";
    promptContextTargetRequired = Boolean(contextStrategy?.target?.required);
    promptScanSurface = (contextStrategy?.scan_surface ?? []).join(", ");
    promptOutputKind =
      typeof contextStrategy?.output?.kind === "string" ? (contextStrategy.output.kind as string) : "";
    promptOutputReview =
      typeof contextStrategy?.output?.review === "string" ? (contextStrategy.output.review as string) : "";
  }

  function openSchemaTypeDetail(typeId: string) {
    const entryType = metadataSchema?.entry_types[typeId];
    if (!entryType) return;
    const source = schemaTypeSource(typeId);
    selectedSchemaTypeId = typeId;
    schemaTypeId = typeId;
    schemaTypeName = entryType.name;
    schemaTypeKind =
      entryType.kind === "scene"
        ? "scene"
        : entryType.kind === "prompt"
          ? "prompt"
          : entryType.kind === "assistant"
            ? "assistant"
            : "lore";
    schemaTypeParent = entryType.parent ?? "";
    schemaTypeAbstract = Boolean(entryType.abstract);
    schemaTypeReadonly = Boolean(source?.built_in);
    schemaTypeLayerId = source?.built_in ? projectSchemaLayerId() : (source?.layer_id ?? projectSchemaLayerId());
    loadPromptExtrasFromEntryType(entryType);
    schemaTypePaneOpen = true;
    focusPane("schema_type");
  }

  function updateSchemaTypeName(value: string) {
    schemaTypeName = value;
    if (!schemaTypeReadonly) {
      schemaTypeId = slugifyFieldId(value);
    }
  }

  function defaultSchemaParentType(kind: "scene" | "lore" | "prompt" | "assistant" | "project") {
    if (kind === "lore" && metadataSchema?.entry_types.lore_entry) return "lore_entry";
    if (kind === "prompt" && metadataSchema?.entry_types.prompt) return "prompt";
    return "";
  }

  function openSchemaForCustomData(entryType: string, kind: "scene" | "lore" | "prompt" | "assistant" | "project") {
    // Phase B: the entry editor's "Edit type…" button now opens ONLY the
    // per-type editor (schema_type pane) — not the schema/tree hierarchy
    // view. Tree access is the top bar's "Detail Types" button.
    const candidate = metadataSchema?.entry_types[entryType];
    const resolvedTypeId = candidate?.kind === kind ? entryType : defaultSchemaEntryType(kind);
    schemaFieldEntryType = resolvedTypeId;
    if (resolvedTypeId && metadataSchema?.entry_types[resolvedTypeId]) {
      openSchemaTypeDetail(resolvedTypeId);
    } else {
      // No matching type — fall back to opening the tree so the user can
      // pick or create one. Rare edge case for new projects.
      schemaPaneOpen = true;
      focusPane("schema");
    }
  }

  // Top-bar entry point: opens the schema/tree pane (the canonical
  // hierarchy editor). The per-type editor opened from individual entries
  // goes via openSchemaTypeDetail instead — see Phase B's split.
  function openDetailTypesPane() {
    if (!isProjectOpen) return;
    schemaPaneOpen = true;
    focusPane("schema");
  }

  // Switches the tree's scope. schemaFieldKind is derived from
  // schemaFieldEntryType via a $: expression — to switch kinds we set
  // entryType to a default of the target kind. The cascade updates
  // schemaContextHeading and schemaNodeTypeTree on the next tick.
  function switchSchemaKind(kind: "scene" | "lore" | "prompt" | "assistant" | "project") {
    schemaFieldEntryType = defaultSchemaEntryType(kind);
  }

  function defaultSchemaEntryType(kind: "scene" | "lore" | "prompt" | "assistant" | "project") {
    const fallback = kind === "lore" ? "lore_note" : kind === "prompt" ? "prompt" : kind === "assistant" ? "assistant" : kind === "project" ? "project" : "scene";
    return Object.entries(metadataSchema?.entry_types ?? {}).find(([, definition]) => definition.kind === kind)?.[0] ?? fallback;
  }

  function entryTypeIdsForField(fieldId: string, kind: "scene" | "lore" | "prompt" | "assistant" | "project") {
    return Object.entries(metadataSchema?.entry_types ?? {})
      .filter(([, definition]) => definition.kind === kind && definition.fields.includes(fieldId))
      .map(([typeId]) => typeId);
  }

  function closeSchemaPane(id: "schema" | "schema_field" | "schema_type" | "prompts" | "assistants" | "chats") {
    if (id === "schema") schemaPaneOpen = false;
    else if (id === "schema_field") schemaFieldPaneOpen = false;
    else if (id === "schema_type") schemaTypePaneOpen = false;
    else if (id === "prompts") promptsPaneOpen = false;
    else if (id === "assistants") assistantsPaneOpen = false;
    else if (id === "chats") chatsPaneOpen = false;
  }

  function openPromptsPane() {
    promptsPaneOpen = true;
    focusPane("prompts");
  }

  function openAssistantsPane() {
    assistantsPaneOpen = true;
    void refreshAssistantEntries();
    focusPane("assistants");
  }

  function openChatsPane() {
    chatsPaneOpen = true;
    void refreshChatSessions();
    focusPane("chats");
  }

  function buildPromptExtras(): PromptEntryTypeExtras | null {
    const scanSurface = promptScanSurface
      .split(",")
      .map((token) => token.trim())
      .filter(Boolean);
    const hasTarget = Boolean(promptContextTargetKind) || promptContextTargetRequired;
    const hasOutput = Boolean(promptOutputKind) || Boolean(promptOutputReview);
    const contextStrategy: PromptContextStrategy | null = scanSurface.length || hasTarget || hasOutput
      ? {
          ...(hasTarget
            ? {
                target: {
                  ...(promptContextTargetRequired ? { required: true } : {}),
                  ...(promptContextTargetKind ? { kind: promptContextTargetKind } : {}),
                },
              }
            : {}),
          ...(scanSurface.length ? { scan_surface: scanSurface } : {}),
          ...(hasOutput
            ? {
                output: {
                  ...(promptOutputKind ? { kind: promptOutputKind } : {}),
                  ...(promptOutputReview ? { review: promptOutputReview } : {}),
                },
              }
            : {}),
        }
      : null;

    const extras: PromptEntryTypeExtras = {
      ...(promptSystemPrompt.trim() ? { system_prompt: promptSystemPrompt } : {}),
      ...(promptModelClass.trim() ? { model_class: promptModelClass.trim() } : {}),
      ...(promptProviderPolicy ? { provider_policy: promptProviderPolicy } : {}),
      ...(contextStrategy ? { context_strategy: contextStrategy } : {}),
    };
    return Object.keys(extras).length ? extras : null;
  }

  function startSchemaTypeDrag(typeId: string) {
    draggedSchemaTypeId = typeId;
  }

  async function dropSchemaTypeOnParent(parentTypeId: string) {
    const typeId = draggedSchemaTypeId;
    draggedSchemaTypeId = null;
    if (!typeId || typeId === parentTypeId) return;
    const entryType = metadataSchema?.entry_types[typeId];
    const parentType = metadataSchema?.entry_types[parentTypeId];
    if (!entryType || !parentType || entryType.kind !== parentType.kind) return;
    const source = schemaTypeSource(typeId);
    if (!source || source.built_in) {
      status = "System detail types cannot be moved";
      return;
    }
    await run(async () => {
      metadataSchema = await api.upsertMetadataEntryType(
        source.layer_id,
        typeId,
        {
          ...entryType,
          parent: parentTypeId,
        },
        true,
      );
      await refreshMetadataSchema();
      validation = await api.validateProject();
      selectedSchemaTypeId = typeId;
      status = `Moved ${entryType.name} under ${parentType.name}`;
    });
  }

  function schemaFieldSaveType(): MetadataFieldType {
    if (schemaFieldType === "select" && schemaFieldAllowMultiple) return "multi_select";
    if (schemaFieldType === "entity_ref" && schemaFieldAllowMultiple) return "entity_ref_list";
    return schemaFieldType;
  }

  function updateSchemaFieldName(value: string) {
    schemaFieldName = value;
    if (!schemaFieldReadonly) {
      schemaFieldId = slugifyFieldId(value);
    }
  }

  function slugifyFieldId(value: string) {
    return value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^[0-9]/, "field_$&");
  }

  async function saveSchemaField() {
    if (!schemaFieldLayerId) return;
    await run(async () => {
      const previousFieldId = selectedSchemaFieldId && !selectedSchemaFieldId.startsWith("system:") ? selectedSchemaFieldId : null;
      const nextFieldId = schemaFieldId.trim();
      const previousField = previousFieldId ? metadataSchema?.fields[previousFieldId] : null;
      const options = schemaFieldOptions
        .split(",")
        .map((option) => option.trim())
        .filter(Boolean);
      const nextField: MetadataFieldDefinition = {
        name: schemaFieldName.trim() || nextFieldId,
        type: schemaFieldSaveType(),
        options: schemaFieldType === "select" ? options : [],
        ...(schemaFieldType === "entity_ref"
          ? {
              target: schemaFieldReferenceEntryType
                ? { entry_type: schemaFieldReferenceEntryType }
                : { kind: schemaFieldReferenceTarget },
            }
          : {}),
      };
      const optionMigration = buildOptionMigration(previousField, nextField);
      if (previousFieldId && previousFieldId !== nextFieldId) {
        await api.renameMetadataField(previousFieldId, nextFieldId, schemaFieldEntryType);
      }
      metadataSchema = await api.upsertMetadataField(schemaFieldLayerId, nextFieldId, nextField, schemaFieldEntryType, Boolean(previousFieldId));
      await refreshMetadataSchema();
      if (previousFieldId) {
        const renamedField = previousFieldId !== nextFieldId;
        await refreshOpenEditorPaneBaselines((metadata) => {
          const renamedMetadata = renamedField ? renameMetadataKey(metadata, previousFieldId, nextFieldId) : metadata;
          return migrateMetadataOptionValues(renamedMetadata, nextFieldId, optionMigration);
        });
      }
      validation = await api.validateProject();
      selectedSchemaFieldId = nextFieldId;
      status = "Updated details schema";
    });
  }

  async function saveSchemaType() {
    if (!schemaTypeLayerId) return;
    await run(async () => {
      const previousTypeId = selectedSchemaTypeId && !schemaTypeReadonly ? selectedSchemaTypeId : null;
      const nextTypeId = schemaTypeId.trim();
      const existing = previousTypeId ? metadataSchema?.entry_types[previousTypeId] : null;
      const promptExtras = schemaTypeKind === "prompt" ? buildPromptExtras() : null;
      const nextType: EntryTypeDefinition = {
        name: schemaTypeName.trim() || nextTypeId,
        kind: schemaTypeKind,
        parent: schemaTypeParent || null,
        abstract: schemaTypeAbstract,
        fields: previousTypeId ? (existing?.own_fields ?? existing?.fields ?? []) : [],
        ...(schemaTypeKind === "prompt" ? { prompt: promptExtras } : {}),
      };
      if (previousTypeId && previousTypeId !== nextTypeId) {
        status = "Renaming detail types is not available yet";
        return;
      }
      metadataSchema = await api.upsertMetadataEntryType(schemaTypeLayerId, nextTypeId, nextType, Boolean(previousTypeId));
      await refreshMetadataSchema();
      validation = await api.validateProject();
      selectedSchemaTypeId = nextTypeId;
      schemaFieldEntryType = nextTypeId;
      status = "Updated detail type";
    });
  }

  function requestDeleteSchemaType() {
    if (!selectedSchemaTypeId || schemaTypeReadonly) return;
    const typeName = schemaTypeName || selectedSchemaTypeId;
    confirmation = {
      title: "Delete Detail Type",
      message: `Delete "${typeName}"? Existing documents using this type must be changed first.`,
      confirmLabel: "Delete Type",
      destructive: true,
      onConfirm: () => deleteSchemaType(selectedSchemaTypeId!),
    };
  }

  async function deleteSchemaType(typeId: string) {
    const deletedKind = schemaFieldKind;
    metadataSchema = await api.deleteMetadataEntryType(typeId);
    await refreshMetadataSchema();
    validation = await api.validateProject();
    selectedSchemaTypeId = null;
    schemaTypePaneOpen = false;
    if (schemaFieldEntryType === typeId || !metadataSchema?.entry_types[schemaFieldEntryType]) {
      schemaFieldEntryType = defaultSchemaEntryType(deletedKind);
    }
    status = `Deleted ${typeId}`;
  }

  function requestDeleteSchemaField() {
    if (!selectedSchemaFieldId || selectedSchemaFieldId.startsWith("system:") || schemaFieldReadonly) return;
    const fieldName = schemaFieldName || selectedSchemaFieldId;
    confirmation = {
      title: "Delete Detail Field",
      message: `Delete "${fieldName}"? This removes the field definition and removes that metadata value from scenes.`,
      confirmLabel: "Delete Field",
      destructive: true,
      onConfirm: () => deleteSchemaField(selectedSchemaFieldId!),
    };
  }

  async function deleteSchemaField(fieldId: string) {
    metadataSchema = await api.deleteMetadataField(fieldId, schemaFieldEntryType);
    await refreshMetadataSchema();
    await refreshOpenEditorPaneBaselines((metadata) => removeMetadataKey(metadata, fieldId));
    validation = await api.validateProject();
    selectedSchemaFieldId = null;
    schemaFieldPaneOpen = false;
    status = `Deleted ${fieldId}`;
  }

  function renameMetadataKey(metadata: EntryMetadata, oldFieldId: string, newFieldId: string) {
    if (!(oldFieldId in metadata)) return metadata;
    const nextMetadata = cloneMetadata(metadata);
    if (!(newFieldId in nextMetadata)) {
      nextMetadata[newFieldId] = nextMetadata[oldFieldId];
    }
    delete nextMetadata[oldFieldId];
    return nextMetadata;
  }

  function removeMetadataKey(metadata: EntryMetadata, fieldId: string) {
    if (!(fieldId in metadata)) return metadata;
    const nextMetadata = cloneMetadata(metadata);
    delete nextMetadata[fieldId];
    return nextMetadata;
  }

  function buildOptionMigration(previousField: MetadataFieldDefinition | null | undefined, nextField: MetadataFieldDefinition) {
    const optionTypes = new Set<MetadataFieldType>(["select", "multi_select", "tags"]);
    if (!previousField || !optionTypes.has(previousField.type) || !optionTypes.has(nextField.type)) return null;
    if (!previousField.options.length || previousField.options.length !== nextField.options.length) return null;
    const migration: Record<string, string> = {};
    previousField.options.forEach((previousOption, index) => {
      const nextOption = nextField.options[index];
      if (previousOption !== nextOption) {
        migration[previousOption] = nextOption;
      }
    });
    return Object.keys(migration).length > 0 ? migration : null;
  }

  function migrateMetadataOptionValues(metadata: EntryMetadata, fieldId: string, migration: Record<string, string> | null) {
    if (!migration || !(fieldId in metadata)) return metadata;
    const value = metadata[fieldId];
    const nextMetadata = cloneMetadata(metadata);
    if (typeof value === "string") {
      nextMetadata[fieldId] = migration[value] ?? value;
    } else if (Array.isArray(value)) {
      nextMetadata[fieldId] = value.map((item) => (typeof item === "string" ? migration[item] ?? item : item));
    }
    return nextMetadata;
  }

  function findFirstSceneId(node: StructureNode | null | undefined): string | null {
    if (!node) return null;
    if (node.scene_id && isLeafNode(node)) return node.scene_id;
    for (const child of node.children ?? []) {
      const sceneId = findFirstSceneId(child);
      if (sceneId) return sceneId;
    }
    return null;
  }

  async function newScene(parentId?: string) {
    await run(async () => {
      const scene = await api.createScene("New Scene", parentId);
      await refreshStructure();
      await openSceneInEditorPane(scene.id);
    });
  }

  function isLeafNode(node: StructureNode): boolean {
    return node.type === "scene";
  }

  function renderNodeTitle(node: StructureNode, schema: MetadataSchema | null): string {
    const template = schema?.entry_types[node.type]?.display_template ?? "{title}";
    const liveTitle = node.scene_id ? draftTitleByScene.get(node.scene_id) : undefined;
    const effectiveTitle = liveTitle ?? node.title;
    return template.replace(/\{(\w+)\}/g, (_match, fieldName) => {
      if (fieldName === "title") return effectiveTitle;
      const computed = node.computed_metadata?.[fieldName];
      if (computed !== undefined && computed !== null) return String(computed);
      return "";
    });
  }

  function defaultChildEntryType(parentType: string): string | null {
    if (parentType === "root") return "act";
    if (parentType === "act") return "chapter";
    if (parentType === "chapter") return "scene";
    return null;
  }

  function manuscriptEntryTypeChoices(schema: MetadataSchema | null): Array<{ id: string; name: string }> {
    return Object.entries(schema?.entry_types ?? {})
      .filter(([, definition]) => definition.kind === "scene" && !definition.abstract)
      .map(([id, definition]) => ({ id, name: definition.name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  function entryTypeName(typeId: string, schema: MetadataSchema | null): string {
    return schema?.entry_types[typeId]?.name ?? typeId;
  }

  function findStructureNodeById(node: StructureNode | null | undefined, id: string): StructureNode | null {
    if (!node) return null;
    if (node.id === id) return node;
    for (const child of node.children ?? []) {
      const found = findStructureNodeById(child, id);
      if (found) return found;
    }
    return null;
  }

  function parentNodeOrRoot(parentId: string | null): StructureNode | null {
    if (!structure) return null;
    if (!parentId) return structure.root;
    return findStructureNodeById(structure.root, parentId);
  }

  function nextAutoName(parentId: string | null, entryType: string): string {
    const typeName = entryTypeName(entryType, metadataSchema);
    const parent = parentNodeOrRoot(parentId);
    const siblingCount = parent?.children?.filter((child) => child.type === entryType).length ?? 0;
    return `${typeName} ${siblingCount + 1}`;
  }

  function findNewlyAddedChildId(
    before: StructureDocument | null,
    after: StructureDocument | null,
    parentId: string | null,
  ): string | null {
    if (!after) return null;
    const beforeParent = before ? findStructureNodeById(before.root, parentId ?? before.root.id) : null;
    const afterParent = findStructureNodeById(after.root, parentId ?? after.root.id);
    if (!afterParent) return null;
    const beforeIds = new Set(beforeParent?.children?.map((child) => child.id) ?? []);
    return afterParent.children.find((child) => !beforeIds.has(child.id))?.id ?? null;
  }

  async function addStructureChild(parentId: string | null, entryType: string) {
    const title = nextAutoName(parentId, entryType);
    addMenuOpenFor = null;
    await run(async () => {
      const before = structure;
      let createdNodeId: string | null = null;
      if (entryType === "scene") {
        const scene = await api.createScene(title, parentId ?? undefined);
        await refreshStructure();
        await openSceneInEditorPane(scene.id);
        const newNode = structure ? findStructureNodeForScene(structure.root, scene.id) : null;
        createdNodeId = newNode?.id ?? null;
      } else {
        structure = await api.createStructureNode(title, entryType, parentId);
        createdNodeId = findNewlyAddedChildId(before, structure, parentId);
      }
      if (createdNodeId) {
        startRename(createdNodeId, title);
      }
    });
  }

  function findStructureNodeForScene(node: StructureNode, sceneId: string): StructureNode | null {
    if (node.scene_id === sceneId) return node;
    for (const child of node.children ?? []) {
      const found = findStructureNodeForScene(child, sceneId);
      if (found) return found;
    }
    return null;
  }

  function toggleAddMenu(nodeId: string) {
    addMenuOpenFor = addMenuOpenFor === nodeId ? null : nodeId;
  }

  function startRename(nodeId: string, currentTitle: string) {
    editingNodeId = nodeId;
    editingTitle = currentTitle;
    setTimeout(() => {
      const input = document.querySelector<HTMLInputElement>(`[data-node-edit-id="${nodeId}"]`);
      if (input) {
        input.focus();
        input.select();
      }
    }, 0);
  }

  async function commitRename(nodeId: string) {
    if (editingNodeId !== nodeId) return;
    const trimmed = editingTitle.trim();
    const node = structure ? findStructureNodeById(structure.root, nodeId) : null;
    editingNodeId = null;
    if (!trimmed || !node || node.title === trimmed) {
      return;
    }
    if (structure) {
      structure = { root: updateNodeTitleInTree(structure.root, nodeId, trimmed) };
    }
    await run(async () => {
      structure = await api.renameStructureNode(nodeId, trimmed);
      syncRenameIntoEditorPanes(nodeId, trimmed);
    });
  }

  function syncRenameIntoEditorPanes(nodeId: string, newTitle: string) {
    if (!structure) return;
    const renamedNode = findStructureNodeById(structure.root, nodeId);
    if (!renamedNode?.scene_id) return;
    const sceneId = renamedNode.scene_id;
    const nextReloads = { ...titleReloadsByPane };
    editorPanes = editorPanes.map((pane) => {
      if (!pane.scene || pane.scene.id !== sceneId) return pane;
      const nextScene = { ...pane.scene, title: newTitle };
      if (pane.dirty) {
        return { ...pane, scene: nextScene };
      }
      nextReloads[pane.id] = {
        token: (nextReloads[pane.id]?.token ?? 0) + 1,
        title: newTitle,
      };
      return { ...pane, scene: nextScene, draftTitle: newTitle };
    });
    titleReloadsByPane = nextReloads;
  }

  function cancelRename() {
    editingNodeId = null;
  }

  function updateNodeTitleInTree(node: StructureNode, nodeId: string, title: string): StructureNode {
    if (node.id === nodeId) {
      return { ...node, title };
    }
    return {
      ...node,
      children: (node.children ?? []).map((child) => updateNodeTitleInTree(child, nodeId, title)),
    };
  }

  function handleRenameKeydown(event: KeyboardEvent, nodeId: string) {
    if (event.key === "Enter") {
      event.preventDefault();
      void commitRename(nodeId);
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancelRename();
    }
  }

  function handleTreeRowKeydown(event: KeyboardEvent, node: StructureNode) {
    if (event.key === "F2") {
      event.preventDefault();
      startRename(node.id, node.title);
      return;
    }
    if (!(event.ctrlKey || event.metaKey)) return;
    if (event.key === "ArrowUp") {
      event.preventDefault();
      void moveNodeUp(node);
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      void moveNodeDown(node);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      void indentNode(node);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      void outdentNode(node);
    }
  }

  async function refocusTreeNode(nodeId: string) {
    await tick();
    const el = document.querySelector<HTMLElement>(`[data-tree-node-id="${nodeId}"]`);
    el?.focus();
  }

  async function moveNodeUp(node: StructureNode) {
    if (!structure) return;
    const found = findParentAndIndex(structure.root, node.id);
    if (!found || found.index === 0) return;
    await run(async () => {
      structure = await api.moveStructureNode(node.id, found.parent.id, found.index - 1);
    });
    await refocusTreeNode(node.id);
  }

  async function moveNodeDown(node: StructureNode) {
    if (!structure) return;
    const found = findParentAndIndex(structure.root, node.id);
    if (!found || found.index >= (found.parent.children?.length ?? 0) - 1) return;
    await run(async () => {
      structure = await api.moveStructureNode(node.id, found.parent.id, found.index + 1);
    });
    await refocusTreeNode(node.id);
  }

  async function indentNode(node: StructureNode) {
    if (!structure) return;
    const found = findParentAndIndex(structure.root, node.id);
    if (!found || found.index === 0) return;
    const previousSibling = found.parent.children[found.index - 1];
    if (previousSibling.scene_id) return;
    const newPosition = previousSibling.children?.length ?? 0;
    await run(async () => {
      structure = await api.moveStructureNode(node.id, previousSibling.id, newPosition);
    });
    await refocusTreeNode(node.id);
  }

  async function outdentNode(node: StructureNode) {
    if (!structure) return;
    const parentFound = findParentAndIndex(structure.root, node.id);
    if (!parentFound) return;
    if (parentFound.parent.id === structure.root.id) return;
    const grandparentFound = findParentAndIndex(structure.root, parentFound.parent.id);
    if (!grandparentFound) return;
    await run(async () => {
      structure = await api.moveStructureNode(node.id, grandparentFound.parent.id, grandparentFound.index + 1);
    });
    await refocusTreeNode(node.id);
  }

  function findParentAndIndex(
    parent: StructureNode,
    nodeId: string,
  ): { parent: StructureNode; index: number } | null {
    for (let i = 0; i < (parent.children?.length ?? 0); i++) {
      if (parent.children[i].id === nodeId) return { parent, index: i };
      const found = findParentAndIndex(parent.children[i], nodeId);
      if (found) return found;
    }
    return null;
  }

  function handleTreeDragStart(event: DragEvent, node: StructureNode) {
    draggedNodeId = node.id;
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", node.id);
    }
  }

  function handleTreeDragEnd() {
    draggedNodeId = null;
    dragOverNodeId = null;
    dragOverPosition = null;
  }

  function handleTreeDragOver(event: DragEvent, node: StructureNode) {
    if (!draggedNodeId || draggedNodeId === node.id) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    const target = event.currentTarget;
    if (!(target instanceof HTMLElement)) return;
    const rect = target.getBoundingClientRect();
    const ratio = (event.clientY - rect.top) / rect.height;
    let position: "before" | "after" | "into";
    const isContainer = !isLeafNode(node);
    if (isContainer && ratio > 0.2 && ratio < 0.8) {
      position = "into";
    } else if (ratio < 0.5) {
      position = "before";
    } else {
      position = "after";
    }
    if (dragOverNodeId !== node.id || dragOverPosition !== position) {
      dragOverNodeId = node.id;
      dragOverPosition = position;
    }
  }

  async function handleTreeDrop(event: DragEvent, node: StructureNode) {
    event.preventDefault();
    const sourceId = draggedNodeId;
    const position = dragOverPosition;
    handleTreeDragEnd();
    if (!sourceId || !position || !structure || sourceId === node.id) return;

    let targetParentId: string;
    let targetIndex: number;
    if (position === "into") {
      targetParentId = node.id;
      const target = findStructureNodeById(structure.root, node.id);
      targetIndex = target?.children?.length ?? 0;
    } else {
      const found = findParentAndIndex(structure.root, node.id);
      if (!found) return;
      targetParentId = found.parent.id;
      targetIndex = found.index + (position === "after" ? 1 : 0);
    }

    const sourceFound = findParentAndIndex(structure.root, sourceId);
    if (sourceFound && sourceFound.parent.id === targetParentId && sourceFound.index < targetIndex) {
      targetIndex -= 1;
    }

    await run(async () => {
      structure = await api.moveStructureNode(sourceId, targetParentId, targetIndex);
    });
  }

  async function requestDeleteStructureNode(node: StructureNode) {
    if (editingNodeId === node.id) {
      editingNodeId = null;
    }
    let preview: StructureNodeDeletePreview | null = null;
    try {
      preview = await api.cascadeDeletePreview(node.id);
    } catch (error) {
      console.warn("Failed to fetch cascade preview", error);
    }
    const typeName = entryTypeName(node.type, metadataSchema);
    const sceneCount = preview?.descendant_scene_count ?? 0;
    const containerCount = preview?.descendant_container_count ?? 0;
    const backlinks = preview?.backlinks ?? [];

    let message = `Delete ${typeName} "${node.title}"?`;
    const cascadeParts: string[] = [];
    if (sceneCount > 0) cascadeParts.push(`${sceneCount} scene${sceneCount === 1 ? "" : "s"}`);
    if (containerCount > 0) cascadeParts.push(`${containerCount} sub-container${containerCount === 1 ? "" : "s"}`);
    if (cascadeParts.length > 0) {
      message += `\n\nThis will also permanently remove ${cascadeParts.join(" and ")} inside it.`;
    } else if (node.scene_id) {
      message += " This removes the scene file from the project.";
    } else {
      message += " This removes the container from the project.";
    }
    if (backlinks.length > 0) {
      message += `\n\n${backlinks.length} ${backlinks.length === 1 ? "entry references" : "entries reference"} content that will be deleted — those links will break:`;
    }
    const details = backlinks.map((link) => `${link.title} — ${link.field_name}`);

    confirmation = {
      title: `Delete ${typeName}`,
      message,
      details,
      confirmLabel: `Delete ${typeName}`,
      destructive: true,
      onConfirm: () => deleteStructureNode(node.id),
    };
  }

  async function deleteStructureNode(nodeId: string) {
    structure = await api.deleteStructureNode(nodeId);
    await refreshTodos();
    const livingSceneIds = collectSceneIdSet(structure?.root ?? null);
    const deadPaneIds = editorPanes
      .filter((pane) => pane.scene && !livingSceneIds.has(pane.scene.id))
      .map((pane) => pane.id);
    if (deadPaneIds.length > 0) {
      const deadSet = new Set(deadPaneIds);
      editorPanes = editorPanes.filter((pane) => !deadSet.has(pane.id));
      embeddedTodosByPane = Object.fromEntries(
        Object.entries(embeddedTodosByPane).filter(([id]) => !deadSet.has(id)),
      );
      metadataReloadsByPane = Object.fromEntries(
        Object.entries(metadataReloadsByPane).filter(([id]) => !deadSet.has(id)),
      );
      titleReloadsByPane = Object.fromEntries(
        Object.entries(titleReloadsByPane).filter(([id]) => !deadSet.has(id)),
      );
      panes = Object.fromEntries(Object.entries(panes).filter(([id]) => !deadSet.has(id)));
      if (focusedEditorPaneId && deadSet.has(focusedEditorPaneId)) {
        focusedEditorPaneId = editorPanes[0]?.id ?? null;
      }
    }
    status = "Deleted";
  }

  function collectSceneIdSet(node: StructureNode | null): Set<string> {
    const ids = new Set<string>();
    if (!node) return ids;
    const walk = (current: StructureNode) => {
      if (current.scene_id) ids.add(current.scene_id);
      for (const child of current.children ?? []) walk(child);
    };
    walk(node);
    return ids;
  }

  async function newLoreEntry() {
    await run(async () => {
      const entry = await api.createLoreEntry("New Entry", "lore_note");
      await refreshLoreEntries();
      await openLoreEntryInEditorPane(entry.id);
    });
  }

  async function openProjectNodeInEditorPane() {
    // Singleton — focus the existing pane if it's already showing the
    // project node, otherwise reuse a non-pinned pane (or open one).
    const existingPane = editorPanes.find((pane) => pane.document?.type === "project");
    if (existingPane) {
      focusedEditorPaneId = existingPane.id;
      focusPane(existingPane.id);
      status = `Focused ${existingPane.scene?.title ?? "project"}`;
      return;
    }

    await run(async () => {
      let targetPane = editorPanes.find((pane) => !pane.pinned);
      if (!targetPane) {
        targetPane = addEditorPane();
      }
      if (targetPane.dirty) {
        await saveEditorPane(targetPane.id);
      }

      const node = await api.getProjectNode();
      // The editor pane uses Scene-compatible shape; project nodes have no
      // `status` so default to "" and let the documentKind branch hide it.
      const sceneShaped = {
        ...node,
        status: "",
        source_layer_id: "",
        source_layer_label: "",
      } as unknown as Scene;
      editorPanes = editorPanes.map((pane) =>
        pane.id === targetPane!.id
          ? {
              ...pane,
              document: { type: "project", id: node.id },
              scene: sceneShaped,
              dirty: false,
              draftTitle: node.title,
              draftMarkdown: node.body_markdown,
              draftStatus: "",
              draftEntryType: node.entry_type,
              draftMetadata: cloneMetadata(node.metadata),
              saving: false,
            }
          : pane,
      );
      focusedEditorPaneId = targetPane!.id;
      focusPane(targetPane!.id);
      status = `Loaded ${node.title}`;
    });
  }

  async function openSceneInEditorPane(sceneId: string) {
    const existingPane = editorPanes.find((pane) => pane.document?.type === "scene" && pane.document.id === sceneId);
    if (existingPane) {
      focusedEditorPaneId = existingPane.id;
      focusPane(existingPane.id);
      status = `Focused ${existingPane.scene?.title ?? "open scene"}`;
      return;
    }

    let targetPane = editorPanes.find((pane) => !pane.pinned);
    if (!targetPane) {
      targetPane = addEditorPane();
    }

    if (targetPane.dirty) {
      await saveEditorPane(targetPane.id);
    }

    const scene = await api.getScene(sceneId);
    editorPanes = editorPanes.map((pane) =>
      pane.id === targetPane.id
        ? {
            ...pane,
            document: { type: "scene", id: scene.id },
            scene,
            dirty: false,
            draftTitle: scene.title,
            draftMarkdown: scene.body_markdown,
            draftStatus: scene.status,
            draftEntryType: scene.entry_type,
            draftMetadata: cloneMetadata(scene.metadata),
            saving: false,
          }
        : pane,
    );
    focusedEditorPaneId = targetPane.id;
    focusPane(targetPane.id);
    status = `Loaded ${scene.title}`;
    if (!sceneEntryHasBody(scene)) {
      await tick();
      fitEditorPaneToContent(targetPane.id);
    }
  }

  function sceneEntryHasBody(scene: Scene): boolean {
    const entryDefinition = metadataSchema?.entry_types[scene.entry_type];
    return entryDefinition?.has_body ?? true;
  }

  function navigateToBacklink(id: string, kind: string) {
    if (kind === "lore") {
      void run(() => openLoreEntryInEditorPane(id));
    } else {
      void run(() => openSceneInEditorPane(id));
    }
  }

  function fitEditorPaneToContent(paneId: string) {
    setTimeout(() => {
      const paneEl = document.querySelector<HTMLElement>(`[data-pane-id="${paneId}"]`);
      if (!paneEl) return;
      const headerEl = paneEl.querySelector<HTMLElement>(".pane-header");
      const panelEl = paneEl.querySelector<HTMLElement>(".editor-panel");
      if (!headerEl || !panelEl) return;
      let contentHeight = 0;
      for (const child of Array.from(panelEl.children)) {
        const el = child as HTMLElement;
        if (el.offsetParent === null) continue;
        contentHeight += el.getBoundingClientRect().height;
      }
      const totalHeight = headerEl.getBoundingClientRect().height + contentHeight + 24;
      const current = panes[paneId];
      if (!current || totalHeight < 120) return;
      const newHeight = Math.round(totalHeight);
      panes = {
        ...panes,
        [paneId]: { ...current, height: newHeight },
      };
      paneEl.style.height = `${newHeight}px`;
    }, 100);
  }

  async function openPromptEntryInEditorPane(entryId: string) {
    const existingPane = editorPanes.find((pane) => pane.document?.type === "prompt" && pane.document.id === entryId);
    if (existingPane) {
      focusedEditorPaneId = existingPane.id;
      focusPane(existingPane.id);
      status = `Focused ${existingPane.scene?.title ?? "open prompt"}`;
      return;
    }
    let targetPane = editorPanes.find((pane) => !pane.pinned);
    if (!targetPane) targetPane = addEditorPane();
    if (targetPane.dirty) await saveEditorPane(targetPane.id);
    const entry = await api.getPromptEntry(entryId);
    editorPanes = editorPanes.map((pane) =>
      pane.id === targetPane.id
        ? {
            ...pane,
            document: { type: "prompt", id: entry.id },
            scene: entry,
            dirty: false,
            draftTitle: entry.title,
            draftMarkdown: entry.body_markdown,
            draftStatus: "",
            draftEntryType: entry.entry_type,
            draftMetadata: cloneMetadata(entry.metadata),
            draftInputs: JSON.parse(JSON.stringify(entry.inputs ?? [])),
            saving: false,
          }
        : pane,
    );
    focusedEditorPaneId = targetPane.id;
    focusPane(targetPane.id);
    status = `Loaded ${entry.title}`;
  }

  async function newPromptEntry(entryType: string) {
    await run(async () => {
      const created = await api.createPromptEntry(`Untitled Prompt`, entryType);
      await refreshPromptEntries();
      await openPromptEntryInEditorPane(created.id);
    });
  }

  async function openAssistantEntryInEditorPane(entryId: string) {
    const existingPane = editorPanes.find((pane) => pane.document?.type === "assistant" && pane.document.id === entryId);
    if (existingPane) {
      focusedEditorPaneId = existingPane.id;
      focusPane(existingPane.id);
      status = `Focused ${existingPane.scene?.title ?? "open assistant"}`;
      return;
    }
    let targetPane = editorPanes.find((pane) => !pane.pinned);
    if (!targetPane) targetPane = addEditorPane();
    if (targetPane.dirty) await saveEditorPane(targetPane.id);
    const entry = await api.getAssistantEntry(entryId);
    editorPanes = editorPanes.map((pane) =>
      pane.id === targetPane.id
        ? {
            ...pane,
            document: { type: "assistant", id: entry.id },
            scene: entry,
            dirty: false,
            draftTitle: entry.title,
            draftMarkdown: "",
            draftStatus: "",
            draftEntryType: entry.entry_type,
            draftMetadata: cloneMetadata(entry.metadata),
            saving: false,
          }
        : pane,
    );
    focusedEditorPaneId = targetPane.id;
    focusPane(targetPane.id);
    status = `Loaded ${entry.title}`;
  }

  async function newAssistantEntry() {
    await run(async () => {
      const created = await api.createAssistantEntry("Untitled assistant");
      await refreshAssistantEntries();
      await openAssistantEntryInEditorPane(created.id);
    });
  }

  async function openLoreEntryInEditorPane(entryId: string) {
    const existingPane = editorPanes.find((pane) => pane.document?.type === "lore" && pane.document.id === entryId);
    if (existingPane) {
      focusedEditorPaneId = existingPane.id;
      focusPane(existingPane.id);
      status = `Focused ${existingPane.scene?.title ?? "open entry"}`;
      return;
    }

    let targetPane = editorPanes.find((pane) => !pane.pinned);
    if (!targetPane) {
      targetPane = addEditorPane();
    }

    if (targetPane.dirty) {
      await saveEditorPane(targetPane.id);
    }

    const entry = await api.getLoreEntry(entryId);
    editorPanes = editorPanes.map((pane) =>
      pane.id === targetPane.id
        ? {
            ...pane,
            document: { type: "lore", id: entry.id },
            scene: entry,
            dirty: false,
            draftTitle: entry.title,
            draftMarkdown: entry.body_markdown,
            draftStatus: "",
            draftEntryType: entry.entry_type,
            draftMetadata: cloneMetadata(entry.metadata),
            saving: false,
          }
        : pane,
    );
    focusedEditorPaneId = targetPane.id;
    focusPane(targetPane.id);
    status = `Loaded ${entry.title}`;
  }

  function filterLoreEntries(entries: LoreEntrySummary[], query: string) {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) return entries;
    return entries.filter((entry) => loreEntrySearchText(entry).includes(normalizedQuery));
  }

  function groupLoreEntriesByType(entries: LoreEntrySummary[], schema: MetadataSchema | null): LoreEntryGroup[] {
    const groupsByType = new Map<string, LoreEntryGroup>();
    for (const entry of entries) {
      const groupId = `type:${entry.entry_type || "unknown"}`;
      const existingGroup = groupsByType.get(groupId);
      if (existingGroup) {
        existingGroup.entries.push(entry);
      } else {
        groupsByType.set(groupId, {
          id: groupId,
          label: loreEntryTypeName(entry, schema),
          entries: [entry],
          depth: 0,
        });
      }
    }
    return Array.from(groupsByType.values()).sort((left, right) => left.label.localeCompare(right.label, undefined, { sensitivity: "base" }));
  }

  function toggleLoreGroup(groupId: string) {
    collapsedLoreGroups = {
      ...collapsedLoreGroups,
      [groupId]: !collapsedLoreGroups[groupId],
    };
  }

  function loreEntrySearchText(entry: LoreEntrySummary) {
    return [
      entry.title,
      entry.body_markdown,
      loreEntryTypeName(entry, metadataSchema),
      metadataSearchText(entry.metadata),
    ]
      .join(" ")
      .toLowerCase();
  }

  function loreEntryTypeName(entry: LoreEntrySummary, schema = metadataSchema) {
    return schema?.entry_types[entry.entry_type]?.name ?? "Entry";
  }

  function loreEntryDetailText(entry: LoreEntrySummary) {
    const details = [];
    const aliases = metadataListText(entry.metadata.aliases);
    const tags = metadataListText(entry.metadata.tags);
    if (aliases) details.push(`Aliases: ${aliases}`);
    if (tags) details.push(`Tags: ${tags}`);
    return details.join(" · ");
  }

  function metadataListText(value: unknown) {
    if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean).join(", ");
    if (typeof value === "string") return value.trim();
    return "";
  }

  function metadataSearchText(value: unknown): string {
    if (value === null || value === undefined) return "";
    if (Array.isArray(value)) return value.map(metadataSearchText).join(" ");
    if (typeof value === "object") return Object.values(value).map(metadataSearchText).join(" ");
    return String(value);
  }

  function addEditorPane() {
    const id = `editor_${nextEditorPaneIndex}`;
    nextEditorPaneIndex += 1;
    const offset = Math.min(160, editorPanes.length * 28);
    panes = {
      ...panes,
      [id]: {
        title: "Editor",
        x: 342 + offset,
        y: 18 + offset,
        width: 760,
        height: 662,
        z: nextZ + 1,
      },
    };
    nextZ += 1;
    const pane = createEmptyEditorPane(id);
    editorPanes = [...editorPanes, pane];
    return pane;
  }

  function updateEditorPaneDraft(id: string, title: string, bodyMarkdown: string, status: string, entryType: string, metadata: EntryMetadata, inputs?: PromptInputDefinition[]) {
    editorPanes = editorPanes.map((pane) => {
      if (pane.id !== id) return pane;
      const nextInputs = inputs ?? pane.draftInputs;
      return {
        ...pane,
        dirty:
          isEditorPaneDirty(pane.scene, title, bodyMarkdown, status, entryType, metadata, nextInputs),
        draftTitle: title,
        draftMarkdown: bodyMarkdown,
        draftStatus: status,
        draftEntryType: entryType,
        draftMetadata: cloneMetadata(metadata),
        draftInputs: JSON.parse(JSON.stringify(nextInputs ?? [])),
      };
    });
  }

  function cloneMetadata(metadata: EntryMetadata) {
    return JSON.parse(JSON.stringify(metadata ?? {})) as EntryMetadata;
  }

  function metadataEqual(left: EntryMetadata, right: EntryMetadata) {
    return JSON.stringify(left ?? {}) === JSON.stringify(right ?? {});
  }

  function isEditorPaneDirty(
    scene: EditableDocument | null,
    title: string,
    bodyMarkdown: string,
    status: string,
    entryType: string,
    metadata: EntryMetadata,
    inputs?: PromptInputDefinition[],
  ) {
    if (!scene) return false;
    if (title !== scene.title) return true;
    if (bodyMarkdown !== scene.body_markdown) return true;
    if (documentStatus(scene) ? status !== documentStatus(scene) : false) return true;
    if (entryType !== scene.entry_type) return true;
    if (!metadataEqual(metadata, scene.metadata ?? {})) return true;
    // Prompt-only: inputs are a per-entry array of definitions. Compare the
    // serialised form so reordering / type changes are detected.
    const sceneInputs = (scene as { inputs?: PromptInputDefinition[] }).inputs;
    if (inputs !== undefined && sceneInputs !== undefined) {
      if (JSON.stringify(inputs) !== JSON.stringify(sceneInputs)) return true;
    }
    return false;
  }

  function documentStatus(document: EditableDocument | null) {
    return document && "status" in document ? document.status : "";
  }

  async function refreshOpenEditorPaneBaselines(transformDraftMetadata?: (metadata: EntryMetadata) => EntryMetadata) {
    const documentRefs = Array.from(
      new Map(
        editorPanes
          .map((pane) => pane.document)
          .filter((document): document is DocumentRef => Boolean(document))
          .map((document) => [`${document.type}:${document.id}`, document]),
      ).values(),
    );
    if (documentRefs.length === 0) return;
    const refreshedDocuments = await Promise.all(
      documentRefs.map((document) =>
        document.type === "lore"
          ? api.getLoreEntry(document.id)
          : document.type === "prompt"
            ? api.getPromptEntry(document.id)
            : api.getScene(document.id),
      ),
    );
    const refreshedByKey = new Map(refreshedDocuments.map((document, index) => [`${documentRefs[index].type}:${document.id}`, document]));
    const nextReloads: Record<string, MetadataReloadSignal> = {};
    editorPanes = editorPanes.map((pane) => {
      if (!pane.scene || !pane.document) return pane;
      const refreshedDocument = refreshedByKey.get(`${pane.document.type}:${pane.scene.id}`);
      if (!refreshedDocument) return pane;
      const draftMetadata = transformDraftMetadata ? transformDraftMetadata(refreshedDocument.metadata) : refreshedDocument.metadata;
      nextReloads[pane.id] = {
        token: nextMetadataReloadToken,
        metadata: cloneMetadata(draftMetadata),
        status: documentStatus(refreshedDocument),
        entryType: refreshedDocument.entry_type,
      };
      nextMetadataReloadToken += 1;
      return {
        ...pane,
        scene: refreshedDocument,
        draftMetadata: cloneMetadata(draftMetadata),
        draftStatus: documentStatus(refreshedDocument),
        dirty: isEditorPaneDirty(
          refreshedDocument,
          pane.draftTitle,
          pane.draftMarkdown,
          pane.draftStatus,
          pane.draftEntryType,
          draftMetadata,
        ),
      };
    });
    metadataReloadsByPane = { ...metadataReloadsByPane, ...nextReloads };
  }

  function toggleEditorPanePinned(id: string) {
    editorPanes = editorPanes.map((pane) => (pane.id === id ? { ...pane, pinned: !pane.pinned } : pane));
  }

  async function closeEditorPane(id: string) {
    const pane = editorPanes.find((candidate) => candidate.id === id);
    if (!pane) return;
    await run(async () => {
      if (pane.dirty) {
        await saveEditorPane(id);
      }
      tearDownEditorPane(id);
    });
  }

  function tearDownEditorPane(id: string) {
    const remainingEditorPanes = editorPanes.filter((candidate) => candidate.id !== id);
    editorPanes = remainingEditorPanes;
    const { [id]: _closedTodos, ...remainingEmbeddedTodos } = embeddedTodosByPane;
    embeddedTodosByPane = remainingEmbeddedTodos;
    const { [id]: _closedReload, ...remainingReloads } = metadataReloadsByPane;
    metadataReloadsByPane = remainingReloads;
    const { [id]: _closedTitleReload, ...remainingTitleReloads } = titleReloadsByPane;
    titleReloadsByPane = remainingTitleReloads;
    const { [id]: _closedPane, ...remainingPanes } = panes;
    panes = remainingPanes;
    if (focusedEditorPaneId === id) {
      focusedEditorPaneId = remainingEditorPanes[0]?.id ?? null;
    }
  }

  async function saveEditorPane(id: string) {
    const pane = editorPanes.find((candidate) => candidate.id === id);
    if (!pane?.scene) return;
    const documentKind = pane.document?.type ?? "scene";
    setEditorPaneSaving(id, true);
    try {
      const draftDocument = {
        ...pane.scene,
        title: pane.draftTitle,
        ...(documentKind === "scene" ? { status: pane.draftStatus } : {}),
        entry_type: pane.draftEntryType,
        metadata: cloneMetadata(pane.draftMetadata),
        ...(documentKind === "prompt" ? { inputs: pane.draftInputs } : {}),
      };
      let savedDocument: EditableDocument;
      if (documentKind === "lore") {
        savedDocument = await api.saveLoreEntry(draftDocument as LoreEntry, pane.draftMarkdown);
      } else if (documentKind === "prompt") {
        savedDocument = await api.savePromptEntry(draftDocument as PromptEntry, pane.draftMarkdown);
      } else if (documentKind === "assistant") {
        savedDocument = await api.saveAssistantEntry(draftDocument as AssistantEntry);
      } else if (documentKind === "project") {
        // Project node is the project.md singleton; round-trip via the
        // dedicated endpoint and re-shape into the editor pane's
        // Scene-compatible draft.
        savedDocument = await api.saveProjectNode(draftDocument as ProjectNode, pane.draftMarkdown) as unknown as EditableDocument;
      } else {
        savedDocument = await api.saveScene(draftDocument as Scene, pane.draftMarkdown);
      }
      editorPanes = editorPanes.map((candidate) =>
        candidate.id === id
          ? {
              ...candidate,
              document: { type: documentKind, id: savedDocument.id },
              scene: savedDocument,
              dirty: false,
              draftTitle: savedDocument.title,
              draftMarkdown: savedDocument.body_markdown,
              draftStatus: documentStatus(savedDocument),
              draftEntryType: savedDocument.entry_type,
              draftMetadata: cloneMetadata(savedDocument.metadata),
              saving: false,
            }
          : candidate,
      );
      if (documentKind === "lore") {
        await refreshLoreEntries();
        await refreshKnownTags();
      } else if (documentKind === "prompt") {
        await refreshPromptEntries();
      } else if (documentKind === "assistant") {
        await refreshAssistantEntries();
      } else if (documentKind === "project") {
        // Title may have changed; reflect it on the top bar and pane.
        projectTitle = savedDocument.title;
        if (appState.name === "projectOpen") {
          appState = {
            ...appState,
            project: { ...appState.project, title: savedDocument.title },
          };
        }
      } else {
        await refreshStructure();
        await refreshTodos();
        await refreshKnownTags();
      }
      status = `Saved ${savedDocument.title}`;
    } catch (caught) {
      setEditorPaneSaving(id, false);
      throw caught;
    }
  }

  function setEditorPaneSaving(id: string, saving: boolean) {
    editorPanes = editorPanes.map((pane) => (pane.id === id ? { ...pane, saving } : pane));
  }

  async function requestDeleteEditorPaneScene(id: string) {
    const pane = editorPanes.find((candidate) => candidate.id === id);
    if (!pane?.scene) return;
    const documentKind = pane.document?.type ?? "scene";
    const sceneTitle = pane.scene.title;
    const sceneId = pane.scene.id;
    let backlinks: Backlink[] = [];
    try {
      backlinks = (await api.listBacklinks(sceneId)).backlinks;
    } catch (error) {
      console.warn("Failed to fetch backlinks", error);
    }
    const fileLabel = documentKind === "scene" ? "scene" : documentKind === "lore" ? "entry" : "prompt";
    const titleLabel =
      documentKind === "scene"
        ? "Delete Scene"
        : documentKind === "lore"
          ? "Delete Entry"
          : "Delete Prompt";
    const baseMessage = `Delete "${sceneTitle}"? This removes the ${fileLabel} file from the project.`;
    const message =
      backlinks.length > 0
        ? `${baseMessage}\n\n${backlinks.length} ${backlinks.length === 1 ? "entry references" : "entries reference"} this — those links will become broken:`
        : baseMessage;
    const details = backlinks.map((link) => `${link.title} — ${link.field_name}`);
    confirmation = {
      title: titleLabel,
      message,
      details,
      confirmLabel: titleLabel,
      destructive: true,
      onConfirm: () => deleteEditorPaneScene(id),
    };
  }

  async function confirmModalAction() {
    const currentConfirmation = confirmation;
    if (!currentConfirmation) return;
    confirmation = null;
    await run(currentConfirmation.onConfirm);
  }

  async function deleteEditorPaneScene(id: string) {
    const pane = editorPanes.find((candidate) => candidate.id === id);
    if (!pane?.scene) return;
    const documentKind = pane.document?.type ?? "scene";
    const sceneTitle = pane.scene.title;
    if (documentKind === "lore") {
      loreEntries = (await api.deleteLoreEntry(pane.scene.id)).entries;
    } else if (documentKind === "prompt") {
      promptEntries = (await api.deletePromptEntry(pane.scene.id)).entries;
    } else if (documentKind === "assistant") {
      assistantEntries = (await api.deleteAssistantEntry(pane.scene.id)).entries;
    } else {
      structure = await api.deleteScene(pane.scene.id);
      await refreshTodos();
    }
    tearDownEditorPane(id);
    status = `Deleted ${sceneTitle}`;
  }

  async function addTodo() {
    if (!newTodo.trim()) return;
    await run(async () => {
      todos = (await api.createTodo(newTodo.trim(), activeScene?.id)).items;
      newTodo = "";
    });
  }

  async function toggleTodo(item: TodoItem) {
    await run(async () => {
      todos = (await api.updateTodo(item.id, { status: item.status === "open" ? "done" : "open" })).items;
    });
  }

  async function updateTodoText(item: TodoItem, text: string) {
    const trimmed = text.trim();
    if (!trimmed || trimmed === item.text) return;
    await run(async () => {
      todos = (await api.updateTodo(item.id, { text: trimmed })).items;
    });
  }

  async function deleteTodo(item: TodoItem) {
    await run(async () => {
      todos = (await api.deleteTodo(item.id)).items;
      status = "Deleted TODO";
    });
  }

  async function deleteCompletedTodos() {
    const completedTodos = todos.filter((item) => item.status === "done");
    const completedEmbeddedTodos = allEmbeddedTodos.filter((item) => item.status === "done");
    if (completedTodos.length === 0 && completedEmbeddedTodos.length === 0) return;
    await run(async () => {
      let nextTodos = todos;
      for (const item of completedTodos) {
        nextTodos = (await api.deleteTodo(item.id)).items;
      }
      todos = nextTodos.filter((item) => !item.anchor_id);
      for (const item of completedEmbeddedTodos) {
        editorPaneComponents[item.paneId]?.deleteEmbeddedTodo(item.id);
      }
      const deletedCount = completedTodos.length + completedEmbeddedTodos.length;
      status = `Deleted ${deletedCount} completed TODO${deletedCount === 1 ? "" : "s"}`;
    });
  }

  function handleTodoTextKeydown(event: KeyboardEvent, item: TodoItem) {
    const input = event.currentTarget as HTMLTextAreaElement;
    if (event.key === "Enter" && event.ctrlKey) {
      event.preventDefault();
      input.blur();
    } else if (event.key === "Escape") {
      input.value = item.text;
      input.blur();
    }
  }

  async function validateProject() {
    await run(async () => {
      validation = await api.validateProject();
      status = validation.valid ? "Project validation passed" : "Project validation found issues";
    });
  }

  async function repairProject() {
    await run(async () => {
      validation = await api.repairProject();
      await refreshStructure();
      await refreshTodos();
      status = validation.valid ? "Project repair complete" : "Project repair complete with remaining issues";
    });
  }

  async function search() {
    if (!searchQuery.trim() && !searchOpenTodos) return;
    await run(async () => {
      searchHits = (await api.search(searchQuery.trim(), searchOpenTodos)).hits;
    });
  }

  async function openSearchHit(hit: SearchHit) {
    if (hit.file_id === "project") return;
    await run(async () => {
      if (hit.kind === "lore") {
        await openLoreEntryInEditorPane(hit.file_id);
      } else {
        await openSceneInEditorPane(hit.file_id);
      }
      if (hit.kind === "scene" && hit.todo_id) {
        window.setTimeout(() => highlightEmbeddedTodoInOpenPane(hit.file_id, hit.todo_id!), 0);
      }
    });
  }

  async function openEmbeddedTodo(item: EmbeddedTodo) {
    await run(async () => {
      await openSceneInEditorPane(item.sceneId);
      window.setTimeout(() => highlightEmbeddedTodoInOpenPane(item.sceneId, item.id), 0);
    });
  }

  async function openFileTodo(item: TodoItem) {
    if (!item.scene_id) return;
    await run(async () => {
      await openSceneInEditorPane(item.scene_id!);
    });
  }

  function highlightEmbeddedTodoInOpenPane(sceneId: string, todoId: string) {
    const pane = editorPanes.find((candidate) => candidate.scene?.id === sceneId);
    if (!pane) return;
    editorPaneComponents[pane.id]?.highlightEmbeddedTodo(todoId);
  }

  function nodeChildren(node: StructureNode) {
    return node.children ?? [];
  }

  function updateEmbeddedTodosForPane(id: string, embeddedTodos: Array<{ id: string; text: string; status: "open" | "done"; note: string }>) {
    const pane = editorPanes.find((candidate) => candidate.id === id);
    if (!pane?.scene || pane.document?.type !== "scene") {
      const { [id]: _removed, ...remainingTodos } = embeddedTodosByPane;
      embeddedTodosByPane = remainingTodos;
      return;
    }
    embeddedTodosByPane = {
      ...embeddedTodosByPane,
      [id]: embeddedTodos.map((item) => ({
        ...item,
        paneId: id,
        sceneId: pane.scene!.id,
        sceneTitle: pane.scene!.title,
      })),
    };
  }

  function toggleEmbeddedTodo(item: EmbeddedTodo) {
    editorPaneComponents[item.paneId]?.updateEmbeddedTodo(item.id, {
      status: item.status === "open" ? "done" : "open",
    });
  }

  function updateEmbeddedTodoNote(item: EmbeddedTodo, note: string) {
    if (note === item.note) return;
    editorPaneComponents[item.paneId]?.updateEmbeddedTodo(item.id, { note });
  }

  function deleteEmbeddedTodo(item: EmbeddedTodo) {
    editorPaneComponents[item.paneId]?.deleteEmbeddedTodo(item.id);
  }

  function buildEmbeddedTodoStatusHintsByPane(itemsByPane: Record<string, EmbeddedTodo[]>) {
    return Object.fromEntries(
      Object.entries(itemsByPane).map(([paneId, items]) => {
        const openCount = items.filter((item) => item.status === "open").length;
        const doneCount = items.length - openCount;
        return [
          paneId,
          items.length === 0
            ? "No embedded TODOs. Select text to mark a TODO."
            : `${openCount} open embedded TODO${openCount === 1 ? "" : "s"} · ${doneCount} completed.`,
        ];
      }),
    );
  }
</script>

<TopBar
  currentTitle={isProjectOpen ? projectTitle : null}
  {recentProjects}
  projectOpen={isProjectOpen}
  onSelectRecent={(path) => void openProjectAt(path)}
  onOpenFolder={openDirectoryPickerForOpenProject}
  onNewProject={openNewProjectModal}
  onOpenAssistants={openAssistantsPane}
  onOpenSettings={openMachineSettings}
  onOpenDetailTypes={openDetailTypesPane}
  onOpenProjectNode={() => void openProjectNodeInEditorPane()}
/>

<main class="workspace">
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isPaneVisible("project")} class="pane project-pane" data-pane-id="project" style={paneStyle("project")} aria-label="Project pane" on:mousedown={() => focusPane("project")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Project pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "project")} on:mousedown={(event) => startPaneDrag(event, "project")}>
      <h2>Project</h2>
    </header>
    <div class="pane-content project-panel">
      {#if !isProjectOpen}
        <p class="muted project-empty-hint">
          No project open. Pick one from the switcher above — recents, browse, or create new.
        </p>
      {:else}
        <div class="project-identity">
          <strong class="project-identity-title">{projectTitle}</strong>
          <code class="project-identity-path" title={projectPath}>{projectPath}</code>
          <div class="button-row">
            <button type="button" on:click={validateProject}>Validate</button>
          </div>
        </div>
      {/if}

      <section class="ai-settings" aria-label="AI settings" class:disabled-section={!isProjectOpen}>
        <h3>AI</h3>
        {#if isProjectOpen}
        <div class="button-row">
          <button type="button" on:click={openChatsPane}>Chats…</button>
        </div>
        {/if}
        {#if isProjectOpen}
          <fieldset class="ai-policy">
            <legend>AI access</legend>
            <label><input type="radio" bind:group={aiPolicy} value="off" /> Off</label>
            <label><input type="radio" bind:group={aiPolicy} value="local-only" /> Local only</label>
            <label><input type="radio" bind:group={aiPolicy} value="cloud-allowed" /> Cloud allowed</label>
          </fieldset>
          <label>
            Preferred subscription
            <select bind:value={aiDefaultProvider}>
              <option value="">(machine default)</option>
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
              <option value="openrouter">OpenRouter</option>
              <option value="ollama">Ollama (local)</option>
            </select>
          </label>
          <label>
            Preferred assistant tier
            <select bind:value={aiDefaultModelClass}>
              <option value="">(unset)</option>
              <option value="cheap">cheap</option>
              <option value="balanced">balanced</option>
              <option value="best">best</option>
            </select>
          </label>
          <div class="button-row">
            <button type="button" on:click={updateProjectAISettings}>Save AI Settings</button>
            <button type="button" disabled={aiHealthChecking || aiPolicy === "off"} on:click={runAIHealthCheck}>
              {aiHealthChecking ? "Pinging…" : "Health Check"}
            </button>
          </div>
          <div class="button-row">
            <button type="button" on:click={openPromptsPane}>Prompts…</button>
          </div>
          {#if aiHealthResult}
            <p class="ai-health-result" class:ok={aiHealthResult.ok} class:fail={!aiHealthResult.ok}>
              {#if aiHealthResult.ok}
                ✓ {aiHealthResult.provider} · {aiHealthResult.model} · {aiHealthResult.latency_ms} ms
              {:else}
                ✗ {aiHealthResult.provider || "(no provider)"} — {aiHealthResult.error}
              {/if}
            </p>
          {/if}
        {/if}
      </section>
      {#if validation}
        <section class:invalid={!validation.valid} class="validation-panel" aria-label="Project validation result">
          <h3>{validation.valid ? "Project Looks Consistent" : "Project Issues Found"}</h3>
          {#if validation.migrations_applied.length > 0}
            <strong>Migrations Applied</strong>
            {#each validation.migrations_applied as migration}
              <p class="migration-applied">{migration}</p>
            {/each}
          {/if}
          {#if validation.errors.length > 0}
            <strong>Errors</strong>
            {#each validation.errors as validationError}
              <p>{validationError}</p>
            {/each}
          {/if}
          {#if validation.warnings.length > 0}
            <strong>Warnings</strong>
            {#each validation.warnings as validationWarning}
              <p>{validationWarning}</p>
            {/each}
          {/if}
          {#if validation.errors.length === 0 && validation.warnings.length === 0}
            <p>No structure, scene, or TODO synchronization issues found.</p>
          {/if}
          {#if validation.errors.length > 0 || validation.warnings.length > 0}
            <div class="validation-actions">
              <button type="button" on:click={repairProject}>Repair TODO Links</button>
            </div>
          {/if}
        </section>
      {/if}
    </div>
    <button class="pane-resize" type="button" aria-label="Resize Project pane" on:keydown={(event) => handlePaneResizeKeydown(event, "project")} on:mousedown={(event) => startPaneResize(event, "project")}></button>
  </section>

  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isPaneVisible("outline")} class="pane outline-pane" data-pane-id="outline" style={paneStyle("outline")} aria-label="Manuscript Outline pane" on:mousedown={() => focusPane("outline")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Manuscript Outline pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "outline")} on:mousedown={(event) => startPaneDrag(event, "outline")}>
      <h2>Manuscript Outline</h2>
    </header>
    <div class="pane-content">
      <div class="section-title">
        <h3>Scenes</h3>
        <div class="tree-add-controls">
          <button class="tree-add" on:click={() => addStructureChild(null, defaultChildEntryType("root") ?? "scene")}>+ {entryTypeName(defaultChildEntryType("root") ?? "scene", metadataSchema)}</button>
          <div class="tree-menu-anchor">
            <button class="tree-menu" title="Other types" on:click={() => toggleAddMenu("__root__")}>⋯</button>
            {#if addMenuOpenFor === "__root__"}
              <div class="tree-add-menu">
                {#each manuscriptEntryTypeChoices(metadataSchema) as choice (choice.id)}
                  <button type="button" on:click={() => addStructureChild(null, choice.id)}>{choice.name}</button>
                {/each}
              </div>
            {/if}
          </div>
        </div>
      </div>
      {#if structure}
        {#each nodeChildren(structure.root) as child}
          {@render renderTree(child, 0)}
        {/each}
        {#if nodeChildren(structure.root).length === 0}
          <p class="muted">No scenes yet.</p>
        {/if}
      {:else}
        <p class="muted">Open or create a project to begin.</p>
      {/if}
    </div>
    <button class="pane-resize" type="button" aria-label="Resize Manuscript Outline pane" on:keydown={(event) => handlePaneResizeKeydown(event, "outline")} on:mousedown={(event) => startPaneResize(event, "outline")}></button>
  </section>

  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isPaneVisible("lore")} class="pane lore-pane" data-pane-id="lore" style={paneStyle("lore")} aria-label="Lore pane" on:mousedown={() => focusPane("lore")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Lore pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "lore")} on:mousedown={(event) => startPaneDrag(event, "lore")}>
      <h2>Lore</h2>
      <div class="pane-header-actions">
        <button class="pin-button" type="button" title="Add entry" on:mousedown={(event) => event.stopPropagation()} on:click={() => newLoreEntry()}>+ Entry</button>
      </div>
    </header>
    <div class="pane-content">
      <input class="lore-search" bind:value={loreSearchQuery} placeholder="Search entries, tags, aliases" />
      <div class="schema-layer-fields lore-entry-list">
        {#each groupedLoreEntries as group}
          <section class="lore-entry-group" style={`--group-depth: ${group.depth}`}>
            <button class="lore-group-header" type="button" aria-expanded={!collapsedLoreGroups[group.id]} on:mousedown={(event) => event.stopPropagation()} on:click={() => toggleLoreGroup(group.id)}>
              <span class:collapsed={collapsedLoreGroups[group.id]} class="lore-group-caret">▾</span>
              <span>{group.label}</span>
              <small>{group.entries.length}</small>
            </button>
            {#if !collapsedLoreGroups[group.id]}
              <div class="lore-group-entries">
                {#each group.entries as entry}
                  {@const detailText = loreEntryDetailText(entry)}
                  <button class:active={focusedEditorPane?.document?.type === "lore" && focusedEditorPane.document.id === entry.id} class="schema-row system-row lore-row" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => openLoreEntryInEditorPane(entry.id)}>
                    <span>
                      <strong>{entry.title}</strong>
                      {#if detailText}
                        <small>{detailText}</small>
                      {/if}
                    </span>
                  </button>
                {/each}
              </div>
            {/if}
          </section>
        {/each}
      </div>
      {#if loreEntries.length === 0}
        <p class="muted">No entries yet.</p>
      {:else if filteredLoreEntries.length === 0}
        <p class="muted">No entries match this search.</p>
      {/if}
    </div>
    <button class="pane-resize" type="button" aria-label="Resize Lore pane" on:keydown={(event) => handlePaneResizeKeydown(event, "lore")} on:mousedown={(event) => startPaneResize(event, "lore")}></button>
  </section>

  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isProjectOpen || !schemaPaneOpen} class="pane schema-pane" data-pane-id="schema" style={paneStyle("schema")} aria-label="Detail Types pane" on:mousedown={() => focusPane("schema")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Detail Types pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "schema")} on:mousedown={(event) => startPaneDrag(event, "schema")}>
      <h2>Detail Types</h2>
      <div class="pane-header-actions">
        <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => createSchemaTypeDraft()}>+ Type</button>
        <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => closeSchemaPane("schema")}>Close</button>
      </div>
    </header>
    <div class="pane-content schema-list">
      <div class="schema-kind-tabs" role="tablist" aria-label="Type kind">
        <button
          type="button"
          role="tab"
          aria-selected={schemaFieldKind === "scene"}
          class:active={schemaFieldKind === "scene"}
          on:click={() => switchSchemaKind("scene")}
        >Scene</button>
        <button
          type="button"
          role="tab"
          aria-selected={schemaFieldKind === "lore"}
          class:active={schemaFieldKind === "lore"}
          on:click={() => switchSchemaKind("lore")}
        >Lore</button>
        <button
          type="button"
          role="tab"
          aria-selected={schemaFieldKind === "prompt"}
          class:active={schemaFieldKind === "prompt"}
          on:click={() => switchSchemaKind("prompt")}
        >Prompt</button>
        <button
          type="button"
          role="tab"
          aria-selected={schemaFieldKind === "assistant"}
          class:active={schemaFieldKind === "assistant"}
          on:click={() => switchSchemaKind("assistant")}
        >Assistant</button>
        <button
          type="button"
          role="tab"
          aria-selected={schemaFieldKind === "project"}
          class:active={schemaFieldKind === "project"}
          on:click={() => switchSchemaKind("project")}
        >Project</button>
      </div>
      <div class="schema-context-heading">
        <strong>{schemaContextHeading}</strong>
        <small>Drag a custom type onto another type to change its parent.</small>
      </div>
      <div class="schema-node-tree" aria-label={`${schemaContextHeading} tree`}>
        {#each schemaNodeTypeTree as node}
          {@render renderNodeTypeCard(node)}
        {/each}
        {#if schemaNodeTypeTree.length === 0}
          <p class="muted">No detail types defined for this context.</p>
        {/if}
      </div>
    </div>
    <button class="pane-resize" type="button" aria-label="Resize Detail Types pane" on:keydown={(event) => handlePaneResizeKeydown(event, "schema")} on:mousedown={(event) => startPaneResize(event, "schema")}></button>
  </section>

  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isProjectOpen || !schemaTypePaneOpen} class="pane schema-type-pane" data-pane-id="schema_type" style={paneStyle("schema_type")} aria-label="Detail Type pane" on:mousedown={() => focusPane("schema_type")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Detail Type pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "schema_type")} on:mousedown={(event) => startPaneDrag(event, "schema_type")}>
      <h2>Detail Type</h2>
      <div class="pane-header-actions">
        <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => closeSchemaPane("schema_type")}>Close</button>
      </div>
    </header>
    <div class="pane-content schema-editor">
      {#if schemaTypeReadonly}
        <div class="schema-target-layer">
          <strong>Scope</strong>
          <span>System</span>
        </div>
      {:else}
        <label>
          Save layer
          <select bind:value={schemaTypeLayerId}>
            {#each metadataSchemaLayers as layer}
              <option value={layer.id}>{layer.label}</option>
            {/each}
          </select>
        </label>
      {/if}
      <label>
        Display name
        <input readonly={schemaTypeReadonly} value={schemaTypeName} placeholder="Faction" on:input={(event) => updateSchemaTypeName(event.currentTarget.value)} />
      </label>
      <label>
        Type ID
        <input
          aria-label="Generated Type ID"
          title="Generated from the type name"
          value={schemaTypeId}
          readonly
          placeholder="faction"
        />
      </label>
      {#if selectedSchemaTypeId}
        {@const fieldEntries = fieldEntriesForEntryType(selectedSchemaTypeId)}
        <section class="schema-type-fields" aria-label="Fields on this type">
          <header class="schema-type-fields-header">
            <strong>Fields</strong>
            <small>{fieldEntries.length}</small>
          </header>
          <div class="schema-type-field-list">
            {#each fieldEntries as [fieldId, field]}
              {@const fieldSource = metadataSchemaOverview?.field_sources[fieldId]}
              <button class="schema-node-field-row" type="button" on:click={() => openSchemaFieldDetail(fieldId, selectedSchemaTypeId)}>
                <span>
                  <strong>{field.name}</strong>
                  <small>{fieldId} · {fieldTypeLabel(field.type)}</small>
                </span>
                <span class="schema-source-badge" style={`--source-index: ${sourceLayerIndex(fieldSource)}`}>{sourceBadgeLabel(fieldSource)}</span>
              </button>
            {/each}
            {#if fieldEntries.length === 0}
              <p class="muted">No local fields defined on this type.</p>
            {/if}
          </div>
          {#if !schemaTypeReadonly}
            <div class="button-row">
              <button type="button" on:click={() => createSchemaFieldDraft(schemaTypeLayerId || projectSchemaLayerId(), selectedSchemaTypeId)}>+ Field</button>
            </div>
          {/if}
        </section>
      {/if}

      {#if schemaTypeKind === "prompt"}
        <fieldset class="prompt-fieldset" disabled={schemaTypeReadonly}>
          <legend>Defaults</legend>
          <label>
            Brief
            <textarea rows="4" bind:value={promptSystemPrompt} placeholder="Optional brief inherited by sub-types — sets the assistant's role."></textarea>
          </label>
          <div class="prompt-row">
            <label>
              Assistant tier
              <select bind:value={promptModelClass}>
                <option value="">(inherit)</option>
                <option value="cheap">cheap</option>
                <option value="balanced">balanced</option>
                <option value="best">best</option>
              </select>
            </label>
            <label>
              Subscription policy
              <select bind:value={promptProviderPolicy}>
                <option value="">(inherit project policy)</option>
                <option value="off">Off</option>
                <option value="local-only">Local only</option>
                <option value="cloud-allowed">Cloud allowed</option>
              </select>
            </label>
          </div>
        </fieldset>

        <fieldset class="prompt-fieldset" disabled={schemaTypeReadonly}>
          <legend>Context strategy</legend>
          <p class="muted">How the dispatcher picks the target node and what surrounding context it includes.</p>
          <div class="prompt-row">
            <label>
              Target kind
              <select bind:value={promptContextTargetKind}>
                <option value="">(none)</option>
                <option value="scene">Scene</option>
                <option value="lore">Lore Entry</option>
              </select>
            </label>
            <label class="inline-check">
              <input type="checkbox" bind:checked={promptContextTargetRequired} />
              Target required
            </label>
          </div>
          <label>
            Scan surface
            <input bind:value={promptScanSurface} placeholder="_text_before, _selection" />
            <small>Comma-separated tokens (e.g. <code>_text_before</code>, <code>_selection</code>) or field names.</small>
          </label>
          <div class="prompt-row">
            <label>
              Output kind
              <select bind:value={promptOutputKind}>
                <option value="">(none)</option>
                <option value="append_to_body">Append to body</option>
                <option value="replace_selection">Replace selection</option>
                <option value="replace_field">Replace field</option>
                <option value="chat_panel">Chat panel</option>
                <option value="new_node">New node</option>
              </select>
            </label>
            <label>
              Review
              <select bind:value={promptOutputReview}>
                <option value="">(default)</option>
                <option value="visual_diff">Visual diff</option>
                <option value="auto_apply_undo">Auto-apply with undo</option>
                <option value="none">None</option>
              </select>
            </label>
          </div>
        </fieldset>
      {/if}

      {#if !schemaTypeReadonly}
        <div class="button-row">
          <button type="button" disabled={!schemaTypeLayerId || !schemaTypeId.trim() || !schemaTypeName.trim()} on:click={saveSchemaType}>Save Type</button>
          {#if selectedSchemaTypeId}
            <button class="danger-button" type="button" on:click={requestDeleteSchemaType}>Delete</button>
          {/if}
        </div>
      {/if}
    </div>
    <button class="pane-resize" type="button" aria-label="Resize Detail Type pane" on:keydown={(event) => handlePaneResizeKeydown(event, "schema_type")} on:mousedown={(event) => startPaneResize(event, "schema_type")}></button>
  </section>

  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isProjectOpen || !schemaFieldPaneOpen} class="pane schema-field-pane" data-pane-id="schema_field" style={paneStyle("schema_field")} aria-label="Detail Field pane" on:mousedown={() => focusPane("schema_field")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Detail Field pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "schema_field")} on:mousedown={(event) => startPaneDrag(event, "schema_field")}>
      <h2>Detail Field</h2>
      <div class="pane-header-actions">
        <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => closeSchemaPane("schema_field")}>Close</button>
      </div>
    </header>
    <div class="pane-content schema-editor">
      <div class="schema-target-layer">
        <strong>{schemaFieldReadonly ? "Scope" : selectedSchemaFieldId ? "Defined at" : "Save layer"}</strong>
        <span>{schemaFieldReadonly ? "System" : layerLabel(schemaFieldLayerId)}</span>
      </div>
      <label>
        Display name
        <input readonly={schemaFieldReadonly} value={schemaFieldName} placeholder="POV Character" on:input={(event) => updateSchemaFieldName(event.currentTarget.value)} />
      </label>
      <label>
        Field ID
        <input
          aria-label="Generated Field ID"
          title="Generated from the field name"
          value={schemaFieldId}
          readonly
          placeholder="pov_character"
        />
      </label>
      <label>
        Field type
        {#if schemaFieldReadonly}
          <input readonly value={schemaFieldReadonlyTypeLabel || fieldTypeLabel(schemaFieldType)} />
        {:else}
          <select bind:value={schemaFieldType}>
            <option value="text">Text</option>
            <option value="long_text">Long Text</option>
            <option value="number">Number</option>
            <option value="boolean">Boolean</option>
            <option value="select">Select</option>
            <option value="entity_ref">Entity Reference</option>
            <option value="tags">Tags</option>
          </select>
        {/if}
      </label>
      {#if !schemaFieldReadonly && (schemaFieldType === "select" || schemaFieldType === "entity_ref")}
        <label class="inline-check">
          <input type="checkbox" bind:checked={schemaFieldAllowMultiple} />
          Allow multiple
        </label>
      {/if}
      {#if schemaFieldType === "entity_ref" && !schemaFieldReadonly}
        <label>
          Reference target
          <select
            value={schemaFieldReferenceTarget}
            on:change={(event) => {
              schemaFieldReferenceTarget = event.currentTarget.value as "scene" | "lore";
              schemaFieldReferenceEntryType = "";
            }}
          >
            <option value="lore">Lore Entries</option>
            <option value="scene">Scenes</option>
          </select>
        </label>
        <label>
          Narrow to type (optional)
          <select bind:value={schemaFieldReferenceEntryType}>
            <option value="">Any {schemaFieldReferenceTarget === "scene" ? "scene" : "lore"} entry</option>
            {#each Object.entries(metadataSchema?.entry_types ?? {}).filter(([, definition]) => definition.kind === schemaFieldReferenceTarget) as [typeId, definition]}
              <option value={typeId}>{definition.name}</option>
            {/each}
          </select>
        </label>
      {/if}
      {#if schemaFieldType === "select" && (!schemaFieldReadonly || schemaFieldOptions)}
        <label>
          Options
          <input readonly={schemaFieldReadonly} bind:value={schemaFieldOptions} placeholder="draft, revised, complete" />
        </label>
      {/if}
      {#if !schemaFieldReadonly}
        <div class="button-row">
          <button type="button" disabled={!schemaFieldLayerId || !schemaFieldId.trim() || !schemaFieldName.trim()} on:click={saveSchemaField}>Save Field</button>
          {#if selectedSchemaFieldId}
            <button class="danger" type="button" on:click={requestDeleteSchemaField}>Delete Field</button>
          {/if}
        </div>
      {/if}
    </div>
    <button class="pane-resize" type="button" aria-label="Resize Detail Field pane" on:keydown={(event) => handlePaneResizeKeydown(event, "schema_field")} on:mousedown={(event) => startPaneResize(event, "schema_field")}></button>
  </section>

  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isProjectOpen || !promptsPaneOpen} class="pane prompts-pane" data-pane-id="prompts" style={paneStyle("prompts")} aria-label="Prompts pane" on:mousedown={() => focusPane("prompts")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Prompts pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "prompts")} on:mousedown={(event) => startPaneDrag(event, "prompts")}>
      <h2>Prompts</h2>
      <div class="pane-header-actions">
        <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => closeSchemaPane("prompts")}>Close</button>
      </div>
    </header>
    <div class="pane-content schema-list">
      {#each concretePromptSubtypes as subtype (subtype.id)}
        <div class="prompt-entry-section">
          <header>
            <strong>{subtype.label}</strong>
            <button class="pin-button" type="button" on:click={() => newPromptEntry(subtype.id)}>+ Entry</button>
          </header>
          {#each promptEntries.filter((e) => e.entry_type === subtype.id) as entry (entry.id)}
            <button class:active={focusedEditorPane?.document?.type === "prompt" && focusedEditorPane.document.id === entry.id} class="prompt-entry-row" type="button" on:click={() => openPromptEntryInEditorPane(entry.id)}>
              <span><strong>{entry.title}</strong></span>
            </button>
          {/each}
        </div>
      {/each}
      {#if concretePromptSubtypes.length === 0}
        <p class="muted">No prompt sub-types defined yet. Open a prompt entry's Detail Types to create one.</p>
      {/if}
    </div>
    <button class="pane-resize" type="button" aria-label="Resize Prompts pane" on:keydown={(event) => handlePaneResizeKeydown(event, "prompts")} on:mousedown={(event) => startPaneResize(event, "prompts")}></button>
  </section>

  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!assistantsPaneOpen} class="pane assistants-pane" data-pane-id="assistants" style={paneStyle("assistants")} aria-label="Assistants pane" on:mousedown={() => focusPane("assistants")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Assistants pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "assistants")} on:mousedown={(event) => startPaneDrag(event, "assistants")}>
      <h2>Assistants</h2>
      <div class="pane-header-actions">
        <button class="pin-button" type="button" title="Add assistant" on:mousedown={(event) => event.stopPropagation()} on:click={() => newAssistantEntry()}>+ Assistant</button>
        <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => closeSchemaPane("assistants")}>Close</button>
      </div>
    </header>
    <div class="pane-content schema-list">
      {#each groupedAssistantEntries as group (group.layerId)}
        <div class="prompt-entry-section">
          <header>
            <strong>{group.layerLabel}</strong>
            <small>{group.entries.length}</small>
          </header>
          {#each group.entries as entry (entry.id)}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div
              class="assistant-row-wrap"
              class:drop-before={assistantDropTarget?.id === entry.id && assistantDropTarget?.position === "before"}
              class:drop-after={assistantDropTarget?.id === entry.id && assistantDropTarget?.position === "after"}
              class:dragging={assistantDragId === entry.id}
              on:dragover={(event) => onAssistantDragOver(event, entry)}
              on:dragleave={onAssistantDragLeave}
              on:drop={(event) => onAssistantDrop(event, entry)}
            >
              <span
                class="assistant-drag-handle"
                draggable="true"
                role="button"
                tabindex="-1"
                aria-label="Drag to reorder"
                on:dragstart={(event) => startAssistantDrag(event, entry)}
                on:dragend={endAssistantDrag}
              >⋮⋮</span>
              <button class:active={focusedEditorPane?.document?.type === "assistant" && focusedEditorPane.document.id === entry.id} class="prompt-entry-row" type="button" on:click={() => openAssistantEntryInEditorPane(entry.id)}>
                <span>
                  <strong>{entry.title}</strong>
                  {#if entry.metadata?.is_default}
                    <small class="assistant-default-badge">default</small>
                  {/if}
                  <small>{assistantSubtitle(entry)}</small>
                </span>
              </button>
            </div>
          {/each}
        </div>
      {/each}
      {#if assistantEntries.length === 0}
        <p class="muted">No assistants defined yet. Click + Assistant to create one in the machine layer.</p>
      {/if}
    </div>
    <button class="pane-resize" type="button" aria-label="Resize Assistants pane" on:keydown={(event) => handlePaneResizeKeydown(event, "assistants")} on:mousedown={(event) => startPaneResize(event, "assistants")}></button>
  </section>


  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isPaneVisible("chats")} class="pane chats-pane" data-pane-id="chats" style={paneStyle("chats")} aria-label="Chats pane" on:mousedown={() => focusPane("chats")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Chats pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "chats")} on:mousedown={(event) => startPaneDrag(event, "chats")}>
      <h2>Chats</h2>
      <div class="pane-header-actions">
        <button class="pin-button" type="button" title="Start a new chat" on:mousedown={(event) => event.stopPropagation()} on:click={() => createNewChatSession()}>+ New Chat</button>
        <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => closeSchemaPane("chats")}>Close</button>
      </div>
    </header>
    <div class="pane-content schema-list">
      {#if chatSessions.length === 0}
        <p class="muted">No chats yet. Click + New Chat to start one.</p>
      {:else}
        {#each chatSessions as session (session.id)}
          <div class="chat-session-row-wrap" class:active-chat-row={activeChatId === session.id}>
            <button class:active={activeChatId === session.id} class="prompt-entry-row chat-session-row" type="button" on:click={() => openChatSession(session.id)}>
              <span>
                <strong>{session.title || "Untitled chat"}</strong>
                {#if session.pinned}<small class="assistant-default-badge">pinned</small>{/if}
                {#if session.prompt_entry_id || session.assistant_id}
                  <small class="chat-session-preset">
                    {#if session.prompt_entry_id}
                      <span class="chat-prompt-glyph" aria-hidden="true">✨</span>
                      {chatSessionPromptTitle(session)}
                    {/if}
                    {#if session.prompt_entry_id && session.assistant_id} · {/if}
                    {#if session.assistant_id}
                      {assistantNameFor(session.assistant_id) || "(unknown)"}
                    {/if}
                  </small>
                {/if}
                <small>{session.message_count} message{session.message_count === 1 ? "" : "s"} · {session.updated_at.slice(0, 16).replace("T", " ")}</small>
              </span>
            </button>
            <button class="chat-session-pin" type="button" title={session.pinned ? "Unpin" : "Pin"} on:click={() => togglePinForChat(session.id)}>{session.pinned ? "★" : "☆"}</button>
            <button class="chat-session-delete" type="button" title="Delete chat" on:click={() => deleteChatSessionFromPane(session.id)}>×</button>
          </div>
        {/each}
      {/if}
    </div>
    <button class="pane-resize" type="button" aria-label="Resize Chats pane" on:keydown={(event) => handlePaneResizeKeydown(event, "chats")} on:mousedown={(event) => startPaneResize(event, "chats")}></button>
  </section>


  {#each editorPanes as editorPane (editorPane.id)}
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <section
      class:hidden-pane={!isPaneVisible(editorPane.id)}
      class:from-ancestor={paneEntryFromAncestor(editorPane)}
      class="pane editor-pane"
      data-pane-id={editorPane.id}
      style={paneStyle(editorPane.id)}
      aria-label="Editor pane"
      on:mousedown={() => focusPane(editorPane.id)}
    >
      <header class="pane-header" role="button" tabindex="0" aria-label="Move Editor pane" on:keydown={(event) => handlePaneHeaderKeydown(event, editorPane.id)} on:mousedown={(event) => startPaneDrag(event, editorPane.id)}>
        <h2>
          {editorPane.scene?.title ?? "Editor"}
          {#if paneEntryFromAncestor(editorPane)}
            <span class="ancestor-badge" title="This entry lives in an ancestor project. Edits write back to the original file.">
              from {editorPane.scene?.source_layer_label ?? "ancestor"}
            </span>
          {/if}
        </h2>
        <div class="pane-header-actions">
          {#if editorPane.dirty}
            <span class="pane-status">Unsaved</span>
          {/if}
          <button
            class="pin-button"
            type="button"
            disabled={editorPane.saving || !editorPane.dirty}
            title={editorPane.saving ? "Saving this document" : "Save this document"}
            on:mousedown={(event) => event.stopPropagation()}
            on:click={() => run(() => saveEditorPane(editorPane.id))}
          >
            {editorPane.saving ? "Saving" : "Save"}
          </button>
          <button
            class="pin-button danger"
            type="button"
            disabled={!editorPane.scene}
            title={editorPane.document?.type === "lore" ? "Delete this entry" : "Delete this scene"}
            on:mousedown={(event) => event.stopPropagation()}
            on:click={() => requestDeleteEditorPaneScene(editorPane.id)}
          >
            Delete
          </button>
          <button
            class:active-pin={editorPane.pinned}
            class="pin-button"
            type="button"
            title={editorPane.pinned ? "Unpin this pane" : "Pin this pane"}
            on:mousedown={(event) => event.stopPropagation()}
            on:click={() => toggleEditorPanePinned(editorPane.id)}
          >
            {editorPane.pinned ? "Pinned" : "Pin"}
          </button>
          <button
            class="pin-button"
            type="button"
            title="Close this editor pane"
            on:mousedown={(event) => event.stopPropagation()}
            on:click={() => closeEditorPane(editorPane.id)}
          >
            Close
          </button>
        </div>
      </header>
      <DocumentEditorPane
        bind:this={editorPaneComponents[editorPane.id]}
        scene={editorPane.scene}
        documentKind={editorPane.document?.type ?? "scene"}
        metadataSchema={metadataSchema}
        promptEntries={promptEntries}
        knownTags={knownTags}
        assistantEntries={assistantEntries}
        defaultAssistantId={defaultAssistantEntryId()}
        availableScenes={flattenStructureScenes(structure?.root)}
        metadataReload={metadataReloadsByPane[editorPane.id] ?? null}
        titleReload={titleReloadsByPane[editorPane.id] ?? null}
        dirty={editorPane.dirty}
        todoStatusHint={editorPane.document?.type === "scene" && editorPane.scene && sceneEntryHasBody(editorPane.scene) ? (embeddedTodoStatusHintsByPane[editorPane.id] ?? "No embedded TODOs. Select text to mark a TODO.") : ""}
        on:focus={() => focusPane(editorPane.id)}
        on:change={(event) =>
          updateEditorPaneDraft(
            editorPane.id,
            event.detail.title,
            event.detail.bodyMarkdown,
            event.detail.status,
            event.detail.entryType,
            event.detail.metadata,
            event.detail.inputs,
          )}
        on:custom-data={(event) => openSchemaForCustomData(event.detail.entryType, event.detail.kind)}
        on:embeddedTodos={(event) => updateEmbeddedTodosForPane(editorPane.id, event.detail.todos)}
        on:navigate={(event) => navigateToBacklink(event.detail.id, event.detail.kind)}
        on:open-chat={(event) => seedChatFromPromptEntry(event.detail.entry, event.detail.inputs, event.detail.sceneId, event.detail.assistantId)}
      />
      <button class="pane-resize" type="button" aria-label="Resize Editor pane" on:keydown={(event) => handlePaneResizeKeydown(event, editorPane.id)} on:mousedown={(event) => startPaneResize(event, editorPane.id)}></button>
    </section>
  {/each}

  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isPaneVisible("todo")} class="pane todo-pane" data-pane-id="todo" style={paneStyle("todo")} aria-label="TODO pane" on:mousedown={() => focusPane("todo")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move TODO pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "todo")} on:mousedown={(event) => startPaneDrag(event, "todo")}>
      <h2>TODO</h2>
      <div class="pane-header-actions">
        <button
          class="pin-button danger"
          type="button"
          disabled={!todos.some((item) => item.status === "done") && !allEmbeddedTodos.some((item) => item.status === "done")}
          title="Delete all completed TODOs"
          on:mousedown={(event) => event.stopPropagation()}
          on:click={deleteCompletedTodos}
        >
          Delete Done
        </button>
      </div>
    </header>
    <div class="pane-content">
      <div class="todo-entry">
        <textarea bind:value={newTodo} placeholder="Add a file-level TODO description" rows="3" on:keydown={(event) => event.key === "Enter" && event.ctrlKey && addTodo()}></textarea>
        <button on:click={addTodo}>Add</button>
      </div>
      {#if allEmbeddedTodos.length > 0}
        <div class="todo-section-label">Embedded TODOs from open scenes</div>
      {/if}
      {#each allEmbeddedTodos as item}
        <div class:done={item.status === "done"} class="todo-item">
          <input class="todo-checkbox" type="checkbox" checked={item.status === "done"} aria-label="Toggle embedded TODO" on:change={() => toggleEmbeddedTodo(item)} />
          <div class="todo-text-stack">
            <textarea
              class="todo-text"
              value={item.note}
              aria-label="Embedded TODO note"
              title="Edit embedded TODO note"
              placeholder={item.text}
              rows="3"
              on:blur={(event) => updateEmbeddedTodoNote(item, event.currentTarget.value)}
            ></textarea>
            <button class="todo-link" type="button" on:click={() => openEmbeddedTodo(item)}>
              <strong>{item.sceneTitle}</strong>
              <span>{item.text}</span>
            </button>
          </div>
          <small>Embedded</small>
          <button class="todo-delete" type="button" on:click={() => deleteEmbeddedTodo(item)}>Remove</button>
        </div>
      {/each}
      {#if todos.length > 0}
        <div class="todo-section-label">File TODOs</div>
      {/if}
      {#each todos as item}
        <div class:done={item.status === "done"} class="todo-item">
          <input class="todo-checkbox" type="checkbox" checked={item.status === "done"} aria-label="Toggle TODO" on:change={() => toggleTodo(item)} />
          <textarea
            class="todo-text"
            value={item.text}
            aria-label="TODO description"
            title="Edit TODO description"
            placeholder="Describe this TODO"
            rows="3"
            on:blur={(event) => updateTodoText(item, event.currentTarget.value)}
            on:keydown={(event) => handleTodoTextKeydown(event, item)}
          ></textarea>
          {#if item.scene_id}
            <button class="todo-link compact" type="button" on:click={() => openFileTodo(item)}>Open Scene</button>
          {:else}
            <small>Project</small>
          {/if}
          <button class="todo-delete" type="button" on:click={() => deleteTodo(item)}>Delete</button>
        </div>
      {/each}
    </div>
    <button class="pane-resize" type="button" aria-label="Resize TODO pane" on:keydown={(event) => handlePaneResizeKeydown(event, "todo")} on:mousedown={(event) => startPaneResize(event, "todo")}></button>
  </section>

  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isPaneVisible("search")} class="pane search-pane" data-pane-id="search" style={paneStyle("search")} aria-label="Search pane" on:mousedown={() => focusPane("search")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Search pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "search")} on:mousedown={(event) => startPaneDrag(event, "search")}>
      <h2>Search</h2>
    </header>
    <div class="pane-content">
      <div class="todo-entry">
        <input bind:value={searchQuery} placeholder="Find in scenes and lore" on:keydown={(event) => event.key === "Enter" && search()} />
        <button on:click={search}>Find</button>
      </div>
      <label class="inline-check">
        <input type="checkbox" bind:checked={searchOpenTodos} />
        Include open TODOs
      </label>
      {#each searchHits as hit}
        <button class="search-hit" on:click={() => openSearchHit(hit)}>
          <strong>{hit.path}:{hit.line}</strong>
          <span>{hit.excerpt}</span>
        </button>
      {/each}
    </div>
    <button class="pane-resize" type="button" aria-label="Resize Search pane" on:keydown={(event) => handlePaneResizeKeydown(event, "search")} on:mousedown={(event) => startPaneResize(event, "search")}></button>
  </section>

  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isPaneVisible("chat")} class="pane chat-pane" data-pane-id="chat" style={paneStyle("chat")} aria-label="AI Chat pane" on:mousedown={() => focusPane("chat")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move AI Chat pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "chat")} on:mousedown={(event) => startPaneDrag(event, "chat")}>
      <h2>
        {activeChatId ? activeChatTitle : "AI Chat"}
      </h2>
      {#if activeChatId}
        <div class="pane-header-actions">
          <button class="pin-button" type="button" title={activeChatPinned ? "Unpin" : "Pin"} on:mousedown={(event) => event.stopPropagation()} on:click={() => toggleActiveChatPin()}>{activeChatPinned ? "★" : "☆"}</button>
          <button class="pin-button" type="button" title="Rename chat" on:mousedown={(event) => event.stopPropagation()} on:click={() => renameActiveChat()}>Rename</button>
        </div>
      {/if}
    </header>
    <div class="pane-content chat-panel">
      <!-- Three-way composer strip: Prompt · Assistant · Context.
           Prompt + Assistant are read-only once chat history exists (locked
           preset, preserves the Anthropic cache prefix). Context is additive. -->
      <div class="chat-composer-strip">
        <div class="chat-prompt-anchor">
          <button
            type="button"
            class="chat-prompt-chip"
            class:locked={isActiveChatLocked()}
            class:assigned={!!chatPromptEntryId}
            title={isActiveChatLocked() ? "Prompt is locked while this chat has messages. Start a new chat to switch." : "Pick a prompt"}
            on:click={() => !isActiveChatLocked() && toggleChatPromptPicker()}
            disabled={isActiveChatLocked() && !chatPromptEntryId}
          >
            <span class="chat-prompt-glyph" aria-hidden="true">✨</span>
            <strong>{activePromptTitle}</strong>
            {#if isActiveChatLocked()}
              <span class="chat-lock-glyph" aria-label="locked">🔒</span>
            {:else}
              <span class="chat-prompt-caret" aria-hidden="true">▾</span>
            {/if}
          </button>
          {#if chatPromptEntryId && !isActiveChatLocked()}
            <button
              type="button"
              class="chat-prompt-clear"
              title="Drop this prompt (revert to freeform chat)"
              on:click={clearChatPrompt}
            >×</button>
          {/if}
          {#if promptPickerOpen}
            <div class="chat-prompt-picker" role="menu">
              <input
                class="chat-prompt-picker-search"
                type="text"
                placeholder="Search prompts…"
                bind:value={promptPickerSearch}
              />
              {#each filteredChatPromptEntries() as entry (entry.id)}
                <button
                  type="button"
                  class:active-prompt={entry.id === chatPromptEntryId}
                  on:click={() => pickPromptForChat(entry)}
                >
                  <strong>{entry.title}</strong>
                  <small>{entry.entry_type}</small>
                </button>
              {:else}
                <p class="muted">
                  {promptPickerSearch
                    ? "No prompts match."
                    : "No chat-routed prompts. Create a prompt with output_kind = chat_panel."}
                </p>
              {/each}
            </div>
          {/if}
        </div>
      </div>

      {#if chatActivePromptEntry}
        <div class="chat-active-prompt">
          <span>Chatting via <strong>{chatActivePromptEntry.title}</strong></span>
          <button type="button" on:click={() => (chatActivePromptEntry = null)}>×</button>
        </div>
      {/if}
      <details class="chat-config">
        <summary>Assistant{#if !chatPromptEntryId} &amp; brief{/if} {#if isActiveChatLocked()}<span class="chat-lock-glyph" aria-label="locked">🔒</span>{/if}</summary>
        <label class="chat-label">
          Assistant
          <select bind:value={chatAssistantId} on:change={handleChatAssistantChange} disabled={isActiveChatLocked()}>
            <option value="">Default ({assistantNameFor(defaultAssistantEntryId()) || "use machine default"})</option>
            {#each assistantEntries as assistant (assistant.id)}
              <option value={assistant.id}>{assistant.title}</option>
            {/each}
          </select>
        </label>
        {#if !chatPromptEntryId}
          <!-- Brief is meaningful only in freeform mode. When a prompt is locked
               in, the system message is the prompt's rendered template — use the
               Preview disclosure below to inspect what's actually sent. -->
          <label class="chat-label">
            Brief
            <textarea class="chat-system" bind:value={chatSystemPrompt} on:input={clearActivePromptOnEdit} on:blur={handleChatSystemPromptBlur} spellcheck="false" readonly={isActiveChatLocked()}></textarea>
          </label>
        {/if}
        {#if isActiveChatLocked()}
          <p class="muted chat-lock-hint">
            Prompt, assistant, and brief are locked once a chat has messages — switching them mid-conversation would invalidate the AI cache prefix and force a full re-send.
            Start a new chat to change them.
          </p>
        {/if}
      </details>

      <details class="chat-preview" on:toggle={handlePromptPreviewToggle}>
        <summary>Preview what's sent <small>· system message + attached context</small></summary>
        {#if promptPreviewLoading}
          <p class="muted">Composing preview…</p>
        {:else if promptPreviewError}
          <p class="preview-result-error">{promptPreviewError}</p>
        {:else if promptPreviewText !== null}
          {#if promptPreviewText.trim()}
            <pre class="chat-preview-content">{promptPreviewText}</pre>
          {:else}
            <p class="muted">No system message will be sent. The model sees only the chat history.</p>
          {/if}
        {/if}
        <p class="muted chat-preview-hint">
          This is the system message and context the assistant receives on the next turn.
          Chat history above is also sent. Composer text becomes the next user message.
        </p>
      </details>

      <div class="chat-history" bind:this={chatScrollEl}>
        {#if chatHistory.length === 0}
          <p class="muted chat-empty">No messages yet. Ctrl/⌘+Enter to send.</p>
        {/if}
        {#each chatHistory as message, i}
          <div class="chat-message chat-message-{message.role}">
            <header class="chat-message-role">{message.role}</header>
            {#if message.thinking}
              <details class="chat-thinking" open={chatRunning && i === chatHistory.length - 1 && !message.content}>
                <summary>Thinking</summary>
                <div class="chat-thinking-content">{message.thinking}</div>
              </details>
            {/if}
            {#if chatRunning && i === chatHistory.length - 1 && message.role === "assistant" && !message.content && !message.thinking}
              <div class="chat-message-content chat-typing">…thinking</div>
            {:else if message.content}
              <div class="chat-message-content">{message.content}</div>
            {/if}
            {#if message.truncated}
              <div class="chat-truncated-banner">
                Response cut off — hit max tokens. Increase the limit in Assistant &amp; brief, then re-send.
              </div>
            {/if}
          </div>
        {/each}
      </div>

      {#if chatLastMeta}
        <p class="chat-meta">
          {chatLastMeta.provider} · {chatLastMeta.model} · {chatLastMeta.latency_ms} ms
        </p>
      {/if}
      {#if chatError}
        <p class="preview-result-error">{chatError}</p>
      {/if}

      {#if chatContextItems.length > 0}
        <div class="chat-context-chips">
          {#each chatContextItems as item (item.kind + ":" + item.id)}
            <span class="chat-context-chip" class:scene={item.kind === "scene"} class:lore={item.kind === "lore"}>
              <small>{item.kind === "scene" ? "Scene" : item.entryType}</small>
              <strong>{item.title}</strong>
              <button type="button" aria-label="Remove from context" on:click={() => removeContextItem(item.id, item.kind)}>×</button>
            </span>
          {/each}
        </div>
      {/if}

      <textarea
        class="chat-input"
        bind:value={chatInput}
        on:keydown={handleChatInputKeydown}
        placeholder="Message… (Ctrl/⌘+Enter to send)"
        spellcheck="true"
      ></textarea>
      <div class="button-row chat-action-row">
        <div class="chat-context-anchor">
          <button type="button" on:click={toggleContextMenu}>+ Context</button>
          {#if chatContextMenuOpen}
            <div class="chat-context-menu" role="menu">
              {#if chatContextCategory === null}
                <div class="chat-context-group-heading">Presets</div>
                <button type="button" title="Include the manuscript outline (acts → chapters → scenes with summaries)" on:click={() => addContextItem({ id: "full_outline", kind: "preset", title: "Full Outline", entryType: "preset" })}>Full Outline</button>
                <button type="button" title="Include every scene's prose in manuscript order. Can be large." on:click={() => addContextItem({ id: "full_text", kind: "preset", title: "Full Novel Text", entryType: "preset" })}>Full Novel Text</button>
                <div class="chat-context-group-heading">Browse</div>
                <button type="button" on:click={() => openContextCategory("scene")}>Scenes ›</button>
                <button type="button" on:click={() => openContextCategory("lore")}>Lore Entries ›</button>
                <button type="button" on:click={() => openContextCategory("snippet")}>Snippets ›</button>
              {:else}
                <button type="button" class="chat-context-back" on:click={backToContextCategories}>‹ Back</button>
                <input
                  class="chat-context-search"
                  type="text"
                  placeholder="Search…"
                  bind:value={chatContextSearch}
                />
                {#if chatContextCategory === "scene"}
                  {@const scenes = filteredStructureScenes(structure?.root, chatContextSearch)}
                  {#each scenes as scene (scene.id)}
                    <button
                      type="button"
                      on:click={() => addContextItem({ id: scene.id, kind: "scene", title: scene.title, entryType: "scene" })}
                    >{scene.title}</button>
                  {/each}
                  {#if scenes.length === 0}
                    <p class="muted">{chatContextSearch ? "No matches." : "No scenes in this project."}</p>
                  {/if}
                {:else if chatContextCategory === "lore"}
                  {@const groups = loreEntriesGroupedByType(chatContextSearch)}
                  {#each groups as group (group.typeId)}
                    <div class="chat-context-group-heading">{group.typeName}</div>
                    {#each group.entries as entry (entry.id)}
                      <button
                        type="button"
                        on:click={() => addContextItem({ id: entry.id, kind: "lore", title: entry.title, entryType: entry.entry_type })}
                      >{entry.title}</button>
                    {/each}
                  {/each}
                  {#if groups.length === 0}
                    <p class="muted">{chatContextSearch ? "No matches." : "No lore entries in this project."}</p>
                  {/if}
                {:else}
                  {@const snippets = snippetEntriesFor(chatContextSearch)}
                  {#each snippets as snippet (snippet.id)}
                    <button
                      type="button"
                      on:click={() => addContextItem({ id: snippet.id, kind: "snippet", title: snippet.title, entryType: snippet.entry_type })}
                    >{snippet.title}</button>
                  {/each}
                  {#if snippets.length === 0}
                    <p class="muted">{chatContextSearch ? "No matches." : "No snippets in this project."}</p>
                  {/if}
                {/if}
              {/if}
            </div>
          {/if}
        </div>
        <button type="button" disabled={!chatHistory.length || chatRunning} on:click={clearChat}>Clear</button>
        <button type="button" class="primary" disabled={!chatInput.trim() || chatRunning} on:click={sendChat}>
          {chatRunning ? "Sending…" : "Send"}
        </button>
      </div>
    </div>
    <button class="pane-resize" type="button" aria-label="Resize AI Chat pane" on:keydown={(event) => handlePaneResizeKeydown(event, "chat")} on:mousedown={(event) => startPaneResize(event, "chat")}></button>
  </section>

  {#if directoryPickerOpen}
    <section class="directory-modal-backdrop" aria-label="Choose project folder">
      <div class="directory-modal">
        <header class="directory-modal-header">
          <div>
            <h2>Choose Project Folder</h2>
            <p>{directoryListing?.path ?? "Loading folders..."}</p>
          </div>
          <button type="button" on:click={() => (directoryPickerOpen = false)}>Cancel</button>
        </header>

        <div class="directory-modal-actions">
          <button type="button" disabled={!directoryListing?.parent_path || directoryPickerLoading} on:click={() => loadDirectory(directoryListing?.parent_path)}>
            Up
          </button>
          <button class="primary" type="button" disabled={!directoryListing || directoryPickerLoading} on:click={() => directoryListing && useDirectory(directoryListing.path)}>
            Select This Folder
          </button>
        </div>

        <div class="directory-modal-list">
          {#if directoryPickerLoading}
            <p class="muted">Loading folders...</p>
          {:else if directoryListing}
            {#each directoryListing.directories as directory}
              <button type="button" class="directory-row" on:click={() => loadDirectory(directory.path)} title={directory.path}>
                {directory.name}
              </button>
            {/each}
            {#if directoryListing.directories.length === 0}
              <p class="muted">No folders here.</p>
            {/if}
          {/if}
        </div>
      </div>
    </section>
  {/if}

  {#if confirmation}
    <section class="modal-backdrop" aria-label={confirmation.title}>
      <div class="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <header class="confirm-modal-header">
          <h2 id="confirm-title">{confirmation.title}</h2>
        </header>
        <p>{confirmation.message}</p>
        {#if confirmation.details && confirmation.details.length > 0}
          <ul class="confirm-modal-details">
            {#each confirmation.details as detail}
              <li>{detail}</li>
            {/each}
          </ul>
        {/if}
        <div class="confirm-modal-actions">
          <button type="button" on:click={() => (confirmation = null)}>Cancel</button>
          <button
            class:danger-primary={confirmation.destructive}
            class:primary={!confirmation.destructive}
            type="button"
            on:click={confirmModalAction}
          >
            {confirmation.confirmLabel}
          </button>
        </div>
      </div>
    </section>
  {/if}

  {#if newProjectModalOpen}
    <section class="modal-backdrop" aria-label="New project">
      <div class="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="new-project-title">
        <header class="confirm-modal-header">
          <h2 id="new-project-title">New Project</h2>
        </header>

        <label>
          Project name
          <input
            type="text"
            bind:value={newProjectName}
            placeholder="Honor's First Command"
            on:keydown={(e) => e.key === "Enter" && void confirmNewProject()}
          />
        </label>

        {#if !newProjectOverrideFolder}
          <p class="muted">
            Will be created at:
            <code>{newProjectName.trim() ? newProjectResolvedPath : (defaultProjectsFolder || "(no default folder set)")}</code>
          </p>
          {#if !defaultProjectsFolder}
            <p class="muted">
              No default projects folder set — open <button type="button" class="inline-link" on:click={() => { closeNewProjectModal(); openMachineSettings(); }}>Settings</button> to set one, or override below.
            </p>
          {/if}
          <div class="button-row">
            <button type="button" on:click={openDirectoryPickerForNewProjectOverride}>Override folder…</button>
          </div>
        {:else}
          <label>
            Parent folder
            <div class="path-picker-row">
              <input type="text" bind:value={newProjectOverridePath} placeholder="C:\path\to\writing" />
              <button type="button" on:click={openDirectoryPickerForNewProjectOverride}>Browse…</button>
            </div>
          </label>
          <p class="muted">
            Will be created at: <code>{newProjectName.trim() ? newProjectResolvedPath : "(enter a name)"}</code>
          </p>
          <div class="button-row">
            <button type="button" on:click={() => { newProjectOverrideFolder = false; newProjectOverridePath = ""; }}>Use default folder</button>
          </div>
        {/if}

        <div class="confirm-modal-actions">
          <button type="button" on:click={closeNewProjectModal}>Cancel</button>
          <button
            class="primary"
            type="button"
            disabled={!newProjectName.trim() || (newProjectOverrideFolder ? !newProjectOverridePath.trim() : !defaultProjectsFolder)}
            on:click={confirmNewProject}
          >Create</button>
        </div>
      </div>
    </section>
  {/if}

  {#if machineSettingsOpen && machineSettingsDraft}
    <section class="modal-backdrop" aria-label="Machine settings">
      <div class="confirm-modal machine-settings-modal" role="dialog" aria-modal="true" aria-labelledby="machine-settings-title">
        <header class="confirm-modal-header">
          <h2 id="machine-settings-title">Machine Settings</h2>
        </header>
        <p class="muted">Your AI subscriptions — provider accounts and keys.</p>
        <p class="muted">Stored locally at: <code>{machineSettings?.config_path}</code></p>

        <label>
          Default projects folder
          <input type="text" bind:value={machineSettingsDraft.default_projects_folder} placeholder="C:\path\to\writing" />
          <small class="muted">Where new projects get created by default. The project switcher reads recent projects from this config too.</small>
        </label>

        <p class="muted">API keys are masked on read. Leaving a masked field unchanged keeps the existing value.</p>

        <label>
          Anthropic API key
          <input type="password" autocomplete="off" bind:value={machineSettingsDraft.anthropic_api_key} placeholder="sk-ant-…" />
        </label>
        <label>
          OpenAI API key
          <input type="password" autocomplete="off" bind:value={machineSettingsDraft.openai_api_key} placeholder="sk-…" />
        </label>
        <label>
          OpenRouter API key
          <input type="password" autocomplete="off" bind:value={machineSettingsDraft.openrouter_api_key} placeholder="sk-or-…" />
        </label>
        <label>
          Ollama host
          <input type="text" bind:value={machineSettingsDraft.ollama_host} placeholder="http://127.0.0.1:11434" />
        </label>

        <p class="muted">
          Assistants moved to the <strong>Assistants</strong> pane (open from the AI section of the Project pane). Each lives as its own file under the machine config dir and can be overridden by ancestor projects.
        </p>

        <div class="confirm-modal-actions">
          <button type="button" on:click={() => (machineSettingsOpen = false)}>Cancel</button>
          <button class="primary" type="button" on:click={saveMachineSettings}>Save</button>
        </div>
      </div>
    </section>
  {/if}

  {#if error}
    <section class="error-toast">{error}</section>
  {/if}

  {#if chatInputsDialogEntry}
    {@const declaredChatInputs = chatInputsDialogEntry.inputs ?? []}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="inputs-dialog-backdrop" role="presentation" on:mousedown|self={cancelChatInputsDialog}>
      <div class="inputs-dialog" role="dialog" aria-label={`Apply ${chatInputsDialogEntry.title}`} aria-modal="true" tabindex="-1" on:keydown={handleChatInputsDialogKeydown}>
        <header>
          <strong>{chatInputsDialogEntry.title}</strong>
          <small>Fill in the inputs declared by this prompt.</small>
        </header>
        <div class="inputs-dialog-fields">
          {#each declaredChatInputs as input (input.name)}
            <label>
              {input.label || input.name}{#if input.required}<span class="required-marker"> *</span>{/if}
              <PromptInputField
                input={input}
                value={chatInputsDialogDrafts[input.name] ?? ""}
                metadataSchema={metadataSchema}
                excludeId={null}
                ariaLabel={input.label || input.name}
                on:change={(event) => updateChatInputsDraft(input.name, event.detail.value)}
              />
            </label>
          {/each}
        </div>
        {#if chatInputsDialogError}
          <p class="preview-result-error">{chatInputsDialogError}</p>
        {/if}
        <div class="inputs-dialog-actions">
          <button type="button" on:click={cancelChatInputsDialog}>Cancel</button>
          <button type="button" class="primary" on:click={submitChatInputsDialog}>Apply</button>
        </div>
        <small class="inputs-dialog-hint">Ctrl/⌘+Enter to apply · Esc to cancel</small>
      </div>
    </div>
  {/if}
</main>

{#snippet renderTree(node: StructureNode, depth: number)}
  <div
    class="tree-row"
    class:drop-before={dragOverNodeId === node.id && dragOverPosition === "before"}
    class:drop-after={dragOverNodeId === node.id && dragOverPosition === "after"}
    class:drop-into={dragOverNodeId === node.id && dragOverPosition === "into"}
    class:dragging={draggedNodeId === node.id}
    role="treeitem"
    aria-label={node.title}
    aria-selected="false"
    tabindex={-1}
    style={`padding-left: ${depth * 14}px`}
    on:dragover={(event) => handleTreeDragOver(event, node)}
    on:drop={(event) => handleTreeDrop(event, node)}
  >
    <span
      class="tree-handle"
      draggable="true"
      role="button"
      tabindex="-1"
      aria-label="Drag to reorder"
      on:dragstart={(event) => handleTreeDragStart(event, node)}
      on:dragend={handleTreeDragEnd}
    >⋮⋮</span>
    {#if editingNodeId === node.id}
      <input
        class="tree-title tree-rename-input"
        data-node-edit-id={node.id}
        bind:value={editingTitle}
        on:keydown={(event) => handleRenameKeydown(event, node.id)}
        on:blur={() => commitRename(node.id)}
      />
    {:else if isLeafNode(node)}
      <button data-tree-node-id={node.id} class="tree-scene tree-title" on:click={() => node.scene_id && run(() => openSceneInEditorPane(node.scene_id!))} on:dblclick={() => node.scene_id && run(() => openSceneInEditorPane(node.scene_id!))} on:keydown={(event) => handleTreeRowKeydown(event, node)}>{renderNodeTitle(node, metadataSchema)}</button>
      <button class="tree-delete" title={`Delete ${entryTypeName(node.type, metadataSchema)}`} on:click={() => requestDeleteStructureNode(node)}>×</button>
    {:else}
      <button data-tree-node-id={node.id} class="tree-group tree-title" on:click={() => (activeParentId = node.id)} on:dblclick={() => node.scene_id && run(() => openSceneInEditorPane(node.scene_id!))} on:keydown={(event) => handleTreeRowKeydown(event, node)}>{renderNodeTitle(node, metadataSchema)}</button>
      {@const defaultType = defaultChildEntryType(node.type)}
      {#if defaultType}
        <button class="tree-add" title={`Add ${entryTypeName(defaultType, metadataSchema)}`} on:click={() => addStructureChild(node.id, defaultType)}>+</button>
      {/if}
      <div class="tree-menu-anchor">
        <button class="tree-menu" title="Other types" on:click={() => toggleAddMenu(node.id)}>⋯</button>
        {#if addMenuOpenFor === node.id}
          <div class="tree-add-menu">
            {#each manuscriptEntryTypeChoices(metadataSchema) as choice (choice.id)}
              <button type="button" on:click={() => addStructureChild(node.id, choice.id)}>{choice.name}</button>
            {/each}
          </div>
        {/if}
      </div>
      <button class="tree-delete" title={`Delete ${entryTypeName(node.type, metadataSchema)}`} on:click={() => requestDeleteStructureNode(node)}>×</button>
    {/if}
  </div>
  {#each nodeChildren(node) as child}
    {@render renderTree(child, depth + 1)}
  {/each}
{/snippet}

{#snippet renderNodeTypeCard(node: NodeTypeTreeNode)}
  {@const typeSource = schemaTypeSource(node.id)}
  {@const fieldEntries = fieldEntriesForEntryType(node.id)}
  {@const fieldsCollapsed = collapsedSchemaFieldsByType[node.id] ?? true}
  <section
    class:active={selectedSchemaTypeId === node.id}
    class="schema-node-card"
    draggable={!typeSource?.built_in}
    role="group"
    aria-label={`${node.label} detail type`}
    style={`--source-index: ${sourceLayerIndex(typeSource)}`}
    on:dragstart={() => {
      if (!typeSource?.built_in) startSchemaTypeDrag(node.id);
    }}
    on:dragend={() => (draggedSchemaTypeId = null)}
    on:dragover|preventDefault
    on:drop|preventDefault={() => dropSchemaTypeOnParent(node.id)}
  >
    <div class="schema-node-card-main">
      <button class="schema-node-title" type="button" on:click={() => openSchemaTypeDetail(node.id)}>
        <span>
          <strong>{node.label}</strong>
          <small>{node.id} · {node.definition.abstract ? "Abstract " : ""}Detail Type</small>
        </span>
      </button>
      <span class="schema-source-badge" style={`--source-index: ${sourceLayerIndex(typeSource)}`}>{sourceBadgeLabel(typeSource)}</span>
      <div class="schema-node-actions">
        <button class="pin-button" type="button" on:click={() => createSchemaTypeDraft(schemaTypeLayerId || projectSchemaLayerId(), node.id)}>+ Type</button>
        <button class="pin-button" type="button" on:click={() => createSchemaFieldDraft(schemaTypeLayerId || projectSchemaLayerId(), node.id)}>+ Field</button>
      </div>
    </div>
    <section class="schema-node-fields" aria-label={`${node.label} fields`}>
      <button class="schema-node-fields-toggle" type="button" aria-expanded={!fieldsCollapsed} on:click={() => toggleSchemaFieldsForType(node.id)}>
        <span class:collapsed={fieldsCollapsed} class="lore-group-caret">▾</span>
        <span>Fields</span>
        <small>{fieldEntries.length}</small>
      </button>
      {#if !fieldsCollapsed}
        <div class="schema-node-field-list">
          {#each fieldEntries as [fieldId, field]}
            {@const fieldSource = metadataSchemaOverview?.field_sources[fieldId]}
            <button class="schema-node-field-row" type="button" on:click={() => openSchemaFieldDetail(fieldId, node.id)}>
              <span>
                <strong>{field.name}</strong>
                <small>{fieldId} · {fieldTypeLabel(field.type)}</small>
              </span>
              <span class="schema-source-badge" style={`--source-index: ${sourceLayerIndex(fieldSource)}`}>{sourceBadgeLabel(fieldSource)}</span>
            </button>
          {/each}
          {#if fieldEntries.length === 0}
            <p class="muted">No local fields defined on this type.</p>
          {/if}
        </div>
      {/if}
    </section>
    {#if node.children.length > 0}
      <div class="schema-node-children">
        {#each node.children as child}
          {@render renderNodeTypeCard(child)}
        {/each}
      </div>
    {/if}
  </section>
{/snippet}

