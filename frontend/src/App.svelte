<script lang="ts">
  import { onMount, tick } from "svelte";
  import { api } from "@/lib/api";
  import CodeEditor from "@/components/widgets/CodeEditor.svelte";
  import NodeEditor from "@/components/editor/NodeEditor.svelte";
  import DirectoryPickerModal from "@/components/dialogs/DirectoryPickerModal.svelte";
  import SchemaPanes from "@/components/schema/SchemaPanes.svelte";
  import Tree, { type TreeConfig } from "@/components/panes/Tree.svelte";
  import Lore from "@/components/panes/Lore.svelte";
  import Assistants from "@/components/panes/Assistants.svelte";
  import Prompts from "@/components/panes/Prompts.svelte";
  import Chats from "@/components/panes/Chats.svelte";
  import Project from "@/components/panes/Project.svelte";
  import Search from "@/components/panes/Search.svelte";
  import Todo, { type EmbeddedTodo } from "@/components/panes/Todo.svelte";
  import Pane, { type PaneChrome } from "@/components/panes/Pane.svelte";
  import {
    collectNodeIdSet,
    collectSceneIdSet,
    entryTypeName,
    findNodeBySceneId,
    findStructureNodeById,
    isLeafNode,
  } from "@/lib/utils/treeHelpers";
  import NewProjectModal from "@/components/dialogs/NewProjectModal.svelte";
  import MachineSettingsDialog from "@/components/dialogs/MachineSettingsDialog.svelte";
  import ConfirmModal from "@/components/dialogs/ConfirmModal.svelte";
  import PlainTextEditor from "@/components/widgets/PlainTextEditor.svelte";
  import PromptInputField from "@/components/widgets/PromptInputField.svelte";
  import TopBar from "@/components/chrome/TopBar.svelte";
  import { installThemeWiring, themePreference, nextPreference, type ThemePreference } from "@/lib/utils/theme";
  import { renderChatContent } from "@/lib/utils/chatMessageRender";
  import { setPalette, resolveColor } from "@/lib/utils/colors";
  import { get } from "svelte/store";
  import {
    chatSessionsStore,
    projectCostTotalStore,
    projectCostBreakdownStore,
    refreshChatSessions as storeRefreshChatSessions,
    refreshProjectCost as storeRefreshProjectCost,
    setChatSessions,
    setProjectCost,
  } from "@/lib/stores/chats";
  import { todosStore, refreshTodos as storeRefreshTodos, setTodos } from "@/lib/stores/todos";
  import { knownTagsStore, refreshKnownTags as storeRefreshKnownTags, setKnownTags } from "@/lib/stores/tags";
  import { validationStore, setValidation } from "@/lib/stores/validation";
  import {
    structureStore,
    researchStructureStore,
    refreshStructure as storeRefreshStructure,
    refreshResearchStructure as storeRefreshResearchStructure,
    setStructure,
    setResearchStructure,
  } from "@/lib/stores/structure";
  import {
    loreEntriesStore,
    refreshLoreEntries as storeRefreshLoreEntries,
    setLoreEntries,
  } from "@/lib/stores/lore";
  import {
    promptEntriesStore,
    refreshPromptEntries as storeRefreshPromptEntries,
    setPromptEntries,
  } from "@/lib/stores/prompts";
  import {
    assistantEntriesStore,
    defaultAssistantIdStore,
    refreshAssistantEntries as storeRefreshAssistantEntries,
    setAssistantEntries,
  } from "@/lib/stores/assistants";
  import {
    metadataSchemaStore,
    projectSchemaLayerId,
  } from "@/lib/stores/schema";
  import { implicitContextMatcherStore } from "@/lib/stores/derived";
  import { loadProjectData } from "@/lib/stores/index";
  import { focusedDocumentStore, pinnedKeysStore } from "@/lib/stores/editorFocus";
  import { paneLayout, isEditorPaneId } from "@/lib/stores/paneLayout.svelte";
  import {
    type EditorPaneState,
    computeDraftTitleOverrides,
  } from "@/lib/editor-core/editorPaneModel";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import { confirmService } from "@/lib/stores/confirmService.svelte";
  import { projectChooser } from "@/lib/stores/projectChooser.svelte";
  import TagManagerDialog from "@/components/dialogs/TagManagerDialog.svelte";
  import type {
    AIHealthResponse,
    AIPolicy,
    AssistantEntrySummary,
    ChatMessage,
    ChatSession,
    ChatSessionJournalEntry,
    ChatSessionMessage,
    ChatSessionSummary,
    LoreEntrySummary,
    PromptEntrySummary,
    Scene,
    MachineSettingsDraft,
    MachineSettingsUpdate,
    MachineSettingsView,
    NodePickerConfig,
    PaneId,
    ProjectInfo,
    RecentProject,
    ProjectValidation,
    SearchHit,
    StructureDocument,
    StructureNode,
    StructureNodeDeletePreview,
    TodoItem,
  } from "@/lib/types";

  type AppState =
    | { name: "needsProject" }
    | { name: "projectOpen"; project: ProjectInfo };
  // TreeConfig (the per-kind manuscript/research tree contract) + the tree
  // rendering and inline CRUD now live in Tree.svelte; App owns the structure
  // data, the editor-pane coupling (delete, dblclick-open), and collapse state.

  let projectPath = $state("");
  let projectTitle = $state("Untitled Project");

  let aiPolicy: AIPolicy = $state("off");
  let aiDefaultProvider = $state("");
  let aiDefaultModelClass = $state("");
  let aiHealthResult: AIHealthResponse | null = $state(null);
  let aiHealthChecking = $state(false);

  let machineSettings: MachineSettingsView | null = $state(null);
  let machineSettingsOpen = $state(false);

  // Recent projects + default base folder come from machine settings.
  // Reloaded after open/create (which push onto the recents list) and after
  // machine-settings saves (which can change the default folder).
  let recentProjects: RecentProject[] = $state([]);
  // The default base folder + the new-project / directory-picker UI live in the
  // projectChooser controller (lib/stores/projectChooser). App pushes the
  // machine-settings default in and injects the open/create lifecycle.

  // Which chat is open in an editor pane lives on the editorPanes controller
  // (editorPanes.activeChatId) — it's a projection of the editor surface.
  let activeChatTitle = "Untitled chat";
  let projectCostExpanded = $state(false);
  let machineSettingsDraft: MachineSettingsDraft | null = $state(null);
  let appState = $state<AppState>({ name: "needsProject" });
  let collapsedResearchNodes: Record<string, boolean> = $state({});
  let tagsManagerOpen = $state(false);
  let activeParentId: string | undefined = undefined;
  let addMenuOpenFor: string | null = $state(null);
  // Floating-popover coordinates captured at click time. `position: fixed`
  // on the popover sidesteps any ancestor `overflow: hidden` (panes,
  // tier panels) so the menu can extend below/above its anchor without
  // being clipped.
  let addMenuPosition: { top: number; right: number } | null = $state(null);
  let draftTitleByScene = $state(new Map<string, string>());
  // The schema-authoring surface (state, the entry-type→kind→tree cascade, and
  // all persistence handlers) lives in SchemaPanes.svelte (#14 P0). App holds
  // only the instance ref so it can drive the three entry points.
  let schemaPanes: SchemaPanes | undefined = $state();
  let promptsPaneOpen = $state(false);
  let assistantsPaneOpen = $state(false);
  let chatsPaneOpen = $state(false);
  let newTodo = $state("");
  // Outline group-header collapse state, keyed by StructureNode.id.
  // Same shape as the other collapsed-* maps so the refactor stays
  // consistent across panes. Persisted per-project to localStorage so
  // the user's collapse choices survive reload.
  let collapsedStructureNodes: Record<string, boolean> = $state({});
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
  let error = $state("");
  let status = "No project open";
  // The editor-pane MDI surface (open panes, drafts, autosave lifecycle, the
  // open*/embedded-TODO bridge) lives in the editorPanes controller
  // (lib/stores/editorPanes). App keeps only the projections it renders.

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
    paneLayout.fitToViewport();
    // Raising the focused editor pane must also update focusedEditorPaneId; the
    // pane-layout controller stays ignorant of editor state and calls back here.
    paneLayout.onRaise = (id) => {
      if (isEditorPaneId(id) && editorPanes.panes.some((pane) => pane.id === id)) {
        editorPanes.focusedEditorPaneId = id;
      }
    };
    // The editor-pane controller funnels errors/status through App and writes the
    // project-node title back into the top bar; it owns everything else itself.
    editorPanes.run = run;
    editorPanes.setStatus = (message) => { status = message; };
    editorPanes.setError = (message) => { error = message; };
    editorPanes.onProjectNodeSaved = (title) => {
      projectTitle = title;
      if (appState.name === "projectOpen") {
        appState = { ...appState, project: { ...appState.project, title } };
      }
    };
    // Confirm actions flow through App's run() so errors surface in `error`.
    confirmService.onRun = run;
    // Project chooser drives only its modals; App owns the open/create
    // lifecycle and feeds the picker its start dir + error sink.
    projectChooser.onRun = run;
    projectChooser.onError = (message) => { error = message; };
    projectChooser.onOpenProject = (path) => void openProjectAt(path);
    projectChooser.onCreateProject = createProjectAt;
    projectChooser.getStartPath = () => projectPath;
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
      paneLayout.dispose();
      editorPanes.dispose();
      document.removeEventListener("mousedown", handleDocumentMousedown);
      cleanupThemeWiring?.();
    };
  });

  async function loadMachineSettings() {
    try {
      machineSettings = await api.getMachineSettings();
      recentProjects = machineSettings.recent_projects ?? [];
      projectChooser.defaultProjectsFolder = machineSettings.default_projects_folder ?? "";
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
      projectChooser.defaultProjectsFolder = view.default_projects_folder ?? "";
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
    paneLayout.fitToViewport();
    focusPane("outline");
    void hydrateChatSessionsForProject();
    void refreshProjectCost();
    void refreshCurrentProjectColor();
  }

  // Project-node color, surfaced on the top-bar switcher as a dot so the
  // user can tell at a glance which project they're in. Refreshed on
  // open + on save of the project node.
  let currentProjectColor: string | null = $state(null);
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
    editorPanes.reset();
    setKnownTags([]);
    activeChatTitle = "Untitled chat";
    setChatSessions([]);
    // Preserve all pane configs. An earlier version stripped chat/preview/
    // prompts/assistants/chats out of `panes`, which made `panes.chats` etc.
    // undefined after a project switch — focusPane then created `{ z }` entries
    // with no left/top/width/height, and paneStyle returned an empty string,
    // so opening those panes did nothing visible. Pane positions and sizes are
    // pure UI state; nothing project-specific lives here.
  }

  // Thin adapters onto the pane-layout window manager (lib/stores/paneLayout):
  // App keeps its local vocabulary while the geometry/drag/resize logic lives in
  // the controller. raise() also runs onRaise (wired in onMount) to track focus.
  const focusPane = (id: PaneId) => paneLayout.raise(id);
  const paneStyle = (id: PaneId) => paneLayout.styleFor(id);

  // The shared chrome controller handed to every <Pane>; each pane calls these
  // with its own id. Stable object — the handlers don't change.
  const paneChrome: PaneChrome = {
    focus: focusPane,
    headerKeydown: (event, id) => paneLayout.headerKeydown(event, id),
    headerDrag: (event, id) => paneLayout.startDrag(event, id),
    resizeKeydown: (event, id) => paneLayout.resizeKeydown(event, id),
    resizeDrag: (event, id) => paneLayout.startResize(event, id),
  };

  async function run(action: () => Promise<void>): Promise<boolean> {
    error = "";
    try {
      await action();
      return true;
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
      return false;
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
      await editorPanes.refreshOpenEditorPaneBaselines();
    });
  }

  async function refreshTodos() {
    await storeRefreshTodos();
  }

  // Create a project at the given path with the given title. Optional
  // base folder lets callers override the default; omit to use the
  // project's parent folder (matches the backend's fallback).
  async function createProjectAt(path: string, title: string, baseFolder?: string) {
    await run(async () => {
      const openedProject = await api.createProject(path, title, baseFolder ?? "");
      openProjectWorkspace(openedProject);
      await loadProjectData();
      schemaPanes?.syncSelection();
      const initialSceneId = findFirstSceneId(get(structureStore)?.root);
      if (initialSceneId) {
        await editorPanes.openScene(initialSceneId);
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
      schemaPanes?.syncSelection();
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
      projectChooser.defaultProjectsFolder = machineSettings.default_projects_folder ?? "";
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
      await editorPanes.openChat(session.id);
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
      await editorPanes.openChat(session.id);
      status = `Opened ${entry.title} as a chat`;
    });
  }

  async function deleteChatSessionFromPane(chatId: string): Promise<void> {
    try {
      const listing = await api.deleteChatSession(chatId);
      setChatSessions(listing.sessions);
      if (editorPanes.activeChatId === chatId) {
        editorPanes.activeChatId = null;
        activeChatTitle = "Untitled chat";
      }
      // Tear down any editor pane still pointing at the deleted chat.
      for (const pane of editorPanes.panes.filter(
        (candidate) => candidate.document?.type === "chat" && candidate.document.id === chatId,
      )) {
        editorPanes.tearDown(pane.id);
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

  function paneEntryFromAncestor(pane: EditorPaneState): boolean {
    const layerId = pane.scene?.source_layer_id;
    if (!layerId) return false;
    const projectLayer = projectSchemaLayerId();
    if (!projectLayer) return false;
    return layerId !== projectLayer;
  }

  function closeListPane(id: "prompts" | "assistants" | "chats") {
    if (id === "prompts") promptsPaneOpen = false;
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
      await editorPanes.openScene(scene.id);
    });
  }

  function defaultChildEntryType(parentType: string): string | null {
    if (parentType === "root") return "act";
    if (parentType === "act") return "chapter";
    if (parentType === "chapter") return "scene";
    return null;
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
    confirmService.request({
      title: "Move to Research",
      message: `Move "${entry.title}" out of Lore and into the Research tree?${cascadeNote}`,
      details: [],
      confirmLabel: "Move to Research",
      destructive: droppable.length > 0,
      onConfirm: async () => {
        // Close the lore entry's editor pane first so it doesn't dangle
        // on a deleted file. The new research note will open in its own
        // pane after the migration.
        editorPanes.panes.forEach((pane) => {
          if (pane.document?.type === "lore" && pane.document.id === entry.id) {
            editorPanes.tearDown(pane.id);
          }
        });
        await run(async () => {
          const result = await api.moveLoreNoteToResearch(entry.id);
          setLoreEntries(result.lore.entries);
          setResearchStructure(result.tree);
          // Open the new note in the editor so the user sees the result.
          await editorPanes.openResearchNote(result.note_id);
          status = result.dropped_fields.length > 0
            ? `Moved "${entry.title}" to Research (dropped ${result.dropped_fields.join(", ")})`
            : `Moved "${entry.title}" to Research`;
        });
      },
    });
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
    openLeaf: (sceneId) => editorPanes.openScene(sceneId),
    onGroupClick: (nodeId) => deferStructureNodeCollapse(nodeId),
    onGroupDblClick: (nodeId) => handleStructureNodeDblClick(nodeId),
    cascadeLabels: {
      leaf: { singular: "scene", plural: "scenes" },
      container: { singular: "sub-container", plural: "sub-containers" },
    },
    afterDelete: () => refreshTodos(),
    afterRename: (nodeId, title) => editorPanes.syncRename(nodeId, title),
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
    openLeaf: (sceneId) => editorPanes.openResearchNote(sceneId),
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

    confirmService.request({
      title: `Delete ${typeName}`,
      message,
      details: backlinks.map((link) => `${link.title} — ${link.field_name}`),
      confirmLabel: `Delete ${typeName}`,
      destructive: true,
      onConfirm: () => performTreeDelete(config, node),
    });
  }

  async function performTreeDelete(config: TreeConfig, node: StructureNode) {
    // Close editor panes whose underlying leaf is doomed before the API
    // call so the panes don't dangle on a missing scene/note.
    const doomedSceneIds = collectSceneIdSet(node);
    editorPanes.panes.forEach((pane) => {
      if (
        pane.scene
        && pane.document?.type === config.kind
        && doomedSceneIds.has(pane.scene.id)
      ) {
        editorPanes.tearDown(pane.id);
      }
    });
    if (config.containerHasEditor) {
      // Manuscript Acts/Chapters can open as structure_node editor panes
      // — close those too if their node id falls inside the doomed subtree.
      const doomedNodeIds = collectNodeIdSet(node);
      editorPanes.panes.forEach((pane) => {
        if (pane.document?.type === "structure_node" && doomedNodeIds.has(pane.document.id)) {
          editorPanes.tearDown(pane.id);
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
    void run(() => editorPanes.openStructureNode(nodeId));
  }

  async function newLoreEntry() {
    await run(async () => {
      const entry = await api.createLoreEntry("New Entry", "lore_note");
      await refreshLoreEntries();
      await editorPanes.openLore(entry.id);
    });
  }

  function sceneEntryHasBody(scene: Scene): boolean {
    const entryDefinition = metadataSchema?.entry_types[scene.entry_type];
    return entryDefinition?.has_body ?? true;
  }

  function navigateToBacklink(id: string, kind: string) {
    if (kind === "lore") {
      void run(() => editorPanes.openLore(id));
    } else {
      void run(() => editorPanes.openScene(id));
    }
  }

  async function newPromptEntry(entryType: string) {
    await run(async () => {
      const created = await api.createPromptEntry(`Untitled Prompt`, entryType);
      await refreshPromptEntries();
      await editorPanes.openPrompt(created.id);
    });
  }

  async function newAssistantEntry() {
    await run(async () => {
      const created = await api.createAssistantEntry("Untitled assistant");
      await refreshAssistantEntries();
      await editorPanes.openAssistant(created.id);
    });
  }

  function metadataListText(value: unknown) {
    if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean).join(", ");
    if (typeof value === "string") return value.trim();
    return "";
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
    const completedEmbeddedTodos = editorPanes.allEmbeddedTodos.filter((item) => item.status === "done");
    if (completedTodos.length === 0 && completedEmbeddedTodos.length === 0) return;
    await run(async () => {
      let nextTodos = todos;
      for (const item of completedTodos) {
        nextTodos = (await api.deleteTodo(item.id)).items;
      }
      setTodos(nextTodos.filter((item) => !item.anchor_id));
      for (const item of completedEmbeddedTodos) {
        editorPanes.deleteEmbeddedTodo(item);
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
        await editorPanes.openLore(hit.file_id);
      } else {
        await editorPanes.openScene(hit.file_id);
      }
      if (hit.kind === "scene" && hit.todo_id) {
        window.setTimeout(() => editorPanes.highlightEmbeddedTodoInOpenPane(hit.file_id, hit.todo_id!), 0);
      }
    });
  }

  async function openEmbeddedTodo(item: EmbeddedTodo) {
    await run(async () => {
      await editorPanes.openScene(item.sceneId);
      window.setTimeout(() => editorPanes.highlightEmbeddedTodoInOpenPane(item.sceneId, item.id), 0);
    });
  }

  async function openFileTodo(item: TodoItem) {
    if (!item.scene_id) return;
    await run(async () => {
      await editorPanes.openScene(item.scene_id!);
    });
  }

  // AI chat sessions. Per-chat state (history, composer, cost/TTL) lives
  // inside ChatBodyView now; App only tracks the session roster (Chats pane)
  // and which chat is currently open in an editor pane (active-row highlight).
  let chatSessions = $derived($chatSessionsStore);
  // V2: project-wide cost rollup. Refreshed on project open and after
  // each chat save. `projectCostBreakdown` is the per-chat list returned
  // by /api/ai/project-cost; populated only when the user expands the
  // chip so common loads don't pay for full enumeration.
  let projectCostTotal = $derived($projectCostTotalStore);
  let projectCostBreakdown = $derived($projectCostBreakdownStore);
  let project = $derived(appState.name === "projectOpen" ? appState.project : null);
  let isProjectOpen = $derived(appState.name === "projectOpen");
  let structure = $derived($structureStore);
  // Research tree — parallel structure to the manuscript tree. Topics
  // are containers, notes are leaves with their own markdown file.
  // See docs/research-strategy.md.
  let researchStructure = $derived($researchStructureStore);
  let loreEntries = $derived($loreEntriesStore);
  // Compiled matcher for implicit-context highlighting in editors. Derived in
  // the store layer from lore + schema (see stores/derived.ts).
  let implicitContextMatcher = $derived($implicitContextMatcherStore);
  let knownTags = $derived($knownTagsStore);
  let focusedEditorPane = $derived(editorPanes.panes.find((pane) => pane.id === editorPanes.focusedEditorPaneId) ?? editorPanes.panes[0] ?? null);
  // Write-through the focused doc to the editor-focus store so the list panes
  // read it directly instead of having it drilled in (#14 Step 2). App is the
  // sole writer (projection of editorPanes).
  $effect.pre(() => {
    focusedDocumentStore.set(focusedEditorPane?.document ?? null);
  });
  let activeScene = $derived(focusedEditorPane?.document?.type === "scene" ? focusedEditorPane.scene : null);
  let todos = $derived($todosStore);
  let validation = $derived($validationStore);
  let metadataSchema = $derived($metadataSchemaStore);
  let promptEntries = $derived($promptEntriesStore);
  let assistantEntries = $derived($assistantEntriesStore);
  $effect.pre(() => {
    draftTitleByScene = computeDraftTitleOverrides(editorPanes.panes);
  });
  // Reactive function: rebound whenever any visibility-deciding state changes.
  // Templates that call `isPaneVisible(id)` track the function's identity — so
  // when this `$:` recomputes, every callsite re-runs and the pane shows.
  //
  // Why this is necessary: function calls are opaque to Svelte's template
  // dependency analyzer. A plain `function isPaneVisible(id)` that reads
  // `chatsPaneOpen` inside doesn't tell the compiler that flipping
  // `chatsPaneOpen` should re-evaluate `class:hidden-pane={!isPaneVisible("chats")}`.
  // The `$:` rebinding gives the template a tracked dependency.
  // (The schema / schema_type panes own their own visibility inside
  // SchemaPanes.svelte and are not routed through here — #14 P0.)
  let isPaneVisible = $derived(((
    _isProjectOpen,
    _assistantsPaneOpen,
    _promptsPaneOpen,
    _chatsPaneOpen,
    _editorPanes,
  ) => (id: PaneId): boolean => {
    if (id === "project") return true;
    if (id === "assistants") return _assistantsPaneOpen;
    if (!_isProjectOpen) return false;
    if (id === "research") return true;
    if (id === "prompts") return _promptsPaneOpen;
    if (id === "chats") return _chatsPaneOpen;
    return !isEditorPaneId(id) || _editorPanes.some((pane) => pane.id === id);
  })(
    isProjectOpen,
    assistantsPaneOpen,
    promptsPaneOpen,
    chatsPaneOpen,
    editorPanes.panes,
  ));
  // Derived in the assistants store (not a function): consumers pass it as a
  // prop, and a bare call in a prop expression wouldn't track its inner roster
  // dependency. See feedback_svelte5_reactivity_traps.
  let defaultAssistantId = $derived($defaultAssistantIdStore);
  // Set of "<docType>:<id>" keys for every node currently open in a
  // pinned editor pane. Derived reactively so the template can ask
  // `pinnedEditorPaneKeys.has(\`lore:${entry.id}\`)` and have Svelte
  // re-evaluate the binding when any pane's .pinned flips. (A plain
  // `function editorPanePinnedFor(...)` doesn't track editorPanes
  // when called inside a template prop binding — Svelte 5 legacy
  // reactivity only tracks deps read directly in the expression.)
  let pinnedEditorPaneKeys = $derived(new Set<string>(
    editorPanes.panes
      .filter((pane) => pane.pinned && pane.document)
      .map((pane) => `${pane.document!.type}:${pane.document!.id}`),
  ));
  // Write-through to the editor-focus store (read by the list panes' pin-star).
  $effect.pre(() => {
    pinnedKeysStore.set(pinnedEditorPaneKeys);
  });
</script>

<TopBar
  currentTitle={isProjectOpen ? projectTitle : null}
  currentProjectColor={currentProjectColor}
  {recentProjects}
  projectOpen={isProjectOpen}
  themePref={$themePreference}
  onCycleTheme={() => themePreference.update((p) => nextPreference(p))}
  onSelectRecent={(path) => void openProjectAt(path)}
  onOpenFolder={() => projectChooser.openForOpenProject()}
  onNewProject={() => projectChooser.openNewProject()}
  onOpenAssistants={openAssistantsPane}
  onOpenSettings={openMachineSettings}
  onOpenDetailTypes={() => schemaPanes?.openDetailTypes()}
  onOpenProjectNode={() => void editorPanes.openProjectNode()}
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
      <button class="pin-button" type="button" title="Add entry" onmousedown={(event) => event.stopPropagation()} onclick={() => newLoreEntry()}>+ Entry</button>
    {/snippet}
    <div class="pane-content">
      <Lore
        entries={loreEntries}        onOpenEntry={(id) => editorPanes.openLore(id)}
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

  <SchemaPanes
    bind:this={schemaPanes}
    {isProjectOpen}
    {paneChrome}
    {run}
    setStatus={(message) => (status = message)}
    refreshOpenEditorPaneBaselines={(transform) => editorPanes.refreshOpenEditorPaneBaselines(transform)}
    onOpenTagsManager={() => (tagsManagerOpen = true)}
  />

  <Pane id="prompts" title="Prompts" paneClass="prompts-pane" hidden={!isProjectOpen || !promptsPaneOpen} style={paneStyle("prompts")} chrome={paneChrome}>
    {#snippet actions()}
      <button class="pin-button" type="button" onmousedown={(event) => event.stopPropagation()} onclick={() => closeListPane("prompts")}>Close</button>
    {/snippet}
    <div class="pane-content schema-list">
      <Prompts
        entries={promptEntries}        onOpenEntry={(id) => editorPanes.openPrompt(id)}
        onNewEntry={(entryType) => newPromptEntry(entryType)}
      />
    </div>
  </Pane>

  <Pane id="assistants" title="Assistants" paneClass="assistants-pane" hidden={!assistantsPaneOpen} style={paneStyle("assistants")} chrome={paneChrome}>
    {#snippet actions()}
      <button class="pin-button" type="button" title="Add assistant" onmousedown={(event) => event.stopPropagation()} onclick={() => newAssistantEntry()}>+ Assistant</button>
      <button class="pin-button" type="button" onmousedown={(event) => event.stopPropagation()} onclick={() => closeListPane("assistants")}>Close</button>
    {/snippet}
    <div class="pane-content schema-list">
      <Assistants
        entries={assistantEntries}        defaultAssistantId={defaultAssistantId}
        onOpenEntry={(id) => editorPanes.openAssistant(id)}
        onReorder={reorderAssistantsInLayer}
      />
    </div>
  </Pane>

  <Pane id="chats" title="Chats" paneClass="chats-pane" hidden={!isPaneVisible("chats")} style={paneStyle("chats")} chrome={paneChrome}>
    {#snippet actions()}
      <button class="pin-button" type="button" title="Start a new chat" onmousedown={(event) => event.stopPropagation()} onclick={() => createNewChatSession()}>+ New Chat</button>
      <button class="pin-button" type="button" onmousedown={(event) => event.stopPropagation()} onclick={() => closeListPane("chats")}>Close</button>
    {/snippet}
    <div class="pane-content schema-list">
      <Chats
        sessions={chatSessions}
        activeChatId={editorPanes.activeChatId}
        promptEntries={promptEntries}
        assistantEntries={assistantEntries}
        onOpenChat={(id) => run(() => editorPanes.openChat(id))}
        onDeleteChat={(id) => deleteChatSessionFromPane(id)}
      />
    </div>
  </Pane>

  {#each editorPanes.panes as editorPane (editorPane.id)}
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <section
      class:hidden-pane={!isPaneVisible(editorPane.id)}
      class:from-ancestor={paneEntryFromAncestor(editorPane)}
      class="pane editor-pane"
      data-pane-id={editorPane.id}
      style={paneStyle(editorPane.id)}
      aria-label="Editor pane"
      onmousedown={() => focusPane(editorPane.id)}
    >
      <header class="pane-header" role="button" tabindex="0" aria-label="Move Editor pane" onkeydown={(event) => paneLayout.headerKeydown(event, editorPane.id)} onmousedown={(event) => paneLayout.startDrag(event, editorPane.id)}>
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
            onmousedown={(event) => event.stopPropagation()}
            onclick={() => editorPanes.requestDeleteScene(editorPane.id)}
          >
            Delete
          </button>
          <button
            class:active-pin={editorPane.pinned}
            class="pin-button"
            type="button"
            title={editorPane.pinned ? "Unpin this pane" : "Pin this pane"}
            onmousedown={(event) => event.stopPropagation()}
            onclick={() => editorPanes.togglePinned(editorPane.id)}
          >
            {editorPane.pinned ? "Pinned" : "Pin"}
          </button>
          <button
            class="pin-button"
            type="button"
            title="Close this editor pane"
            onmousedown={(event) => event.stopPropagation()}
            onclick={() => editorPanes.close(editorPane.id)}
          >
            Close
          </button>
        </div>
      </header>
      <NodeEditor
        bind:this={editorPanes.editorPaneComponents[editorPane.id]}
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
        metadataReload={editorPanes.metadataReloadsByPane[editorPane.id] ?? null}
        titleReload={editorPanes.titleReloadsByPane[editorPane.id] ?? null}
        dirty={editorPane.dirty}
        todoStatusHint={editorPane.document?.type === "scene" && editorPane.scene && sceneEntryHasBody(editorPane.scene as Scene) ? (editorPanes.embeddedTodoStatusHintsByPane[editorPane.id] ?? "") : ""}
        onFocus={() => focusPane(editorPane.id)}
        onChange={(detail) =>
          editorPanes.updateEditorPaneDraft(
            editorPane.id,
            detail.title,
            detail.body,
            detail.status,
            detail.entryType,
            detail.metadata,
            detail.inputs,
          )}
        onCustomData={(detail) => schemaPanes?.openForCustomData(detail.entryType, detail.kind)}
        onEmbeddedTodos={(detail) => editorPanes.updateEmbeddedTodosForPane(editorPane.id, detail.todos)}
        onNavigate={(detail) => navigateToBacklink(detail.id, detail.kind)}
        onOpenChat={(detail) => openChatFromPromptEntry(detail.entry, detail.inputs, detail.sceneId, detail.assistantId)}
      />
      <button class="pane-resize" type="button" aria-label="Resize Editor pane" onkeydown={(event) => paneLayout.resizeKeydown(event, editorPane.id)} onmousedown={(event) => paneLayout.startResize(event, editorPane.id)}></button>
    </section>
  {/each}

  <Pane id="todo" title="TODO" paneClass="todo-pane" hidden={!isPaneVisible("todo")} style={paneStyle("todo")} chrome={paneChrome}>
    {#snippet actions()}
      <button
        class="pin-button danger"
        type="button"
        disabled={!todos.some((item) => item.status === "done") && !editorPanes.allEmbeddedTodos.some((item) => item.status === "done")}
        title="Delete all completed TODOs"
        onmousedown={(event) => event.stopPropagation()}
        onclick={deleteCompletedTodos}
      >
        Delete Done
      </button>
    {/snippet}
    <div class="pane-content">
      <Todo
        {todos}
        embeddedTodos={editorPanes.allEmbeddedTodos}
        bind:newTodo
        onAddTodo={addTodo}
        onToggleTodo={toggleTodo}
        onUpdateTodoText={updateTodoText}
        onDeleteTodo={deleteTodo}
        onTodoTextKeydown={handleTodoTextKeydown}
        onOpenFileTodo={openFileTodo}
        onToggleEmbeddedTodo={(item) => editorPanes.toggleEmbeddedTodo(item)}
        onUpdateEmbeddedTodoNote={(item, note) => editorPanes.updateEmbeddedTodoNote(item, note)}
        onOpenEmbeddedTodo={openEmbeddedTodo}
        onDeleteEmbeddedTodo={(item) => editorPanes.deleteEmbeddedTodo(item)}
      />
    </div>
  </Pane>

  <Pane id="search" title="Search" paneClass="search-pane" hidden={!isPaneVisible("search")} style={paneStyle("search")} chrome={paneChrome}>
    <div class="pane-content">
      <Search {run} onOpenHit={openSearchHit} />
    </div>
  </Pane>

  <DirectoryPickerModal
    open={projectChooser.pickerOpen}
    listing={projectChooser.listing}
    loading={projectChooser.pickerLoading}
    onClose={() => projectChooser.closePicker()}
    onNavigate={(path) => projectChooser.loadDirectory(path)}
    onSelect={(path) => projectChooser.useDirectory(path)}
  />

  <ConfirmModal
    state={confirmService.active}
    onCancel={() => confirmService.dismiss()}
    onConfirm={(dontShowAgain) => confirmService.resolve(dontShowAgain)}
  />

  <NewProjectModal
    open={projectChooser.newProjectOpen}
    bind:name={projectChooser.newProjectName}
    bind:overrideFolder={projectChooser.overrideFolder}
    bind:overridePath={projectChooser.overridePath}
    resolvedPath={projectChooser.resolvedNewProjectPath}
    defaultProjectsFolder={projectChooser.defaultProjectsFolder}
    onClose={() => projectChooser.closeNewProject()}
    onSubmit={() => projectChooser.confirmNewProject()}
    onOpenOverrideFolderPicker={() => projectChooser.openForNewProjectOverride()}
    onOpenSettings={openMachineSettings}
    onClearOverride={() => projectChooser.clearOverride()}
  />

  <MachineSettingsDialog
    open={machineSettingsOpen}
    settings={machineSettings}
    bind:draft={machineSettingsDraft}
    onCancel={() => (machineSettingsOpen = false)}
    onSave={saveMachineSettings}
  />

  {#if tagsManagerOpen}
    <TagManagerDialog
      onChanged={() => void refreshAfterTagChange()}
      onClose={() => (tagsManagerOpen = false)}
    />
  {/if}

  {#if error}
    <section class="error-toast" role="alert">
      <span class="error-toast-body">{error}</span>
      <button
        class="error-toast-close"
        type="button"
        aria-label="Dismiss error"
        onclick={() => (error = "")}
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

