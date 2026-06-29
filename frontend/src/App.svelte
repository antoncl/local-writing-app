<script lang="ts">
  import { onMount, tick } from "svelte";
  import { api } from "./api";
  import CodeEditor from "./CodeEditor.svelte";
  import NodeEditor from "./NodeEditor.svelte";
  import DirectoryPickerModal from "./DirectoryPickerModal.svelte";
  import SchemaTypeEditor from "./SchemaTypeEditor.svelte";
  import type { FieldDraftPayload } from "./SchemaFieldInlineEditor.svelte";
  import SchemaTreePane from "./SchemaTreePane.svelte";
  import Tree, { type TreeConfig } from "./Tree.svelte";
  import Lore from "./Lore.svelte";
  import Assistants from "./Assistants.svelte";
  import Prompts from "./Prompts.svelte";
  import Chats from "./Chats.svelte";
  import Project from "./Project.svelte";
  import Search from "./Search.svelte";
  import Todo, { type EmbeddedTodo } from "./Todo.svelte";
  import Pane, { type PaneChrome } from "./Pane.svelte";
  import {
    buildNodeTypeTree,
    buildSchemaFieldSections,
    slugifyFieldId,
    suggestPrefixFromLabel,
    type NodeTypeTreeNode,
    type SchemaKind,
  } from "./schemaTypeHelpers";
  import {
    collectNodeIdSet,
    collectSceneIdSet,
    entryTypeName,
    findNodeBySceneId,
    findStructureNodeById,
    isLeafNode,
  } from "./treeHelpers";
  import NewProjectModal from "./NewProjectModal.svelte";
  import MachineSettingsDialog from "./MachineSettingsDialog.svelte";
  import ConfirmModal from "./ConfirmModal.svelte";
  import PlainTextEditor from "./PlainTextEditor.svelte";
  import PromptInputField from "./PromptInputField.svelte";
  import TopBar from "./TopBar.svelte";
  import { installThemeWiring, themePreference, nextPreference, type ThemePreference } from "./theme";
  import { renderChatContent } from "./chatMessageRender";
  import { setPalette, resolveColor } from "./colors";
  import { get } from "svelte/store";
  import {
    chatSessionsStore,
    projectCostTotalStore,
    projectCostBreakdownStore,
    refreshChatSessions as storeRefreshChatSessions,
    refreshProjectCost as storeRefreshProjectCost,
    setChatSessions,
    setProjectCost,
  } from "./stores/chats";
  import { todosStore, refreshTodos as storeRefreshTodos, setTodos } from "./stores/todos";
  import { knownTagsStore, refreshKnownTags as storeRefreshKnownTags, setKnownTags } from "./stores/tags";
  import { validationStore, setValidation } from "./stores/validation";
  import {
    structureStore,
    researchStructureStore,
    refreshStructure as storeRefreshStructure,
    refreshResearchStructure as storeRefreshResearchStructure,
    setStructure,
    setResearchStructure,
  } from "./stores/structure";
  import {
    loreEntriesStore,
    refreshLoreEntries as storeRefreshLoreEntries,
    setLoreEntries,
  } from "./stores/lore";
  import {
    promptEntriesStore,
    refreshPromptEntries as storeRefreshPromptEntries,
    setPromptEntries,
  } from "./stores/prompts";
  import {
    assistantEntriesStore,
    defaultAssistantIdStore,
    refreshAssistantEntries as storeRefreshAssistantEntries,
    setAssistantEntries,
  } from "./stores/assistants";
  import {
    metadataSchemaStore,
    metadataSchemaOverviewStore,
    metadataSchemaLayersStore,
    refreshSchema as storeRefreshSchema,
    setMetadataSchema,
  } from "./stores/schema";
  import { implicitContextMatcherStore } from "./stores/derived";
  import { loadProjectData } from "./stores/index";
  import { focusedDocumentStore, pinnedKeysStore } from "./stores/editorFocus";
  import GroupsManagerDialog from "./GroupsManagerDialog.svelte";
  import TagManagerDialog from "./TagManagerDialog.svelte";
  import type { OptionDraft } from "./SelectOptionsEditor.svelte";
  import type {
    AIHealthResponse,
    AIPolicy,
    AssistantEntry,
    AssistantEntrySummary,
    Backlink,
    ChatMessage,
    ChatSession,
    ChatSessionJournalEntry,
    ChatSessionMessage,
    ChatSessionSummary,
    DirectoryListing,
    DocumentKind,
    EditableDocument,
    EntryMetadata,
    EntryTypeDefinition,
    LoreEntry,
    LoreEntrySummary,
    PromptEntry,
    PromptEntrySummary,
    ResearchNote,
    Scene,
    MachineSettingsDraft,
    MachineSettingsUpdate,
    MachineSettingsView,
    MetadataFieldDefinition,
    MetadataFieldType,
    MetadataSchema,
    MetadataSchemaLayer,
    MetadataSchemaOverview,
    NodePickerConfig,
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
  type DocumentRef = { type: "scene" | "lore" | "prompt" | "assistant" | "project" | "structure_node" | "chat" | "research"; id: string };
  // TreeConfig (the per-kind manuscript/research tree contract) + the tree
  // rendering and inline CRUD now live in Tree.svelte; App owns the structure
  // data, the editor-pane coupling (delete, dblclick-open), and collapse state.
  type PaneId = "project" | "outline" | "lore" | "todo" | "search" | string;
  type MetadataReloadSignal = { token: number; metadata: EntryMetadata; status: string; entryType: string };
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
    // True for ~2s after a successful save so the pane chip can briefly
    // show "Saved". Reset whenever the pane becomes dirty again.
    recentlySaved: boolean;
  };

  type ConfirmationState = {
    title: string;
    message: string;
    details?: string[];
    confirmLabel: string;
    destructive: boolean;
    cannotBeUndone?: boolean;
    dontShowAgainKey?: string;
    onConfirm: () => Promise<void>;
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

  // AI chat sessions. Per-chat state (history, composer, cost/TTL) lives
  // inside ChatBodyView now; App only tracks the session roster (Chats pane)
  // and which chat is currently open in an editor pane (active-row highlight).
  $: chatSessions = $chatSessionsStore;
  let activeChatId: string | null = null;
  let activeChatTitle = "Untitled chat";
  // V2: project-wide cost rollup. Refreshed on project open and after
  // each chat save. `projectCostBreakdown` is the per-chat list returned
  // by /api/ai/project-cost; populated only when the user expands the
  // chip so common loads don't pay for full enumeration.
  $: projectCostTotal = $projectCostTotalStore;
  $: projectCostBreakdown = $projectCostBreakdownStore;
  let projectCostExpanded = false;
  let machineSettingsDraft: MachineSettingsDraft | null = null;
  let appState: AppState = { name: "needsProject" };
  $: project = appState.name === "projectOpen" ? appState.project : null;
  $: isProjectOpen = appState.name === "projectOpen";
  $: structure = $structureStore;
  // Research tree — parallel structure to the manuscript tree. Topics
  // are containers, notes are leaves with their own markdown file.
  // See docs/research-strategy.md.
  $: researchStructure = $researchStructureStore;
  let collapsedResearchNodes: Record<string, boolean> = {};
  $: loreEntries = $loreEntriesStore;
  // Compiled matcher for implicit-context highlighting in editors. Derived in
  // the store layer from lore + schema (see stores/derived.ts).
  $: implicitContextMatcher = $implicitContextMatcherStore;
  $: knownTags = $knownTagsStore;
  let tagsManagerOpen = false;
  let focusedEditorPaneId: string | null = null;
  $: focusedEditorPane = editorPanes.find((pane) => pane.id === focusedEditorPaneId) ?? editorPanes[0] ?? null;
  // Write-through the focused doc to the editor-focus store so the list panes
  // read it directly instead of having it drilled in (#14 Step 2). App is the
  // sole writer (projection of editorPanes).
  $: focusedDocumentStore.set(focusedEditorPane?.document ?? null);
  $: activeScene = focusedEditorPane?.document?.type === "scene" ? focusedEditorPane.scene : null;
  let activeParentId: string | undefined = undefined;
  let addMenuOpenFor: string | null = null;
  // Floating-popover coordinates captured at click time. `position: fixed`
  // on the popover sidesteps any ancestor `overflow: hidden` (panes,
  // tier panels) so the menu can extend below/above its anchor without
  // being clipped.
  let addMenuPosition: { top: number; right: number } | null = null;
  let draftTitleByScene = new Map<string, string>();
  $: todos = $todosStore;
  $: validation = $validationStore;
  $: metadataSchema = $metadataSchemaStore;
  $: metadataSchemaOverview = $metadataSchemaOverviewStore;
  $: metadataSchemaLayers = $metadataSchemaLayersStore;
  let schemaFieldKind: SchemaKind = "scene";
  let schemaFieldLayerId = "";
  let schemaFieldEntryType = "scene";
  // The field-editing DRAFT (type / name / key / options / default / picker /
  // computed / icon + the inline editor's popover toggles) now lives inside
  // SchemaFieldInlineEditor (#14 Step 4). App keeps only the context the parent
  // computes from the schema overview: which field is open + whether it's a
  // read-only (built-in) field. The draft arrives back as a payload on save.
  let selectedSchemaFieldId: string | null = null;
  let schemaFieldReadonly = false;
  // L2 reusable-groups manager (modal).
  let groupsManagerOpen = false;
  // L2 "apply group" form state (in the type editor).
  let groupApplyOpen = false;
  let applyGroupId = "";
  let applyGroupLabel = "";
  let applyGroupPrefix = "";
  // Expand-in-place field editing in the type editor: the field id whose
  // inline editor is open (one at a time), or the "__new__" sentinel while
  // adding a field. null = all rows collapsed. Replaces routing to the
  // separate Detail Field pane.
  const NEW_FIELD_SENTINEL = "__new__";
  let expandedSchemaFieldId: string | null = null;
  let schemaPaneOpen = false;
  let schemaTypePaneOpen = false;
  let schemaTypeLayerId = "";
  let schemaTypeId = "";
  let schemaTypeName = "";
  let schemaTypeKind: SchemaKind = "lore";
  let schemaTypeParent = "";
  let schemaTypeAbstract = false;
  let schemaTypeReadonly = false;
  // Type-level palette swatch id. Empty string = "inherit from parent / no
  // override". Saved as null when empty so backend inheritance kicks in.
  let schemaTypeColor: string | null = null;
  let selectedSchemaTypeId: string | null = null;
  let draggedSchemaTypeId: string | null = null;
  let schemaSelectedEntryType: EntryTypeDefinition | null = null;
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
  $: promptEntries = $promptEntriesStore;
  $: assistantEntries = $assistantEntriesStore;
  let newTodo = "";
  // Outline group-header collapse state, keyed by StructureNode.id.
  // Same shape as the other collapsed-* maps so the refactor stays
  // consistent across panes. Persisted per-project to localStorage so
  // the user's collapse choices survive reload.
  let collapsedStructureNodes: Record<string, boolean> = {};
  const TREE_COLLAPSE_LS_PREFIX = "treeCollapse:";

  function loadCollapsedStructureNodes(path: string): Record<string, boolean> {
    if (!path) return {};
    try {
      const raw = localStorage.getItem(TREE_COLLAPSE_LS_PREFIX + path);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }

  function saveCollapsedStructureNodes(path: string, state: Record<string, boolean>): void {
    if (!path) return;
    try {
      localStorage.setItem(TREE_COLLAPSE_LS_PREFIX + path, JSON.stringify(state));
    } catch {
      // Quota / private-browsing — silently degrade to in-memory only.
    }
  }
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
    outline: { title: "Draft", x: 18, y: 260, width: 300, height: 420, z: 2 },
    lore: { title: "Lore", x: 330, y: 260, width: 300, height: 320, z: 3 },
    research: { title: "Research", x: 650, y: 260, width: 300, height: 320, z: 3 },
    schema: { title: "Detail Types", x: 330, y: 260, width: 360, height: 420, z: 3 },
    schema_type: { title: "Detail Type", x: 708, y: 260, width: 440, height: 560, z: 4 },
    prompts: { title: "Prompts", x: 330, y: 260, width: 360, height: 420, z: 3 },
    assistants: { title: "Assistants", x: 330, y: 260, width: 340, height: 420, z: 3 },
    chats: { title: "Chats", x: 330, y: 260, width: 320, height: 420, z: 3 },
    todo: { title: "TODO", x: 1126, y: 18, width: 310, height: 320, z: 4 },
    search: { title: "Search", x: 1126, y: 360, width: 310, height: 320, z: 5 },
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
  $: schemaSelectedEntryType = metadataSchema?.entry_types[schemaFieldEntryType] ?? metadataSchema?.entry_types.scene ?? null;
  $: schemaFieldKind =
    schemaSelectedEntryType?.kind === "lore"
      ? "lore"
      : schemaSelectedEntryType?.kind === "research"
        ? "research"
        : schemaSelectedEntryType?.kind === "prompt"
          ? "prompt"
          : schemaSelectedEntryType?.kind === "assistant"
            ? "assistant"
            : schemaSelectedEntryType?.kind === "project"
              ? "project"
              : "scene";
  $: schemaNodeTypeTree = buildNodeTypeTree(metadataSchema, schemaFieldKind);
  // The type-editor field rows. Explicitly reference metadataSchema so these
  // recompute when the schema is refreshed after a save — fieldEntriesFor…
  // reads it *inside* the function, which the template wouldn't track on its
  // own (see feedback-svelte5-reactivity-traps).
  $: typeOwnFieldEntries =
    metadataSchema && selectedSchemaTypeId ? fieldEntriesForEntryType(selectedSchemaTypeId) : [];
  $: typeInheritedFieldEntries =
    metadataSchema && selectedSchemaTypeId ? inheritedFieldEntriesForEntryType(selectedSchemaTypeId) : [];
  $: typeOwnFieldSections = buildSchemaFieldSections(typeOwnFieldEntries);
  $: typeInheritedFieldSections = buildSchemaFieldSections(typeInheritedFieldEntries);
  // L2 reusable groups: the applications on the selected type + the groups
  // available to apply. Reference metadataSchema explicitly so these recompute
  // after a save (see feedback-svelte5-reactivity-traps).
  $: typeGroupApplications =
    (metadataSchema && selectedSchemaTypeId
      ? metadataSchema.entry_types[selectedSchemaTypeId]?.group_applications
      : null) ?? [];
  $: availableGroupEntries = Object.entries(metadataSchema?.groups ?? {});
  $: schemaContextHeading =
    schemaFieldKind === "lore"
      ? "Lore Entry Types"
      : schemaFieldKind === "research"
        ? "Research Types"
        : schemaFieldKind === "prompt"
          ? "Prompt Types"
          : schemaFieldKind === "assistant"
            ? "Assistant Types"
            : schemaFieldKind === "project"
              ? "Project Types"
              : "Scene Types";

  // Persisted "what was open" — survives reload (HMR or browser refresh) so
  // the user doesn't lose their seat. Cleared on a failed re-open so a
  // moved/deleted folder doesn't keep erroring every load.
  const LAST_PROJECT_KEY = "lastOpenedProjectPath";

  function rememberLastProject(path: string): void {
    try {
      localStorage.setItem(LAST_PROJECT_KEY, path);
    } catch {
      // Storage disabled / quota — rehydrate just won't work; not fatal.
    }
  }

  function forgetLastProject(): void {
    try {
      localStorage.removeItem(LAST_PROJECT_KEY);
    } catch {
      // ignore
    }
  }

  function readLastProject(): string | null {
    try {
      return localStorage.getItem(LAST_PROJECT_KEY);
    } catch {
      return null;
    }
  }

  let cleanupThemeWiring: (() => void) | null = null;

  onMount(() => {
    fitPanesToViewport();
    cleanupThemeWiring = installThemeWiring();
    document.addEventListener("mousedown", handleDocumentMousedown);
    // Eagerly fetch machine settings so the chat panel and inputs dialog
    // can show the assistant roster without a round-trip when first opened.
    // Failure is non-fatal — both UIs fall back to "default assistant".
    void (async () => {
      await loadMachineSettings();
      // Auto-rehydrate the last-opened project so an HMR reload (or a
      // plain F5) doesn't drop the user back to "No project open." Run
      // after machine settings so recents are populated; on failure
      // (path moved / deleted) clear the key so next load starts fresh.
      // openProjectAt() routes errors through run() which swallows them
      // — verify success by checking appState afterwards rather than
      // relying on a thrown exception.
      const lastPath = readLastProject();
      if (lastPath) {
        await openProjectAt(lastPath);
        if (appState.name !== "projectOpen") {
          forgetLastProject();
        }
      }
    })();
    return () => {
      document.removeEventListener("mousemove", movePane);
      document.removeEventListener("mouseup", stopPaneDrag);
      document.removeEventListener("mousemove", resizePane);
      document.removeEventListener("mouseup", stopPaneResize);
      document.removeEventListener("mousedown", handleDocumentMousedown);
      cleanupThemeWiring?.();
    };
  });

  async function loadMachineSettings() {
    try {
      machineSettings = await api.getMachineSettings();
      recentProjects = machineSettings.recent_projects ?? [];
      defaultProjectsFolder = machineSettings.default_projects_folder ?? "";
      setPalette(machineSettings.palette ?? []);
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
      setPalette(view.palette ?? []);
    } catch {
      // Non-fatal — recents stays stale until next reload.
    }
  }

  function handleDocumentMousedown(event: MouseEvent) {
    const target = event.target as HTMLElement | null;
    const inAnchorOrPopover = target?.closest(".tree-menu-anchor, .row-add-popover");
    if (addMenuOpenFor !== null && !inAnchorOrPopover) {
      addMenuOpenFor = null;
      addMenuPosition = null;
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
      recentlySaved: false,
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
    _schemaTypePaneOpen,
    _promptsPaneOpen,
    _chatsPaneOpen,
    _editorPanes,
  ) => (id: PaneId): boolean => {
    if (id === "project") return true;
    if (id === "assistants") return _assistantsPaneOpen;
    if (!_isProjectOpen) return false;
    if (id === "research") return true;
    if (id === "schema") return _schemaPaneOpen;
    if (id === "schema_type") return _schemaTypePaneOpen;
    if (id === "prompts") return _promptsPaneOpen;
    if (id === "chats") return _chatsPaneOpen;
    return !isEditorPaneId(id) || _editorPanes.some((pane) => pane.id === id);
  })(
    isProjectOpen,
    assistantsPaneOpen,
    schemaPaneOpen,
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
    rememberLastProject(nextProject.root_path);
    projectPath = nextProject.root_path;
    collapsedStructureNodes = loadCollapsedStructureNodes(projectPath);
    projectTitle = nextProject.title;
    aiPolicy = nextProject.ai_policy;
    aiDefaultProvider = nextProject.ai_default_provider ?? "";
    aiDefaultModelClass = nextProject.ai_default_model_class ?? "";
    aiHealthResult = null;
    setProjectCost(null, []);
    projectCostExpanded = false;
    currentProjectColor = null;
    appState = { name: "projectOpen", project: nextProject };
    fitPanesToViewport();
    focusPane("outline");
    void hydrateChatSessionsForProject();
    void refreshProjectCost();
    void refreshCurrentProjectColor();
  }

  // Project-node color, surfaced on the top-bar switcher as a dot so the
  // user can tell at a glance which project they're in. Refreshed on
  // open + on save of the project node.
  let currentProjectColor: string | null = null;
  async function refreshCurrentProjectColor() {
    try {
      const node = await api.getProjectNode();
      const instance = typeof node?.metadata?.color === "string" ? node.metadata.color : null;
      const swatch = resolveColor(instance, node?.entry_type, "project", metadataSchema);
      currentProjectColor = swatch?.hex ?? null;
    } catch {
      currentProjectColor = null;
    }
  }

  async function refreshProjectCost(): Promise<void> {
    await storeRefreshProjectCost();
  }

  function resetEditorWorkspace() {
    editorPanes = [];
    setKnownTags([]);
    focusedEditorPaneId = null;
    nextEditorPaneIndex = 1;
    nextMetadataReloadToken = 1;
    metadataReloadsByPane = {};
    titleReloadsByPane = {};
    activeChatId = null;
    activeChatTitle = "Untitled chat";
    setChatSessions([]);
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

  // The shared chrome controller handed to every <Pane>. The handlers are
  // stable function declarations, so a plain object (not reactive) is fine.
  const paneChrome: PaneChrome = {
    focus: focusPane,
    headerKeydown: handlePaneHeaderKeydown,
    headerDrag: startPaneDrag,
    resizeKeydown: handlePaneResizeKeydown,
    resizeDrag: startPaneResize,
  };

  async function run(action: () => Promise<void>) {
    error = "";
    try {
      await action();
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
  }

  async function refreshStructure() {
    await storeRefreshStructure();
  }

  async function refreshResearchStructure() {
    await storeRefreshResearchStructure();
  }

  async function refreshLoreEntries() {
    await storeRefreshLoreEntries();
  }

  async function refreshPromptEntries() {
    await storeRefreshPromptEntries();
  }

  // Persist a within-layer assistant reorder computed by Assistants.svelte.
  // App owns assistantEntries (the chat pane reads it too), so the api call +
  // state update stay here; the drag UI lives in the component.
  async function reorderAssistantsInLayer(layerId: string, orderedIds: string[]) {
    await run(async () => {
      setAssistantEntries((await api.reorderAssistants(layerId, orderedIds)).entries);
    });
  }

  async function refreshAssistantEntries() {
    await storeRefreshAssistantEntries();
  }

  async function refreshKnownTags() {
    await storeRefreshKnownTags();
  }

  // A tag merge rewrites tag values across documents on disk; pull the new
  // tag roster AND re-sync the entry lists + open editors so the change is
  // reflected everywhere immediately (not just on next reload).
  async function refreshAfterTagChange() {
    await refreshKnownTags();
    await run(async () => {
      setLoreEntries((await api.listLoreEntries()).entries);
      setPromptEntries((await api.listPromptEntries()).entries);
      await refreshOpenEditorPaneBaselines();
    });
  }

  async function refreshTodos() {
    await storeRefreshTodos();
  }

  // Re-point the schema-authoring editor's selection at still-valid targets
  // after the schema store changes. App-local authoring state (not server-
  // mirrored). Reads the store live (get) — callers invoke it right after the
  // store set, where the `$:` aliases still lag a flush.
  function syncSchemaAuthoringSelection() {
    const schema = get(metadataSchemaStore);
    if (!schema) return;
    const layers = get(metadataSchemaLayersStore);
    if (!schema.entry_types[schemaFieldEntryType]) {
      schemaFieldEntryType = schema.entry_types.scene ? "scene" : Object.keys(schema.entry_types)[0] ?? "scene";
    }
    if (!schemaFieldLayerId || !layers.some((layer) => layer.id === schemaFieldLayerId)) {
      schemaFieldLayerId = projectSchemaLayerId();
    }
    if (!schemaTypeLayerId || !layers.some((layer) => layer.id === schemaTypeLayerId)) {
      schemaTypeLayerId = projectSchemaLayerId();
    }
  }

  async function refreshMetadataSchema() {
    await storeRefreshSchema();
    syncSchemaAuthoringSelection();
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
      await loadProjectData();
      syncSchemaAuthoringSelection();
      const initialSceneId = findFirstSceneId(get(structureStore)?.root);
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
      await loadProjectData();
      syncSchemaAuthoringSelection();
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
        palette: (machineSettings.palette ?? []).map((s) => ({ ...s })),
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
        palette: machineSettingsDraft!.palette,
      };
      machineSettings = await api.updateMachineSettings(update);
      recentProjects = machineSettings.recent_projects ?? [];
      defaultProjectsFolder = machineSettings.default_projects_folder ?? "";
      setPalette(machineSettings.palette ?? []);
      machineSettingsOpen = false;
      status = "Saved machine settings";
    });
  }

  // --- Chat sessions (Phase 4: ChatBodyView owns per-chat state) ---------
  //
  // App keeps the session roster (Chats pane) in sync and routes opens into
  // editor panes. Everything inside a conversation — history, composer,
  // streaming, cost/TTL, per-turn persistence — lives in ChatBodyView.

  async function refreshChatSessions() {
    await storeRefreshChatSessions();
  }

  // "+ New Chat": create an empty session and open it in an editor pane.
  async function createNewChatSession(): Promise<void> {
    try {
      const session = await api.createChatSession({});
      await refreshChatSessions();
      await openChatInEditorPane(session.id);
    } catch (e) {
      error = `Couldn't create chat: ${(e as Error).message}`;
    }
  }

  // "Invoke chat prompt" from a prose scene: ProseBodyView emits open-chat
  // once its inputs dialog resolves. Create a prompt-bound chat session
  // tied to the originating scene (so the first-send render resolves the
  // `scene` binding), seed the resolved inputs as drafts so the user's
  // dialog entries carry over, and open it in an editor pane.
  async function openChatFromPromptEntry(
    entry: PromptEntrySummary,
    inputs: Record<string, unknown>,
    sceneId: string | null,
    assistantId: string = "",
  ): Promise<void> {
    await run(async () => {
      const session = await api.createChatSession({
        prompt_entry_id: entry.id,
        assistant_id: assistantId,
        title: entry.title,
        target_scene_id: sceneId ?? "",
      });
      if (Object.keys(inputs).length > 0) {
        // Persist resolved inputs via the unified node path so ChatBodyView
        // restores them as drafts on load. Echo target_scene_id so it's
        // never dropped (backend also falls back to the persisted value).
        await api.saveNode<ChatSession>(session.id, {
          title: session.title,
          prompt_entry_id: session.prompt_entry_id,
          assistant_id: session.assistant_id,
          system_prompt: session.system_prompt,
          target_scene_id: session.target_scene_id ?? "",
          pinned: session.pinned,
          context_items: [],
          messages: [],
          inputs,
        });
      }
      await refreshChatSessions();
      await openChatInEditorPane(session.id);
      status = `Opened ${entry.title} as a chat`;
    });
  }

  async function deleteChatSessionFromPane(chatId: string): Promise<void> {
    try {
      const listing = await api.deleteChatSession(chatId);
      setChatSessions(listing.sessions);
      if (activeChatId === chatId) {
        activeChatId = null;
        activeChatTitle = "Untitled chat";
      }
      // Tear down any editor pane still pointing at the deleted chat.
      for (const pane of editorPanes.filter(
        (candidate) => candidate.document?.type === "chat" && candidate.document.id === chatId,
      )) {
        tearDownEditorPane(pane.id);
      }
    } catch (e) {
      error = `Couldn't delete chat: ${(e as Error).message}`;
    }
  }

  async function hydrateChatSessionsForProject(): Promise<void> {
    await refreshChatSessions();
    if (get(chatSessionsStore).length === 0) {
      // Auto-create a first chat so the Chats pane always has somewhere to
      // write. Don't auto-open it — chats open into editor panes on demand.
      try {
        await api.createChatSession({});
        await refreshChatSessions();
      } catch {
        // Backend may be offline at boot — leave the list empty; the user
        // can retry via + New Chat.
      }
    }
  }

  function titleMatchesQuery(title: string, query: string): boolean {
    const q = query.trim().toLowerCase();
    if (!q) return true;
    return title.toLowerCase().includes(q);
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
    // Read the store live — called from refreshMetadataSchema's fallback right
    // after the store set, where the `$:` alias still lags a flush.
    const layers = get(metadataSchemaLayersStore);
    return layers[layers.length - 1]?.id ?? "";
  }

  function layerLabel(layerId: string | undefined | null) {
    if (!layerId) return "Unknown";
    if (layerId === "built_in") return "Built-in";
    return metadataSchemaLayers.find((layer) => layer.id === layerId)?.label ?? "Unknown";
  }

  // Derived in the assistants store (not a function): consumers pass it as a
  // prop, and a bare call in a prop expression wouldn't track its inner roster
  // dependency. See feedback_svelte5_reactivity_traps.
  $: defaultAssistantId = $defaultAssistantIdStore;

  // Set of "<docType>:<id>" keys for every node currently open in a
  // pinned editor pane. Derived reactively so the template can ask
  // `pinnedEditorPaneKeys.has(\`lore:${entry.id}\`)` and have Svelte
  // re-evaluate the binding when any pane's .pinned flips. (A plain
  // `function editorPanePinnedFor(...)` doesn't track editorPanes
  // when called inside a template prop binding — Svelte 5 legacy
  // reactivity only tracks deps read directly in the expression.)
  $: pinnedEditorPaneKeys = new Set<string>(
    editorPanes
      .filter((pane) => pane.pinned && pane.document)
      .map((pane) => `${pane.document!.type}:${pane.document!.id}`),
  );
  // Write-through to the editor-focus store (read by the list panes' pin-star).
  $: pinnedKeysStore.set(pinnedEditorPaneKeys);

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

  // Fields this type inherits from its parent/kind — present in `fields`
  // but not in `own_fields`. Rendered dimmed (read-only) in the type
  // editor with a jump-to-parent affordance (metadata revision, mockup B).
  function inheritedFieldEntriesForEntryType(entryTypeId: string) {
    const entryType = metadataSchema?.entry_types[entryTypeId];
    if (!entryType || !Array.isArray(entryType.own_fields)) return [];
    const own = new Set(entryType.own_fields);
    return (entryType.fields ?? [])
      .filter((fieldId) => !own.has(fieldId))
      .map((fieldId) => {
        const field = metadataSchema?.fields[fieldId];
        return field ? ([fieldId, field] as [string, MetadataFieldDefinition]) : null;
      })
      .filter((entry): entry is [string, MetadataFieldDefinition] => Boolean(entry));
  }

  function schemaTypeSource(typeId: string | null) {
    return typeId ? metadataSchemaOverview?.entry_type_sources[typeId] : null;
  }

  // The field types offered in the inline type grid, in display order.
  // `date` is intentionally omitted (see decisions-field-types). Each cell
  // shows the type's default glyph + label.
  // Switch the field type from the grid; keeps config state coherent so the
  // type-specific blocks below show sane defaults when first revealed.
  // Open the inline editor on an existing field. App sets only the editing
  // CONTEXT (which field, its source layer, read-only-ness, target entry type)
  // — SchemaFieldInlineEditor initializes its own draft from the field def it
  // receives as a prop (#14 Step 4).
  function openSchemaFieldDetail(fieldId: string, entryTypeId = schemaFieldEntryType) {
    const field = metadataSchema?.fields[fieldId];
    if (!field) return;
    const targetEntryTypeId = fieldAppliesToEntryType(fieldId, entryTypeId)
      ? entryTypeId
      : (entryTypeIdsForField(fieldId, schemaFieldKind)[0] ?? defaultSchemaEntryType(schemaFieldKind));
    selectedSchemaFieldId = fieldId;
    schemaFieldReadonly = Boolean(metadataSchemaOverview?.field_sources[fieldId]?.built_in);
    schemaFieldLayerId = metadataSchemaOverview?.field_sources[fieldId]?.built_in ? projectSchemaLayerId() : (metadataSchemaOverview?.field_sources[fieldId]?.layer_id ?? projectSchemaLayerId());
    schemaFieldEntryType = targetEntryTypeId;
    expandedSchemaFieldId = fieldId;
  }

  function createSchemaFieldDraft(layerId = projectSchemaLayerId(), entryTypeId = schemaFieldEntryType) {
    selectedSchemaFieldId = null;
    schemaFieldReadonly = false;
    schemaFieldLayerId = layerId;
    schemaFieldEntryType = entryTypeId;
    expandedSchemaFieldId = NEW_FIELD_SENTINEL;
  }

  // Toggle a field row's inline editor (one open at a time).
  function toggleSchemaFieldInline(fieldId: string, entryTypeId: string) {
    if (expandedSchemaFieldId === fieldId) {
      expandedSchemaFieldId = null;
      return;
    }
    openSchemaFieldDetail(fieldId, entryTypeId);
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
    schemaTypeColor = null;
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
    // Show own-color (pre-inheritance). null = "inherit from parent",
    // which the SwatchPicker renders as the "None" cell.
    schemaTypeColor = entryType.own_color ?? null;
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

  function defaultSchemaParentType(kind: SchemaKind) {
    if (kind === "lore" && metadataSchema?.entry_types.lore_entry) return "lore_entry";
    if (kind === "prompt" && metadataSchema?.entry_types.prompt) return "prompt";
    if (kind === "research" && metadataSchema?.entry_types.research) return "research";
    return "";
  }

  function openSchemaForCustomData(entryType: string, kind: DocumentKind) {
    // Phase B: the entry editor's "Edit type…" button now opens ONLY the
    // per-type editor (schema_type pane) — not the schema/tree hierarchy
    // view. Tree access is the top bar's "Detail Types" button.
    // The dispatched DocumentKind is wider than the schema's kind universe
    // (it includes chat / snippet / structure_node — none of which have
    // their own schema-type tree); narrow before consulting the schema.
    if (kind !== "scene" && kind !== "lore" && kind !== "research" && kind !== "prompt" && kind !== "assistant" && kind !== "project") return;
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
  function switchSchemaKind(kind: SchemaKind) {
    schemaFieldEntryType = defaultSchemaEntryType(kind);
  }

  function defaultSchemaEntryType(kind: SchemaKind) {
    const fallback = kind === "lore" ? "lore_note" : kind === "research" ? "note" : kind === "prompt" ? "prompt" : kind === "assistant" ? "assistant" : kind === "project" ? "project" : "scene";
    return Object.entries(metadataSchema?.entry_types ?? {}).find(([, definition]) => definition.kind === kind)?.[0] ?? fallback;
  }

  function entryTypeIdsForField(fieldId: string, kind: SchemaKind) {
    return Object.entries(metadataSchema?.entry_types ?? {})
      .filter(([, definition]) => definition.kind === kind && definition.fields.includes(fieldId))
      .map(([typeId]) => typeId);
  }

  function closeSchemaPane(id: "schema" | "schema_type" | "prompts" | "assistants" | "chats") {
    if (id === "schema") schemaPaneOpen = false;
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
      setMetadataSchema(await api.upsertMetadataEntryType(
        source.layer_id,
        typeId,
        {
          ...entryType,
          parent: parentTypeId,
        },
        true,
      ));
      await refreshMetadataSchema();
      setValidation(await api.validateProject());
      selectedSchemaTypeId = typeId;
      status = `Moved ${entryType.name} under ${parentType.name}`;
    });
  }

  // Coerce the editor-side string default onto the field-type's wire shape
  // (#38). Mirrors NodeEditor.defaultValueForStorage for prompt inputs;
  // returns undefined for empty (no default) and computed types.
  function schemaFieldDefaultForStorage(
    type: MetadataFieldType,
    raw: string | undefined,
  ): import("./types").MetadataValue | undefined {
    if (raw === undefined || raw === "") return undefined;
    if (type === "boolean") return raw === "true";
    if (type === "number") {
      const n = Number(raw);
      return Number.isFinite(n) ? n : raw;
    }
    return raw;
  }

  // The draft arrives assembled from SchemaFieldInlineEditor (#14 Step 4); App
  // owns the persistence (option migration, removed-value confirm, rename,
  // refresh) plus the editing context (layer / entry-type / previous id).
  async function saveSchemaField(payload: FieldDraftPayload) {
    if (!schemaFieldLayerId) return;
    const layerId = schemaFieldLayerId;
    const entryType = schemaFieldEntryType;
    const previousFieldId = selectedSchemaFieldId && !selectedSchemaFieldId.startsWith("system:") ? selectedSchemaFieldId : null;
    const nextFieldId = payload.id.trim();
    // Compose SelectOption objects from the ordered draft list (order is
    // preserved on save). Drop rows with an empty value; de-dupe by value.
    const seenValues = new Set<string>();
    const options = payload.options
      .map((draft) => ({ ...draft, value: draft.value.trim() }))
      .filter((draft) => draft.value && !seenValues.has(draft.value) && seenValues.add(draft.value))
      .map((draft) => {
        const out: import("./types").SelectOption = { value: draft.value };
        const label = draft.label.trim();
        // Only persist a label when it differs from the stable value
        // (label is cosmetic; value is the macro contract).
        if (label && label !== draft.value) out.label = label;
        if (draft.color) out.color = draft.color;
        return out;
      });
    // Migration: a row whose value changed from its loaded `originalValue`
    // rewrites stored entry data. Reorder-safe (keyed by originalValue, not
    // position); added rows have no originalValue so they never migrate.
    const optionMigration = buildOptionMigrationFromDrafts(payload.options);
    const hasOptions = payload.type === "select" || payload.type === "multi_select";
    const hasPicker = payload.type === "entity_ref" || payload.type === "entity_ref_list";
    const computedSpec: Record<string, string> | null =
      payload.type === "computed"
        ? payload.computedFunction === "word_count"
          ? { source: "body", function: "word_count" }
          : { function: "counter", scope: payload.computedScope }
        : null;
    // Coerce the editor-side string default into the field-type's wire shape
    // (#38). Computed fields never carry a default. undefined / "" → omit
    // the key entirely so the field stays defaultless rather than seeding
    // a falsy value into new entries.
    const defaultValue =
      payload.type === "computed" ? undefined : schemaFieldDefaultForStorage(payload.type, payload.defaultValue);
    const nextField: MetadataFieldDefinition = {
      name: payload.name.trim() || nextFieldId,
      type: payload.type,
      options: hasOptions ? options : [],
      ...(hasPicker ? { picker_config: payload.pickerConfig } : {}),
      ...(computedSpec ? { computed: computedSpec } : {}),
      ...(payload.group.trim() ? { group: payload.group.trim() } : {}),
      // Per-field icon override (chosen in the IconPicker). null/empty =
      // fall back to the field-type default glyph.
      ...(payload.icon ? { icon: payload.icon } : {}),
      ...(defaultValue !== undefined ? { default: defaultValue } : {}),
    };

    // Detect option values that are being removed (present before, gone now,
    // and not a rename source) — those get cleared from existing documents.
    const previousField = previousFieldId ? metadataSchema?.fields[previousFieldId] : null;
    const newValueSet = new Set(options.map((o) => o.value));
    const renameKeys = new Set(Object.keys(optionMigration ?? {}));
    const removedValues = hasOptions && previousField && (previousField.type === "select" || previousField.type === "multi_select")
      ? previousField.options.map((o) => o.value).filter((v) => !newValueSet.has(v) && !renameKeys.has(v))
      : [];

    const persist = () => persistSchemaField({ layerId, entryType, previousFieldId, nextFieldId, nextField, optionMigration });

    if (removedValues.length > 0) {
      requestConfirm({
        title: removedValues.length > 1 ? "Remove these option values?" : "Remove this option value?",
        message: `Removing ${removedValues.join(", ")} will clear ${removedValues.length > 1 ? "them" : "it"} from every document that currently uses ${removedValues.length > 1 ? "them" : "it"}.`,
        confirmLabel: "Remove & save",
        destructive: true,
        cannotBeUndone: true,
        dontShowAgainKey: "removeSelectOptions",
        onConfirm: persist,
      });
    } else {
      await run(persist);
    }
  }

  async function persistSchemaField(args: {
    layerId: string;
    entryType: string;
    previousFieldId: string | null;
    nextFieldId: string;
    nextField: MetadataFieldDefinition;
    optionMigration: Record<string, string> | null;
  }) {
    const { layerId, entryType, previousFieldId, nextFieldId, nextField, optionMigration } = args;
    if (previousFieldId && previousFieldId !== nextFieldId) {
      await api.renameMetadataField(previousFieldId, nextFieldId, entryType);
    }
    setMetadataSchema(await api.upsertMetadataField(layerId, nextFieldId, nextField, entryType, Boolean(previousFieldId), optionMigration));
    await refreshMetadataSchema();
    if (previousFieldId) {
      // The backend rewrote entry data on disk (key rename + option
      // rename/removal); re-pull open panes so they reflect the cleaned data.
      await refreshOpenEditorPaneBaselines();
    }
    setValidation(await api.validateProject());
    selectedSchemaFieldId = nextFieldId;
    // Collapse the inline editor on a successful save.
    expandedSchemaFieldId = null;
    status = "Updated details schema";
  }

  async function applyGroupToType() {
    if (!selectedSchemaTypeId || !applyGroupId) return;
    const typeId = selectedSchemaTypeId;
    const application = {
      group_id: applyGroupId,
      label: applyGroupLabel.trim(),
      key_prefix: (applyGroupPrefix.trim() || suggestPrefixFromLabel(applyGroupLabel) || `${applyGroupId}_`),
    };
    await run(async () => {
      setMetadataSchema(await api.setEntryTypeGroupApplications(
        schemaTypeLayerId || projectSchemaLayerId(),
        typeId,
        [...typeGroupApplications, application],
      ));
      await refreshMetadataSchema();
      setValidation(await api.validateProject());
      groupApplyOpen = false;
      applyGroupId = "";
      applyGroupLabel = "";
      applyGroupPrefix = "";
      status = "Applied group";
    });
  }

  async function removeGroupApplication(index: number) {
    if (!selectedSchemaTypeId) return;
    const typeId = selectedSchemaTypeId;
    const next = typeGroupApplications.filter((_, i) => i !== index);
    await run(async () => {
      setMetadataSchema(await api.setEntryTypeGroupApplications(
        schemaTypeLayerId || projectSchemaLayerId(),
        typeId,
        next,
      ));
      await refreshMetadataSchema();
      setValidation(await api.validateProject());
      status = "Removed group application";
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
        color: schemaTypeColor || null,
        ...(schemaTypeKind === "prompt" ? { prompt: promptExtras } : {}),
      };
      if (previousTypeId && previousTypeId !== nextTypeId) {
        status = "Renaming detail types is not available yet";
        return;
      }
      setMetadataSchema(await api.upsertMetadataEntryType(schemaTypeLayerId, nextTypeId, nextType, Boolean(previousTypeId)));
      await refreshMetadataSchema();
      setValidation(await api.validateProject());
      selectedSchemaTypeId = nextTypeId;
      schemaFieldEntryType = nextTypeId;
      status = "Updated detail type";
    });
  }

  function requestDeleteSchemaType(typeId: string) {
    const definition = metadataSchema?.entry_types[typeId];
    if (!definition) return;
    const source = schemaTypeSource(typeId);
    if (source?.built_in) return;
    const typeName = definition.name || typeId;
    requestConfirm({
      title: "Delete Detail Type",
      message: `Delete "${typeName}"? Existing documents using this type must be changed first.`,
      confirmLabel: "Delete Type",
      destructive: true,
      cannotBeUndone: true,
      dontShowAgainKey: "deleteType",
      onConfirm: () => deleteSchemaType(typeId),
    });
  }

  async function deleteSchemaType(typeId: string) {
    const deletedKind = schemaFieldKind;
    setMetadataSchema(await api.deleteMetadataEntryType(typeId));
    await refreshMetadataSchema();
    setValidation(await api.validateProject());
    selectedSchemaTypeId = null;
    schemaTypePaneOpen = false;
    if (schemaFieldEntryType === typeId || !metadataSchema?.entry_types[schemaFieldEntryType]) {
      schemaFieldEntryType = defaultSchemaEntryType(deletedKind);
    }
    status = `Deleted ${typeId}`;
  }

  function requestDeleteSchemaField() {
    if (!selectedSchemaFieldId || selectedSchemaFieldId.startsWith("system:") || schemaFieldReadonly) return;
    const fieldName = metadataSchema?.fields[selectedSchemaFieldId]?.name || selectedSchemaFieldId;
    requestConfirm({
      title: "Delete Detail Field",
      message: `Delete "${fieldName}"? This removes the field definition and removes that metadata value from every document using it.`,
      confirmLabel: "Delete Field",
      destructive: true,
      cannotBeUndone: true,
      dontShowAgainKey: "deleteField",
      onConfirm: () => deleteSchemaField(selectedSchemaFieldId!),
    });
  }

  async function deleteSchemaField(fieldId: string) {
    setMetadataSchema(await api.deleteMetadataField(fieldId, schemaFieldEntryType));
    await refreshMetadataSchema();
    await refreshOpenEditorPaneBaselines((metadata) => removeMetadataKey(metadata, fieldId));
    setValidation(await api.validateProject());
    selectedSchemaFieldId = null;
    expandedSchemaFieldId = null;
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

  // Migration from the option draft list: a row whose value changed from the
  // value it was loaded with rewrites stored entry data. Keyed by the loaded
  // `originalValue`, so reordering rows never produces a spurious migration,
  // and freshly-added rows (originalValue null) never migrate.
  function buildOptionMigrationFromDrafts(drafts: OptionDraft[]): Record<string, string> | null {
    const migration: Record<string, string> = {};
    for (const draft of drafts) {
      const value = draft.value.trim();
      if (draft.originalValue && value && draft.originalValue !== value) {
        migration[draft.originalValue] = value;
      }
    }
    return Object.keys(migration).length > 0 ? migration : null;
  }

  // Shared drop-position helper: before/after based on cursor vs row midpoint.
  // Mirrors the NodeRow tree-drag marker so every reorderable list reads the
  // same way (a 2px accent insertion line; see .drop-before/.drop-after CSS).
  function dropPositionFromEvent(event: DragEvent): "before" | "after" {
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    return event.clientY < rect.top + rect.height / 2 ? "before" : "after";
  }
  // Reorder helper: move `fromId`/index to before/after `toId`/index.
  function reorderByPosition<T>(list: T[], from: number, to: number, position: "before" | "after"): T[] {
    if (from < 0 || to < 0) return list;
    const next = [...list];
    const [moved] = next.splice(from, 1);
    let insertAt = to > from ? to - 1 : to;
    if (position === "after") insertAt += 1;
    next.splice(insertAt, 0, moved);
    return next;
  }

  // --- Field row drag-reorder (own fields of a type) -----------------------
  let fieldDragId: string | null = null;
  let fieldDropTarget: { id: string; position: "before" | "after" } | null = null;
  function onFieldDragStart(fieldId: string) {
    fieldDragId = fieldId;
  }
  function onFieldDragOver(event: DragEvent, fieldId: string) {
    if (!fieldDragId || fieldId === fieldDragId) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    fieldDropTarget = { id: fieldId, position: dropPositionFromEvent(event) };
  }
  function clearFieldDrag() {
    fieldDragId = null;
    fieldDropTarget = null;
  }
  async function onFieldDrop(targetFieldId: string) {
    const draggedId = fieldDragId;
    const position = fieldDropTarget?.position ?? "before";
    clearFieldDrag();
    if (!draggedId || draggedId === targetFieldId || !selectedSchemaTypeId) return;
    const current = typeOwnFieldEntries.map(([id]) => id);
    const order = reorderByPosition(current, current.indexOf(draggedId), current.indexOf(targetFieldId), position);
    if (order.join(" ") === current.join(" ")) return;
    const layerId = schemaTypeLayerId || projectSchemaLayerId();
    await run(async () => {
      // Reorder is layer-invariant: the backend guard requires an existing
      // override at this layer, so it can't change the overview's
      // field_sources / entry_type_sources / layers. Write through the new
      // effective schema and re-validate the authoring selection locally —
      // no overview refetch needed (the only schema site where that holds).
      setMetadataSchema(await api.setEntryTypeFieldOrder(layerId, selectedSchemaTypeId!, order));
      syncSchemaAuthoringSelection();
      status = "Reordered fields";
    });
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

  function defaultChildEntryType(parentType: string): string | null {
    if (parentType === "root") return "act";
    if (parentType === "act") return "chapter";
    if (parentType === "chapter") return "scene";
    return null;
  }

  async function openResearchNoteInEditorPane(noteId: string) {
    const existingPane = editorPanes.find((pane) => pane.document?.type === "research" && pane.document.id === noteId);
    if (existingPane) {
      focusedEditorPaneId = existingPane.id;
      focusPane(existingPane.id);
      status = `Focused ${existingPane.scene?.title ?? "open note"}`;
      return;
    }

    let targetPane = editorPanes.find((pane) => !pane.pinned);
    if (!targetPane) {
      targetPane = addEditorPane();
    }

    if (targetPane.dirty) {
      await saveEditorPane(targetPane.id);
    }

    const note = await api.getResearchNote(noteId);
    editorPanes = editorPanes.map((pane) =>
      pane.id === targetPane.id
        ? {
            ...pane,
            document: { type: "research", id: note.id },
            scene: note,
            dirty: false,
            draftTitle: note.title,
            draftMarkdown: note.body,
            draftStatus: "",
            draftEntryType: note.entry_type,
            draftMetadata: cloneMetadata(note.metadata),
            saving: false,
            recentlySaved: false,
          }
        : pane,
    );
    focusedEditorPaneId = targetPane.id;
    focusPane(targetPane.id);
    status = `Loaded ${note.title}`;
  }

  // Slice 5: migrate a single lore_note to a research/note. Confirms
  // before running because the v1 note schema is minimal — aliases /
  // related_entries / context_policy on the source are intentionally
  // dropped. The cascade preview surfaces what'll be lost so the user
  // can cancel.
  async function requestMoveLoreNoteToResearch(entry: LoreEntrySummary) {
    const droppable: string[] = [];
    const meta = entry.metadata ?? {};
    if (Array.isArray(meta.aliases) && meta.aliases.length > 0) droppable.push("aliases");
    if (Array.isArray(meta.related_entries) && meta.related_entries.length > 0) droppable.push("related_entries");
    if (typeof meta.context_policy === "string" && meta.context_policy && meta.context_policy !== "auto") {
      droppable.push("context_policy");
    }
    const cascadeNote = droppable.length > 0
      ? `\n\nThe following metadata will be dropped (research notes only carry title + body + tags): ${droppable.join(", ")}.`
      : "";
    confirmation = {
      title: "Move to Research",
      message: `Move "${entry.title}" out of Lore and into the Research tree?${cascadeNote}`,
      details: [],
      confirmLabel: "Move to Research",
      destructive: droppable.length > 0,
      onConfirm: async () => {
        // Close the lore entry's editor pane first so it doesn't dangle
        // on a deleted file. The new research note will open in its own
        // pane after the migration.
        editorPanes.forEach((pane) => {
          if (pane.document?.type === "lore" && pane.document.id === entry.id) {
            tearDownEditorPane(pane.id);
          }
        });
        await run(async () => {
          const result = await api.moveLoreNoteToResearch(entry.id);
          setLoreEntries(result.lore.entries);
          setResearchStructure(result.tree);
          // Open the new note in the editor so the user sees the result.
          await openResearchNoteInEditorPane(result.note_id);
          status = result.dropped_fields.length > 0
            ? `Moved "${entry.title}" to Research (dropped ${result.dropped_fields.join(", ")})`
            : `Moved "${entry.title}" to Research`;
        });
      },
    };
  }


  // Tree configs — the per-kind contract consumed by Tree.svelte. Function
  // declarations referenced below are hoisted. App keeps these (plus the
  // delete/collapse/dblclick callbacks they wire) because they touch
  // editor-pane and persisted-collapse state that lives here.
  const manuscriptTree: TreeConfig = {
    kind: "scene",
    leafType: "scene",
    getStructure: () => get(structureStore),
    applyStructure: (next) => { setStructure(next); },
    refresh: refreshStructure,
    api: {
      create: api.createStructureNode.bind(api),
      rename: api.renameStructureNode.bind(api),
      move: api.moveStructureNode.bind(api),
      cascadePreview: api.cascadeDeletePreview.bind(api),
      delete: api.deleteStructureNode.bind(api),
    },
    openLeaf: (sceneId) => openSceneInEditorPane(sceneId),
    onGroupClick: (nodeId) => deferStructureNodeCollapse(nodeId),
    onGroupDblClick: (nodeId) => handleStructureNodeDblClick(nodeId),
    cascadeLabels: {
      leaf: { singular: "scene", plural: "scenes" },
      container: { singular: "sub-container", plural: "sub-containers" },
    },
    afterDelete: () => refreshTodos(),
    afterRename: (nodeId, title) => syncRenameIntoEditorPanes(nodeId, title),
    supportsDrag: true,
    showStatusStripe: true,
    containerHasEditor: true,
    inlineRenameOnLeafCreate: true,
    rootAddMenuKey: "__root__",
  };

  const researchTree: TreeConfig = {
    kind: "research",
    leafType: "note",
    getStructure: () => get(researchStructureStore),
    applyStructure: (next) => { setResearchStructure(next); },
    refresh: refreshResearchStructure,
    api: {
      create: api.createResearchNode.bind(api),
      rename: api.renameResearchNode.bind(api),
      cascadePreview: api.cascadeResearchDeletePreview.bind(api),
      delete: api.deleteResearchNode.bind(api),
    },
    openLeaf: (sceneId) => openResearchNoteInEditorPane(sceneId),
    onGroupClick: (nodeId) => {
      collapsedResearchNodes = {
        ...collapsedResearchNodes,
        [nodeId]: !collapsedResearchNodes[nodeId],
      };
    },
    // Research has no container editor to open, so a group double-click renames.
    groupDblClickRenames: true,
    cascadeLabels: {
      leaf: { singular: "note", plural: "notes" },
      container: { singular: "topic", plural: "topics" },
    },
    supportsDrag: false,
    showStatusStripe: false,
    containerHasEditor: false,
    inlineRenameOnLeafCreate: false,
    rootAddMenuKey: "__research_root__",
  };

  // Generic cascade-delete confirmation. Manuscript and research differ
  // only in noun choice ("scene"/"sub-container" vs "note"/"topic"), so
  // config.cascadeLabels covers it. The actual delete fans out through
  // performTreeDelete, which closes any editor panes that point at the
  // doomed subtree before calling the kind-specific delete API.
  async function requestDeleteTreeNode(config: TreeConfig, node: StructureNode) {
    let preview: StructureNodeDeletePreview | null = null;
    try {
      preview = await config.api.cascadePreview(node.id);
    } catch (error) {
      console.warn("Failed to fetch cascade preview", error);
    }
    const typeName = entryTypeName(node.type, metadataSchema);
    const leafCount = preview?.descendant_scene_count ?? 0;
    const containerCount = preview?.descendant_container_count ?? 0;
    const leafLabels = config.cascadeLabels.leaf;
    const containerLabels = config.cascadeLabels.container;
    const cascadeParts: string[] = [];
    if (leafCount > 0) cascadeParts.push(`${leafCount} ${leafCount === 1 ? leafLabels.singular : leafLabels.plural}`);
    if (containerCount > 0) cascadeParts.push(`${containerCount} ${containerCount === 1 ? containerLabels.singular : containerLabels.plural}`);
    const backlinks = preview?.backlinks ?? [];

    let message = `Delete ${typeName} "${node.title}"?`;
    if (cascadeParts.length > 0) {
      message += `\n\nThis will also permanently remove ${cascadeParts.join(" and ")} inside it.`;
    } else if (node.scene_id) {
      message += ` This removes the ${leafLabels.singular} file from the project.`;
    } else {
      message += ` This removes the ${containerLabels.singular} from the project.`;
    }
    if (backlinks.length > 0) {
      message += `\n\n${backlinks.length} ${backlinks.length === 1 ? "entry references" : "entries reference"} content that will be deleted — those links will break:`;
    }

    confirmation = {
      title: `Delete ${typeName}`,
      message,
      details: backlinks.map((link) => `${link.title} — ${link.field_name}`),
      confirmLabel: `Delete ${typeName}`,
      destructive: true,
      onConfirm: () => performTreeDelete(config, node),
    };
  }

  async function performTreeDelete(config: TreeConfig, node: StructureNode) {
    // Close editor panes whose underlying leaf is doomed before the API
    // call so the panes don't dangle on a missing scene/note.
    const doomedSceneIds = collectSceneIdSet(node);
    editorPanes.forEach((pane) => {
      if (
        pane.scene
        && pane.document?.type === config.kind
        && doomedSceneIds.has(pane.scene.id)
      ) {
        tearDownEditorPane(pane.id);
      }
    });
    if (config.containerHasEditor) {
      // Manuscript Acts/Chapters can open as structure_node editor panes
      // — close those too if their node id falls inside the doomed subtree.
      const doomedNodeIds = collectNodeIdSet(node);
      editorPanes.forEach((pane) => {
        if (pane.document?.type === "structure_node" && doomedNodeIds.has(pane.document.id)) {
          tearDownEditorPane(pane.id);
        }
      });
    }
    const next = await config.api.delete(node.id);
    config.applyStructure(next);
    if (config.afterDelete) {
      await config.afterDelete();
    }
    status = "Deleted";
  }

  function toggleAddMenu(nodeId: string, event?: MouseEvent) {
    if (addMenuOpenFor === nodeId) {
      addMenuOpenFor = null;
      addMenuPosition = null;
      return;
    }
    addMenuOpenFor = nodeId;
    const anchor = event?.currentTarget;
    if (anchor instanceof HTMLElement) {
      const rect = anchor.getBoundingClientRect();
      // The popover anchors to the button's right edge and drops below.
      // If there isn't room below (less than 200px before the viewport
      // bottom), flip above the button instead.
      const popoverHeight = 180;
      const fitsBelow = window.innerHeight - rect.bottom > popoverHeight;
      addMenuPosition = {
        top: fitsBelow ? rect.bottom + 4 : rect.top - popoverHeight - 4,
        right: window.innerWidth - rect.right,
      };
    } else {
      addMenuPosition = null;
    }
  }

  // Tree.svelte's add menus close through this so its open/position state
  // (kept here, shared across both trees + closed by the document-level
  // click-outside handler) stays the single source of truth.
  function closeAddMenu() {
    addMenuOpenFor = null;
    addMenuPosition = null;
  }

  async function syncRenameIntoEditorPanes(nodeId: string, newTitle: string) {
    if (!structure) return;
    const renamedNode = findStructureNodeById(structure.root, nodeId);
    if (!renamedNode?.scene_id) return;
    const sceneId = renamedNode.scene_id;
    // The rename rewrote the scene file's front-matter, bumping the
    // mtime-derived revision. Any open editor pane still holds the
    // pre-rename revision; the next save would 409. Refetch the scene
    // for its new revision string. The user's in-progress body lives
    // on pane.draftMarkdown — we only swap revision (and title, which
    // we already set above) into pane.scene.
    let refreshedRevision: string | null = null;
    try {
      const refreshed = await api.getScene(sceneId);
      refreshedRevision = refreshed.revision;
    } catch (e) {
      // Pane closed or scene gone — fall through; nothing to sync.
    }
    const nextReloads = { ...titleReloadsByPane };
    editorPanes = editorPanes.map((pane) => {
      if (!pane.scene || pane.scene.id !== sceneId) return pane;
      const nextScene = {
        ...pane.scene,
        title: newTitle,
        ...(refreshedRevision !== null ? { revision: refreshedRevision } : {}),
      };
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

  function toggleStructureNodeCollapse(nodeId: string) {
    collapsedStructureNodes = {
      ...collapsedStructureNodes,
      [nodeId]: !collapsedStructureNodes[nodeId],
    };
    saveCollapsedStructureNodes(projectPath, collapsedStructureNodes);
  }

  // Tree-row click → defer the collapse toggle past the browser's dblclick
  // recognition window so a fast second click can cancel it and open the
  // editor instead. Without the defer the user sees the row visibly toggle
  // collapsed-state for ~100ms before the editor opens on top.
  const DBLCLICK_GUARD_MS = 300;
  let pendingCollapseTimeoutId: ReturnType<typeof setTimeout> | null = null;

  function deferStructureNodeCollapse(nodeId: string) {
    if (pendingCollapseTimeoutId !== null) {
      clearTimeout(pendingCollapseTimeoutId);
    }
    pendingCollapseTimeoutId = setTimeout(() => {
      pendingCollapseTimeoutId = null;
      toggleStructureNodeCollapse(nodeId);
    }, DBLCLICK_GUARD_MS);
  }

  function handleStructureNodeDblClick(nodeId: string) {
    if (pendingCollapseTimeoutId !== null) {
      clearTimeout(pendingCollapseTimeoutId);
      pendingCollapseTimeoutId = null;
    }
    void run(() => openStructureNodeInEditorPane(nodeId));
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
              draftMarkdown: node.body,
              draftStatus: "",
              draftEntryType: node.entry_type,
              draftMetadata: cloneMetadata(node.metadata as EntryMetadata),
              saving: false,
              recentlySaved: false,
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
            draftMarkdown: scene.body,
            draftStatus: scene.status,
            draftEntryType: scene.entry_type,
            draftMetadata: cloneMetadata(scene.metadata),
            saving: false,
            recentlySaved: false,
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

  // Opens a manuscript-tree structure node (Act, Chapter, leaf-Scene-as-
  // node) in an editor pane. Mirrors the universal model: every NodeRow
  // opens its node's editor on double-click, regardless of whether the
  // node has children. For now the editor is title-only — body and
  // user-metadata for structure nodes are a follow-up; renames go
  // through api.renameStructureNode in saveEditorPane.
  async function openStructureNodeInEditorPane(nodeId: string) {
    const existingPane = editorPanes.find(
      (pane) => pane.document?.type === "structure_node" && pane.document.id === nodeId,
    );
    if (existingPane) {
      focusedEditorPaneId = existingPane.id;
      focusPane(existingPane.id);
      status = `Focused ${existingPane.scene?.title ?? "structure node"}`;
      return;
    }
    if (!structure) return;
    const node = findStructureNodeById(structure.root, nodeId);
    if (!node) return;
    // Acts/Chapters are kind="scene" with a different entry_type — their
    // metadata + body + status live in the underlying scene .md file, so
    // fetch it and round-trip via the regular scene endpoints. document.id
    // stays the node id (the open-pane lookup matches on it); pane.scene
    // carries the real Scene so saveEditorPane's structure_node branch can
    // hand the right base_revision to api.saveScene.
    if (!node.scene_id) {
      error = `Node ${node.title} has no underlying scene to edit.`;
      return;
    }
    let targetPane = editorPanes.find((pane) => !pane.pinned);
    if (!targetPane) {
      targetPane = addEditorPane();
    }
    if (targetPane.dirty) {
      await saveEditorPane(targetPane.id);
    }
    const scene = await api.getScene(node.scene_id);
    editorPanes = editorPanes.map((pane) =>
      pane.id === targetPane!.id
        ? {
            ...pane,
            document: { type: "structure_node", id: node.id },
            scene,
            dirty: false,
            draftTitle: scene.title,
            draftMarkdown: scene.body,
            draftStatus: scene.status,
            draftEntryType: scene.entry_type,
            draftMetadata: cloneMetadata(scene.metadata),
            saving: false,
            recentlySaved: false,
          }
        : pane,
    );
    focusedEditorPaneId = targetPane!.id;
    focusPane(targetPane!.id);
    status = `Loaded ${scene.title}`;
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

  // Open a chat session in the editor-pane system. Mirrors the structure-
  // node pattern: synthesize a Scene-shaped record so the existing pane
  // plumbing works without a parallel field. NodeEditor sees entry_type
  // "chat_session" → body_shape "chat" → mounts ChatBodyView, which then
  // fetches the full ChatSession itself via /api/nodes/{id}.
  // saveEditorPane is a no-op for chats (ChatBodyView persists per-turn);
  // deleteEditorPaneScene routes through api.deleteChatSession.
  async function openChatInEditorPane(chatId: string) {
    const existingPane = editorPanes.find(
      (pane) => pane.document?.type === "chat" && pane.document.id === chatId,
    );
    if (existingPane) {
      focusedEditorPaneId = existingPane.id;
      focusPane(existingPane.id);
      status = `Focused ${existingPane.scene?.title ?? "open chat"}`;
      return;
    }
    const summary = get(chatSessionsStore).find((s) => s.id === chatId);
    let targetPane = editorPanes.find((pane) => !pane.pinned);
    if (!targetPane) {
      targetPane = addEditorPane();
    }
    if (targetPane.dirty) {
      await saveEditorPane(targetPane.id);
    }
    const sceneShaped = {
      id: chatId,
      title: summary?.title || "Untitled chat",
      body: "",
      revision: "",
      status: "",
      entry_type: "chat_session",
      metadata: {},
      computed_metadata: {},
    } as unknown as EditableDocument;
    editorPanes = editorPanes.map((pane) =>
      pane.id === targetPane!.id
        ? {
            ...pane,
            document: { type: "chat", id: chatId },
            scene: sceneShaped,
            dirty: false,
            draftTitle: sceneShaped.title,
            draftMarkdown: "",
            draftStatus: "",
            draftEntryType: "chat_session",
            draftMetadata: {},
            saving: false,
            recentlySaved: false,
          }
        : pane,
    );
    focusedEditorPaneId = targetPane!.id;
    focusPane(targetPane!.id);
    status = `Loaded ${sceneShaped.title}`;
    activeChatId = chatId;
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
            draftMarkdown: entry.body,
            draftStatus: "",
            draftEntryType: entry.entry_type,
            draftMetadata: cloneMetadata(entry.metadata),
            draftInputs: JSON.parse(JSON.stringify(entry.inputs ?? [])),
            saving: false,
            recentlySaved: false,
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
            recentlySaved: false,
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
            draftMarkdown: entry.body,
            draftStatus: "",
            draftEntryType: entry.entry_type,
            draftMetadata: cloneMetadata(entry.metadata),
            saving: false,
            recentlySaved: false,
          }
        : pane,
    );
    focusedEditorPaneId = targetPane.id;
    focusPane(targetPane.id);
    status = `Loaded ${entry.title}`;
  }


  function metadataListText(value: unknown) {
    if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean).join(", ");
    if (typeof value === "string") return value.trim();
    return "";
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

  // Auto-save: per-pane debounce. Each pane's pending timer lives in
  // autoSaveTimers; rescheduled on every draft change, cancelled on
  // manual save / pane teardown. Chats persist per-turn from inside
  // ChatBodyView, so they skip the timer entirely.
  const AUTO_SAVE_IDLE_MS = 6000;
  const SAVED_INDICATOR_MS = 2000;
  const autoSaveTimers = new Map<string, ReturnType<typeof setTimeout>>();
  const savedIndicatorTimers = new Map<string, ReturnType<typeof setTimeout>>();

  function cancelAutoSave(id: string) {
    const timer = autoSaveTimers.get(id);
    if (timer !== undefined) {
      clearTimeout(timer);
      autoSaveTimers.delete(id);
    }
  }

  function scheduleAutoSave(id: string) {
    cancelAutoSave(id);
    const pane = editorPanes.find((candidate) => candidate.id === id);
    if (!pane?.dirty || pane.saving) return;
    if (pane.document?.type === "chat") return;
    const timer = setTimeout(() => {
      autoSaveTimers.delete(id);
      const current = editorPanes.find((candidate) => candidate.id === id);
      if (!current?.dirty || current.saving) return;
      if (current.document?.type === "chat") return;
      void run(() => saveEditorPane(id));
    }, AUTO_SAVE_IDLE_MS);
    autoSaveTimers.set(id, timer);
  }

  function flashSavedIndicator(id: string) {
    const existing = savedIndicatorTimers.get(id);
    if (existing !== undefined) clearTimeout(existing);
    const timer = setTimeout(() => {
      savedIndicatorTimers.delete(id);
      editorPanes = editorPanes.map((pane) =>
        pane.id === id ? { ...pane, recentlySaved: false } : pane,
      );
    }, SAVED_INDICATOR_MS);
    savedIndicatorTimers.set(id, timer);
  }

  function updateEditorPaneDraft(id: string, title: string, body: string, status: string, entryType: string, metadata: EntryMetadata, inputs?: PromptInputDefinition[]) {
    editorPanes = editorPanes.map((pane) => {
      if (pane.id !== id) return pane;
      const nextInputs = inputs ?? pane.draftInputs;
      const nextDirty = isEditorPaneDirty(pane.scene, title, body, status, entryType, metadata, nextInputs);
      return {
        ...pane,
        dirty: nextDirty,
        // New edits invalidate any "Saved" feedback still on screen.
        recentlySaved: nextDirty ? false : pane.recentlySaved,
        draftTitle: title,
        draftMarkdown: body,
        draftStatus: status,
        draftEntryType: entryType,
        draftMetadata: cloneMetadata(metadata),
        draftInputs: JSON.parse(JSON.stringify(nextInputs ?? [])),
      };
    });
    scheduleAutoSave(id);
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
    body: string,
    status: string,
    entryType: string,
    metadata: EntryMetadata,
    inputs?: PromptInputDefinition[],
  ) {
    if (!scene) return false;
    if (title !== scene.title) return true;
    if (body !== scene.body) return true;
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
    cancelAutoSave(id);
    const savedIndicatorTimer = savedIndicatorTimers.get(id);
    if (savedIndicatorTimer !== undefined) {
      clearTimeout(savedIndicatorTimer);
      savedIndicatorTimers.delete(id);
    }
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
    // Chats persist per-turn from within ChatBodyView via the unified
    // PUT /api/nodes/{id} path; the pane's draft-* fields aren't the
    // source of truth for chat state. Treat saveEditorPane as a no-op.
    if (documentKind === "chat") return;
    cancelAutoSave(id);
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
      } else if (documentKind === "research") {
        savedDocument = await api.saveResearchNote(draftDocument as ResearchNote, pane.draftMarkdown);
      } else if (documentKind === "prompt") {
        savedDocument = await api.savePromptEntry(draftDocument as PromptEntry, pane.draftMarkdown);
      } else if (documentKind === "assistant") {
        savedDocument = await api.saveAssistantEntry(draftDocument as AssistantEntry);
      } else if (documentKind === "project") {
        // Project node is the project.md singleton; round-trip via the
        // dedicated endpoint and re-shape into the editor pane's
        // Scene-compatible draft.
        savedDocument = await api.saveProjectNode(draftDocument as ProjectNode, pane.draftMarkdown) as unknown as EditableDocument;
      } else if (documentKind === "structure_node") {
        // Acts/Chapters are scenes with a non-"scene" entry_type — their
        // metadata + body + status round-trip via the scene endpoints.
        // The structure tree's per-node title is a projection of the
        // scene title, so refreshStructure below will pick up renames.
        savedDocument = await api.saveScene(draftDocument as Scene, pane.draftMarkdown);
      } else {
        savedDocument = await api.saveScene(draftDocument as Scene, pane.draftMarkdown);
      }
      // Keep the pane's current draft-* fields rather than snapping them to
      // savedDocument: if the user kept typing while the save was in flight
      // (easy under the 6s auto-save debounce), those keystrokes live in
      // the draft fields and would otherwise be silently overwritten.
      // Recompute `dirty` against savedDocument so the next debounce picks
      // up the interim edits.
      let paneStillDirty = false;
      editorPanes = editorPanes.map((candidate) => {
        if (candidate.id !== id) return candidate;
        paneStillDirty = isEditorPaneDirty(
          savedDocument,
          candidate.draftTitle,
          candidate.draftMarkdown,
          candidate.draftStatus,
          candidate.draftEntryType,
          candidate.draftMetadata,
          candidate.draftInputs,
        );
        return {
          ...candidate,
          document: { type: documentKind, id: savedDocument.id },
          scene: savedDocument,
          dirty: paneStillDirty,
          saving: false,
          // Only show "Saved" feedback if the pane is genuinely caught up;
          // flashing it while drafts are still pending would be misleading.
          recentlySaved: !paneStillDirty,
        };
      });
      if (paneStillDirty) scheduleAutoSave(id);
      else flashSavedIndicator(id);
      if (documentKind === "lore") {
        await refreshLoreEntries();
        await refreshKnownTags();
      } else if (documentKind === "research") {
        // save_research_note already syncs the title into the research tree
        // server-side; refresh so the pane reflects it.
        await refreshResearchStructure();
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
    const fileLabel = documentKind === "scene" ? "scene" : documentKind === "lore" ? "entry" : documentKind === "research" ? "note" : "prompt";
    const titleLabel =
      documentKind === "scene"
        ? "Delete Scene"
        : documentKind === "lore"
          ? "Delete Entry"
          : documentKind === "research"
            ? "Delete Note"
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

  async function confirmModalAction(dontShowAgain = false) {
    const currentConfirmation = confirmation;
    if (!currentConfirmation) return;
    confirmation = null;
    if (dontShowAgain && currentConfirmation.dontShowAgainKey) {
      suppressConfirm(currentConfirmation.dontShowAgainKey);
    }
    await run(currentConfirmation.onConfirm);
  }

  // Per-operation "don't show this again" suppression (localStorage).
  const CONFIRM_SUPPRESS_PREFIX = "confirmSuppress:";
  function isConfirmSuppressed(key: string): boolean {
    try {
      return localStorage.getItem(CONFIRM_SUPPRESS_PREFIX + key) === "1";
    } catch {
      return false;
    }
  }
  function suppressConfirm(key: string) {
    try {
      localStorage.setItem(CONFIRM_SUPPRESS_PREFIX + key, "1");
    } catch {
      // ignore storage failures — worst case, we ask again next time.
    }
  }
  // Gate a destructive action behind the confirm modal, honouring a
  // per-op-type "don't show again" suppression. If suppressed, runs the
  // action immediately; otherwise opens the modal.
  function requestConfirm(options: Omit<ConfirmationState, "onConfirm"> & { onConfirm: () => Promise<void> }) {
    if (options.dontShowAgainKey && isConfirmSuppressed(options.dontShowAgainKey)) {
      void run(options.onConfirm);
      return;
    }
    confirmation = options;
  }

  async function deleteEditorPaneScene(id: string) {
    const pane = editorPanes.find((candidate) => candidate.id === id);
    if (!pane?.scene) return;
    const documentKind = pane.document?.type ?? "scene";
    const sceneTitle = pane.scene.title;
    if (documentKind === "lore") {
      setLoreEntries((await api.deleteLoreEntry(pane.scene.id)).entries);
    } else if (documentKind === "research") {
      // Delete the tree node that points at this note; the backend
      // unlinks the markdown file as part of the cascade.
      const node = researchStructure ? findNodeBySceneId(researchStructure.root, pane.scene.id) : null;
      if (node) {
        setResearchStructure(await api.deleteResearchNode(node.id));
      }
    } else if (documentKind === "prompt") {
      setPromptEntries((await api.deletePromptEntry(pane.scene.id)).entries);
    } else if (documentKind === "assistant") {
      setAssistantEntries((await api.deleteAssistantEntry(pane.scene.id)).entries);
    } else if (documentKind === "chat") {
      setChatSessions((await api.deleteChatSession(pane.scene.id)).sessions);
      if (activeChatId === pane.scene.id) activeChatId = null;
    } else {
      setStructure(await api.deleteScene(pane.scene.id));
      await refreshTodos();
    }
    tearDownEditorPane(id);
    status = `Deleted ${sceneTitle}`;
  }

  async function addTodo() {
    if (!newTodo.trim()) return;
    await run(async () => {
      setTodos((await api.createTodo(newTodo.trim(), activeScene?.id)).items);
      newTodo = "";
    });
  }

  async function toggleTodo(item: TodoItem) {
    await run(async () => {
      setTodos((await api.updateTodo(item.id, { status: item.status === "open" ? "done" : "open" })).items);
    });
  }

  async function updateTodoText(item: TodoItem, text: string) {
    const trimmed = text.trim();
    if (!trimmed || trimmed === item.text) return;
    await run(async () => {
      setTodos((await api.updateTodo(item.id, { text: trimmed })).items);
    });
  }

  async function deleteTodo(item: TodoItem) {
    await run(async () => {
      setTodos((await api.deleteTodo(item.id)).items);
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
      setTodos(nextTodos.filter((item) => !item.anchor_id));
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
      const result = await api.validateProject();
      setValidation(result);
      status = result.valid ? "Project validation passed" : "Project validation found issues";
    });
  }

  async function repairProject() {
    await run(async () => {
      const result = await api.repairProject();
      setValidation(result);
      await refreshStructure();
      await refreshTodos();
      status = result.valid ? "Project repair complete" : "Project repair complete with remaining issues";
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
            ? ""
            : `${openCount} open embedded TODO${openCount === 1 ? "" : "s"} · ${doneCount} completed.`,
        ];
      }),
    );
  }
</script>

<TopBar
  currentTitle={isProjectOpen ? projectTitle : null}
  currentProjectColor={currentProjectColor}
  {recentProjects}
  projectOpen={isProjectOpen}
  themePref={$themePreference}
  onCycleTheme={() => themePreference.update((p) => nextPreference(p))}
  onSelectRecent={(path) => void openProjectAt(path)}
  onOpenFolder={openDirectoryPickerForOpenProject}
  onNewProject={openNewProjectModal}
  onOpenAssistants={openAssistantsPane}
  onOpenSettings={openMachineSettings}
  onOpenDetailTypes={openDetailTypesPane}
  onOpenProjectNode={() => void openProjectNodeInEditorPane()}
/>

<main class="workspace">
  <Pane id="project" title="Project" paneClass="project-pane" hidden={!isPaneVisible("project")} style={paneStyle("project")} chrome={paneChrome}>
    <div class="pane-content project-panel">
      <Project
        {isProjectOpen}
        {projectTitle}
        {projectPath}
        {projectCostTotal}
        {projectCostBreakdown}
        {aiHealthResult}
        {aiHealthChecking}
        {validation}
        bind:aiPolicy
        bind:aiDefaultProvider
        bind:aiDefaultModelClass
        bind:projectCostExpanded
        onValidate={validateProject}
        onOpenChats={openChatsPane}
        onSaveAISettings={updateProjectAISettings}
        onHealthCheck={runAIHealthCheck}
        onOpenPrompts={openPromptsPane}
        onRepair={repairProject}
      />
    </div>
  </Pane>

  <Pane id="outline" title="Draft" paneClass="outline-pane" hidden={!isPaneVisible("outline")} style={paneStyle("outline")} chrome={paneChrome}>
    <div class="pane-content">
      <Tree
        config={manuscriptTree}
        {structure}
        collapsed={collapsedStructureNodes}        draftTitles={draftTitleByScene}
        sectionLabel="Scenes"
        emptyLabel="No scenes yet."
        {run}
        onRequestDelete={(node) => requestDeleteTreeNode(manuscriptTree, node)}
        {addMenuOpenFor}
        {addMenuPosition}
        onToggleAddMenu={toggleAddMenu}
        onCloseAddMenu={closeAddMenu}
      />
    </div>
  </Pane>

  <Pane id="lore" title="Lore" paneClass="lore-pane" hidden={!isPaneVisible("lore")} style={paneStyle("lore")} chrome={paneChrome}>
    {#snippet actions()}
      <button class="pin-button" type="button" title="Add entry" on:mousedown={(event) => event.stopPropagation()} on:click={() => newLoreEntry()}>+ Entry</button>
    {/snippet}
    <div class="pane-content">
      <Lore
        entries={loreEntries}        onOpenEntry={(id) => openLoreEntryInEditorPane(id)}
        onMoveNoteToResearch={(entry) => requestMoveLoreNoteToResearch(entry)}
      />
    </div>
  </Pane>

  <Pane id="research" title="Research" paneClass="research-pane" hidden={!isPaneVisible("research")} style={paneStyle("research")} chrome={paneChrome}>
    <div class="pane-content">
      <Tree
        config={researchTree}
        structure={researchStructure}
        collapsed={collapsedResearchNodes}        draftTitles={draftTitleByScene}
        sectionLabel="Notes"
        emptyLabel="No topics or notes yet."
        {run}
        onRequestDelete={(node) => requestDeleteTreeNode(researchTree, node)}
        {addMenuOpenFor}
        {addMenuPosition}
        onToggleAddMenu={toggleAddMenu}
        onCloseAddMenu={closeAddMenu}
      />
    </div>
  </Pane>

  <Pane id="schema" title="Detail Types" paneClass="schema-pane" hidden={!isProjectOpen || !schemaPaneOpen} style={paneStyle("schema")} chrome={paneChrome}>
    {#snippet actions()}
      <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => createSchemaTypeDraft()}>+ Type</button>
      <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => (groupsManagerOpen = true)}>Groups…</button>
      <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => (tagsManagerOpen = true)}>Tags…</button>
      <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => closeSchemaPane("schema")}>Close</button>
    {/snippet}
    <SchemaTreePane
      bind:draggedSchemaTypeId
      schemaFieldKind={schemaFieldKind}
      schemaContextHeading={schemaContextHeading}
      schemaNodeTypeTree={schemaNodeTypeTree}
      selectedSchemaTypeId={selectedSchemaTypeId}
      schemaTypeLayerId={schemaTypeLayerId}
      metadataSchemaOverview={metadataSchemaOverview}
      projectSchemaLayerId={projectSchemaLayerId}
      onSwitchKind={switchSchemaKind}
      onCreateType={createSchemaTypeDraft}
      onOpenType={openSchemaTypeDetail}
      onStartTypeDrag={startSchemaTypeDrag}
      onDropTypeOnParent={dropSchemaTypeOnParent}
      onCreateField={createSchemaFieldDraft}
      onDeleteType={requestDeleteSchemaType}
      onOpenField={openSchemaFieldDetail}
    />
  </Pane>

  <Pane id="schema_type" title="Detail Type" paneClass="schema-type-pane" hidden={!isProjectOpen || !schemaTypePaneOpen} style={paneStyle("schema_type")} chrome={paneChrome}>
    {#snippet actions()}
      <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => closeSchemaPane("schema_type")}>Close</button>
    {/snippet}
    <SchemaTypeEditor
      bind:schemaTypeName
      bind:schemaTypeLayerId
      bind:schemaTypeColor
      bind:expandedSchemaFieldId
      bind:fieldDropTarget
      bind:groupApplyOpen
      bind:applyGroupId
      bind:applyGroupLabel
      bind:applyGroupPrefix
      bind:promptSystemPrompt
      bind:promptOutputKind
      schemaTypeId={schemaTypeId}
      schemaTypeKind={schemaTypeKind}
      schemaTypeParent={schemaTypeParent}
      schemaTypeReadonly={schemaTypeReadonly}
      selectedSchemaTypeId={selectedSchemaTypeId}
      selectedSchemaFieldId={selectedSchemaFieldId}
      schemaFieldReadonly={schemaFieldReadonly}
      schemaFieldLayerId={schemaFieldLayerId}
      metadataSchemaOverview={metadataSchemaOverview}
      metadataSchemaLayers={metadataSchemaLayers}
      typeOwnFieldEntries={typeOwnFieldEntries}
      typeInheritedFieldEntries={typeInheritedFieldEntries}
      typeOwnFieldSections={typeOwnFieldSections}
      typeInheritedFieldSections={typeInheritedFieldSections}
      typeGroupApplications={typeGroupApplications}
      availableGroupEntries={availableGroupEntries}
      NEW_FIELD_SENTINEL={NEW_FIELD_SENTINEL}
      projectSchemaLayerId={projectSchemaLayerId}
      onTypeNameChange={updateSchemaTypeName}
      onSaveType={saveSchemaType}
      onSaveField={saveSchemaField}
      onCancelField={() => (expandedSchemaFieldId = null)}
      onRemoveField={requestDeleteSchemaField}
      onToggleFieldInline={toggleSchemaFieldInline}
      onCreateFieldDraft={createSchemaFieldDraft}
      onApplyGroup={applyGroupToType}
      onRemoveGroupApplication={removeGroupApplication}
      onFieldDragStart={onFieldDragStart}
      onFieldDragOver={onFieldDragOver}
      onFieldDrop={onFieldDrop}
      onClearFieldDrag={clearFieldDrag}
    />
  </Pane>

  <Pane id="prompts" title="Prompts" paneClass="prompts-pane" hidden={!isProjectOpen || !promptsPaneOpen} style={paneStyle("prompts")} chrome={paneChrome}>
    {#snippet actions()}
      <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => closeSchemaPane("prompts")}>Close</button>
    {/snippet}
    <div class="pane-content schema-list">
      <Prompts
        entries={promptEntries}        onOpenEntry={(id) => openPromptEntryInEditorPane(id)}
        onNewEntry={(entryType) => newPromptEntry(entryType)}
      />
    </div>
  </Pane>

  <Pane id="assistants" title="Assistants" paneClass="assistants-pane" hidden={!assistantsPaneOpen} style={paneStyle("assistants")} chrome={paneChrome}>
    {#snippet actions()}
      <button class="pin-button" type="button" title="Add assistant" on:mousedown={(event) => event.stopPropagation()} on:click={() => newAssistantEntry()}>+ Assistant</button>
      <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => closeSchemaPane("assistants")}>Close</button>
    {/snippet}
    <div class="pane-content schema-list">
      <Assistants
        entries={assistantEntries}        defaultAssistantId={defaultAssistantId}
        onOpenEntry={(id) => openAssistantEntryInEditorPane(id)}
        onReorder={reorderAssistantsInLayer}
      />
    </div>
  </Pane>

  <Pane id="chats" title="Chats" paneClass="chats-pane" hidden={!isPaneVisible("chats")} style={paneStyle("chats")} chrome={paneChrome}>
    {#snippet actions()}
      <button class="pin-button" type="button" title="Start a new chat" on:mousedown={(event) => event.stopPropagation()} on:click={() => createNewChatSession()}>+ New Chat</button>
      <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => closeSchemaPane("chats")}>Close</button>
    {/snippet}
    <div class="pane-content schema-list">
      <Chats
        sessions={chatSessions}
        {activeChatId}
        promptEntries={promptEntries}
        assistantEntries={assistantEntries}
        onOpenChat={(id) => run(() => openChatInEditorPane(id))}
        onDeleteChat={(id) => deleteChatSessionFromPane(id)}
      />
    </div>
  </Pane>

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
          {#if editorPane.saving}
            <span class="pane-status">Saving…</span>
          {:else if editorPane.dirty}
            <span class="pane-status">Unsaved</span>
          {:else if editorPane.recentlySaved}
            <span class="pane-status pane-status-saved">Saved</span>
          {/if}
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
      <NodeEditor
        bind:this={editorPaneComponents[editorPane.id]}
        scene={editorPane.scene}
        documentKind={editorPane.document?.type ?? "scene"}
        promptEntries={promptEntries}
        structure={structure}
        researchStructure={researchStructure}
        loreEntries={loreEntries}
        knownTags={knownTags}
        implicitContextMatcher={implicitContextMatcher}
        assistantEntries={assistantEntries}
        defaultAssistantId={defaultAssistantId}
        availableScenes={flattenStructureScenes(structure?.root)}
        metadataReload={metadataReloadsByPane[editorPane.id] ?? null}
        titleReload={titleReloadsByPane[editorPane.id] ?? null}
        dirty={editorPane.dirty}
        todoStatusHint={editorPane.document?.type === "scene" && editorPane.scene && sceneEntryHasBody(editorPane.scene as Scene) ? (embeddedTodoStatusHintsByPane[editorPane.id] ?? "") : ""}
        on:focus={() => focusPane(editorPane.id)}
        on:change={(event) =>
          updateEditorPaneDraft(
            editorPane.id,
            event.detail.title,
            event.detail.body,
            event.detail.status,
            event.detail.entryType,
            event.detail.metadata,
            event.detail.inputs,
          )}
        on:custom-data={(event) => openSchemaForCustomData(event.detail.entryType, event.detail.kind)}
        on:embeddedTodos={(event) => updateEmbeddedTodosForPane(editorPane.id, event.detail.todos)}
        on:navigate={(event) => navigateToBacklink(event.detail.id, event.detail.kind)}
        on:open-chat={(event) => openChatFromPromptEntry(event.detail.entry, event.detail.inputs, event.detail.sceneId, event.detail.assistantId)}
      />
      <button class="pane-resize" type="button" aria-label="Resize Editor pane" on:keydown={(event) => handlePaneResizeKeydown(event, editorPane.id)} on:mousedown={(event) => startPaneResize(event, editorPane.id)}></button>
    </section>
  {/each}

  <Pane id="todo" title="TODO" paneClass="todo-pane" hidden={!isPaneVisible("todo")} style={paneStyle("todo")} chrome={paneChrome}>
    {#snippet actions()}
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
    {/snippet}
    <div class="pane-content">
      <Todo
        {todos}
        embeddedTodos={allEmbeddedTodos}
        bind:newTodo
        onAddTodo={addTodo}
        onToggleTodo={toggleTodo}
        onUpdateTodoText={updateTodoText}
        onDeleteTodo={deleteTodo}
        onTodoTextKeydown={handleTodoTextKeydown}
        onOpenFileTodo={openFileTodo}
        onToggleEmbeddedTodo={toggleEmbeddedTodo}
        onUpdateEmbeddedTodoNote={updateEmbeddedTodoNote}
        onOpenEmbeddedTodo={openEmbeddedTodo}
        onDeleteEmbeddedTodo={deleteEmbeddedTodo}
      />
    </div>
  </Pane>

  <Pane id="search" title="Search" paneClass="search-pane" hidden={!isPaneVisible("search")} style={paneStyle("search")} chrome={paneChrome}>
    <div class="pane-content">
      <Search {run} onOpenHit={openSearchHit} />
    </div>
  </Pane>

  <DirectoryPickerModal
    open={directoryPickerOpen}
    listing={directoryListing}
    loading={directoryPickerLoading}
    onClose={() => (directoryPickerOpen = false)}
    onNavigate={(path) => loadDirectory(path)}
    onSelect={(path) => useDirectory(path)}
  />

  <ConfirmModal
    state={confirmation}
    onCancel={() => (confirmation = null)}
    onConfirm={(dontShowAgain) => confirmModalAction(dontShowAgain)}
  />

  <NewProjectModal
    open={newProjectModalOpen}
    bind:name={newProjectName}
    bind:overrideFolder={newProjectOverrideFolder}
    bind:overridePath={newProjectOverridePath}
    resolvedPath={newProjectResolvedPath}
    {defaultProjectsFolder}
    onClose={closeNewProjectModal}
    onSubmit={confirmNewProject}
    onOpenOverrideFolderPicker={openDirectoryPickerForNewProjectOverride}
    onOpenSettings={openMachineSettings}
    onClearOverride={() => { newProjectOverrideFolder = false; newProjectOverridePath = ""; }}
  />

  <MachineSettingsDialog
    open={machineSettingsOpen}
    settings={machineSettings}
    bind:draft={machineSettingsDraft}
    onCancel={() => (machineSettingsOpen = false)}
    onSave={saveMachineSettings}
  />

  {#if groupsManagerOpen && metadataSchema}
    <GroupsManagerDialog
      groups={metadataSchema.groups ?? {}}
      layerId={schemaTypeLayerId || projectSchemaLayerId()}
      on:changed={(event) => { setMetadataSchema(event.detail.schema); void refreshMetadataSchema(); }}
      on:close={() => (groupsManagerOpen = false)}
    />
  {/if}

  {#if tagsManagerOpen}
    <TagManagerDialog
      on:changed={() => void refreshAfterTagChange()}
      on:close={() => (tagsManagerOpen = false)}
    />
  {/if}

  {#if error}
    <section class="error-toast" role="alert">
      <span class="error-toast-body">{error}</span>
      <button
        class="error-toast-close"
        type="button"
        aria-label="Dismiss error"
        on:click={() => (error = "")}
      >×</button>
    </section>
  {/if}


</main>

<style>
  .workspace {
    position: relative;
    width: 100vw;
    height: calc(100vh - 40px);
    margin-top: 40px;
    overflow: hidden;
  }

  @media (max-width: 640px) {
    .workspace {
      display: grid;
      height: auto;
      min-height: 100vh;
      gap: 12px;
      padding: 12px;
      overflow: auto;
    }
  }

  /* Project pane content wrapper — slotted into <Pane>, so it's App's own DOM. */
  .project-panel {
    display: grid;
    align-content: start;
    gap: 10px;
  }

  /* Inline editor-pane save-status indicator (App renders editor panes inline). */
  .pane-status {
    color: var(--text-3);
    font-size: 12px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .pane-status-saved {
    color: var(--accent);
  }

  /* Ancestor-entry editor panes: tint the (shared) pane header + show a badge.
     `.from-ancestor` is App-only, so scoping this here matches only App's inline
     editor panes — other components' `.pane-header` is untouched. */
  .editor-pane.from-ancestor .pane-header {
    background: var(--star-soft);
    border-bottom-color: var(--star-border);
  }

  .ancestor-badge {
    display: inline-block;
    margin-left: 8px;
    padding: 1px 7px;
    border-radius: 10px;
    background: var(--star);
    color: var(--surface);
    font-size: 11px;
    font-weight: 500;
    vertical-align: middle;
  }

  .error-toast {
    position: fixed;
    right: 18px;
    bottom: 18px;
    z-index: 1000;
    max-width: 420px;
    padding: 10px 12px;
    display: flex;
    align-items: flex-start;
    gap: 10px;
    border: 1px solid var(--danger);
    border-radius: 8px;
    color: var(--danger);
    background: var(--danger-soft);
    box-shadow: 0 14px 30px rgba(36, 36, 36, 0.16);
  }

  .error-toast-body {
    flex: 1;
    min-width: 0;
    line-height: 1.4;
    word-wrap: break-word;
  }

  .error-toast-close {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    margin: -2px -4px 0 0;
    padding: 0;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: var(--danger);
    font-size: 18px;
    line-height: 1;
    cursor: pointer;
  }

  .error-toast-close:hover {
    background: rgba(180, 59, 53, 0.12);
  }
</style>

