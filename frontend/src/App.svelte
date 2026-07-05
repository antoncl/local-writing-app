<script lang="ts">
  import { onMount, tick } from "svelte";
  import { api } from "@/lib/api";
  import CodeEditor from "@/components/widgets/CodeEditor.svelte";
  import NodeEditor from "@/components/editor/NodeEditor.svelte";
  import DirectoryPickerModal from "@/components/dialogs/DirectoryPickerModal.svelte";
  import SchemaPanes from "@/components/schema/SchemaPanes.svelte";
  import Tree from "@/components/panes/Tree.svelte";
  import Lore from "@/components/panes/Lore.svelte";
  import Assistants from "@/components/panes/Assistants.svelte";
  import Prompts from "@/components/panes/Prompts.svelte";
  import Mutations from "@/components/panes/Mutations.svelte";
  import Chats from "@/components/panes/Chats.svelte";
  import Project from "@/components/panes/Project.svelte";
  import Search from "@/components/panes/Search.svelte";
  import Todo from "@/components/panes/Todo.svelte";
  import Workspace from "@/components/workspace/Workspace.svelte";
  import { isLeafNode, entryTypeChoicesByKind } from "@/lib/utils/treeHelpers";
  import NewProjectModal from "@/components/dialogs/NewProjectModal.svelte";
  import MachineSettingsDialog from "@/components/dialogs/MachineSettingsDialog.svelte";
  import ConfirmModal from "@/components/dialogs/ConfirmModal.svelte";
  import PlainTextEditor from "@/components/widgets/PlainTextEditor.svelte";
  import PromptInputField from "@/components/widgets/PromptInputField.svelte";
  import TopBar from "@/components/chrome/TopBar.svelte";
  import { installThemeWiring, themePreference, nextPreference, type ThemePreference } from "@/lib/utils/theme";
  import { renderChatContent } from "@/lib/utils/chatMessageRender";
  import { get } from "svelte/store";
  import {
    chatSessionsStore,
    projectCostTotalStore,
    projectCostBreakdownStore,
    refreshProjectCost as storeRefreshProjectCost,
    setChatSessions,
    setProjectCost,
  } from "@/lib/stores/chats";
  import {
    todosStore,
    embeddedTodosStore,
    refreshTodos as storeRefreshTodos,
    refreshEmbeddedTodos as storeRefreshEmbeddedTodos,
  } from "@/lib/stores/todos";
  import { knownTagsStore, refreshKnownTags as storeRefreshKnownTags, setKnownTags } from "@/lib/stores/tags";
  import { assistantTagsStore, refreshAssistantTags, assistantTagsAsScoped } from "@/lib/stores/assistantTags";
  import { validationStore, setValidation } from "@/lib/stores/validation";
  import {
    structureStore,
    researchStructureStore,
    refreshStructure as storeRefreshStructure,
  } from "@/lib/stores/structure";
  import {
    loreEntriesStore,
    setLoreEntries,
  } from "@/lib/stores/lore";
  import {
    promptEntriesStore,
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
  import { paneViews } from "@/lib/stores/paneViews.svelte";
  import { evaluateView, treeNodeIds } from "@/lib/views/evaluateView";
  import { structureToEvalNodes } from "@/lib/views/structureNodes";
  import ViewSwitcher from "@/components/widgets/ViewSwitcher.svelte";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import { focusedDocumentStore } from "@/lib/stores/editorFocus";
  import { paneLayout } from "@/lib/stores/paneLayout.svelte";
  import { workspaceLayout, isEditorPanelId } from "@/lib/stores/workspaceLayout.svelte";
  import { type PresetName } from "@/lib/stores/workspaceLayout.serialize";
  import { layoutPresets } from "@/lib/stores/layoutPresets.svelte";
  import RegionRegistrar from "@/components/workspace/RegionRegistrar.svelte";
  import {
    type EditorPaneState,
    computeDraftTitleOverrides,
  } from "@/lib/editor-core/editorPaneModel";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import { confirmService } from "@/lib/stores/confirmService.svelte";
  import { projectChooser } from "@/lib/stores/projectChooser.svelte";
  import { projectSession } from "@/lib/stores/projectSession.svelte";
  import { aiSettings } from "@/lib/stores/aiSettings.svelte";
  import { todoActions } from "@/lib/stores/todoActions.svelte";
  import { treeActions } from "@/lib/stores/treeActions.svelte";
  import { chatSessions } from "@/lib/stores/chatSessions.svelte";
  import TagManagerDialog from "@/components/dialogs/TagManagerDialog.svelte";
  import AssistantTagManager from "@/components/dialogs/AssistantTagManager.svelte";
  import type {
    AssistantEntrySummary,
    Scene,
    NodePickerConfig,
    ProjectInfo,
    ProjectValidation,
    SearchHit,
    StructureDocument,
    StructureNode,
    TodoItem,
  } from "@/lib/types";

  type AppState =
    | { name: "needsProject" }
    | { name: "projectOpen"; project: ProjectInfo };
  // The tree rendering + inline CRUD live in Tree.svelte; the per-kind
  // TreeConfig contracts, node create/cascade-delete/collapse/add-menu actions,
  // and the lore→research migration live in the treeActions controller
  // (lib/stores/treeActions). App owns only the structure data it passes down.

  let projectPath = $state("");
  let projectTitle = $state("Untitled Project");

  // AI policy/provider/model-class, the provider health check, and the top-bar
  // project-color dot now live in the aiSettings controller (lib/stores/
  // aiSettings). App keeps project IDENTITY (appState) and folds the saved
  // project back via aiSettings.onProjectUpdated.

  // Machine settings (the dialog state, recents, last-opened persistence) and
  // the open/create/rehydrate flow live in the projectSession controller
  // (lib/stores/projectSession). App keeps project IDENTITY (appState below)
  // and injects the cross-subsystem workspace wiring as onOpenWorkspace.

  // Which chat is open in an editor pane lives on the editorPanes controller
  // (editorPanes.activeChatId); the chat-session roster + openers live in the
  // chatSessions controller (lib/stores/chatSessions).
  let projectCostExpanded = $state(false);
  let appState = $state<AppState>({ name: "needsProject" });
  let tagsManagerOpen = $state(false);
  let assistantTagManagerOpen = $state(false);
  // Sentinel key for the Lore "+ Entry" type-picker, reusing the tree add-menu
  // machinery (treeActions.toggleAddMenu / addMenuPosition / closeAddMenu). Lore
  // groups dynamically so it has no per-type "+ Entry" like Prompts — the
  // pane-header button offers the choice instead. Deprecated types (Note) are
  // filtered out by entryTypeChoicesByKind, so notes can't be created (#67).
  const LORE_ADD_MENU_KEY = "lore:new";
  let activeParentId: string | undefined = undefined;
  let draftTitleByScene = $state(new Map<string, string>());
  // The schema-authoring surface (state, the entry-type→kind→tree cascade, and
  // all persistence handlers) lives in SchemaPanes.svelte (#14 P0). App holds
  // only the instance ref so it can drive the three entry points.
  let schemaPanes: SchemaPanes | undefined = $state();
  // Instance ref so the pane handle bar's "+ New set" can open the editor.
  let mutationsPane: Mutations | undefined = $state();
  let error = $state("");
  let status = "No project open";
  // The editor-pane MDI surface (open panes, drafts, autosave lifecycle, the
  // open*/embedded-TODO bridge) lives in the editorPanes controller
  // (lib/stores/editorPanes). App keeps only the projections it renders.

  let cleanupThemeWiring: (() => void) | null = null;

  onMount(() => {
    // Raising the focused editor pane must also update focusedEditorPaneId; the
    // pane-layout controller stays ignorant of editor state and calls back here.
    // (editorPanes still drives focus through paneLayout.raise; the tiled shell
    // mirrors focusedEditorPaneId into the active tab via an effect below.)
    paneLayout.onRaise = (id) => {
      if (isEditorPanelId(id) && editorPanes.panes.some((pane) => pane.id === id)) {
        editorPanes.focusedEditorPaneId = id;
      }
    };
    // Clicking a tab in the tiled shell focuses that document too.
    workspaceLayout.onFocusPanel = (id) => {
      if (isEditorPanelId(id) && editorPanes.panes.some((pane) => pane.id === id)) {
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
    // AI settings save through App's run()/status; project identity (appState)
    // stays in App, so the save folds the updated project back via onProjectUpdated.
    aiSettings.run = run;
    aiSettings.setStatus = (message) => { status = message; };
    aiSettings.isProjectOpen = () => isProjectOpen;
    aiSettings.onProjectUpdated = (project) => {
      appState = { name: "projectOpen", project };
    };
    // Todo + search actions funnel through App's run()/status; a new todo scopes
    // to the focused scene (or stays project-level when none is open).
    todoActions.run = run;
    todoActions.setStatus = (message) => { status = message; };
    todoActions.getActiveSceneId = () => activeScene?.id;
    // Tree/node CRUD (create, cascade-delete, lore→research migrate, collapse,
    // add-menu) funnels through App's run()/status; editor-pane coupling lives
    // in the editorPanes module the controller imports directly.
    treeActions.run = run;
    treeActions.setStatus = (message) => { status = message; };
    // Chat-session roster sync + the openers/creators that route a chat into an
    // editor pane; editor coupling lives in the editorPanes module it imports.
    chatSessions.run = run;
    chatSessions.setStatus = (message) => { status = message; };
    chatSessions.setError = (message) => { error = message; };
    // Confirm actions flow through App's run() so errors surface in `error`.
    confirmService.onRun = run;
    // Project chooser drives only its modals; the projectSession controller
    // owns the open/create lifecycle. App feeds the picker its start dir +
    // error sink and routes its chosen path/title into projectSession.
    projectChooser.onRun = run;
    projectChooser.onError = (message) => { error = message; };
    projectChooser.onOpenProject = (path) => void projectSession.openProjectAt(path);
    projectChooser.onCreateProject = (path, title, baseFolder) =>
      projectSession.createProjectAt(path, title, baseFolder);
    projectChooser.getStartPath = () => projectPath;
    // The projectSession controller owns machine settings + the open/create/
    // rehydrate flow; App injects status/run and the cross-subsystem workspace
    // wiring (openProjectWorkspace) + the post-load schema sync.
    projectSession.run = run;
    projectSession.setStatus = (message) => { status = message; };
    projectSession.onOpenWorkspace = openProjectWorkspace;
    projectSession.onProjectDataLoaded = () => schemaPanes?.syncSelection();
    cleanupThemeWiring = installThemeWiring();
    document.addEventListener("mousedown", handleDocumentMousedown);
    // Eagerly fetch machine settings (so the chat panel + inputs dialog can show
    // the assistant roster without a round-trip) and auto-rehydrate the
    // last-opened project so an HMR reload / plain F5 doesn't drop the user back
    // to "No project open." Failure is non-fatal.
    void projectSession.rehydrate();
    // Assistant tags are machine-global (like the roster) — load once at startup
    // so colored chips + suggestions are ready before a project opens (#88).
    void refreshAssistantTags();
    return () => {
      paneLayout.dispose();
      editorPanes.dispose();
      document.removeEventListener("mousedown", handleDocumentMousedown);
      cleanupThemeWiring?.();
    };
  });

  function handleDocumentMousedown(event: MouseEvent) {
    const target = event.target as HTMLElement | null;
    const inAnchorOrPopover = target?.closest(".tree-menu-anchor, .row-add-popover");
    if (treeActions.addMenuOpenFor !== null && !inAnchorOrPopover) {
      treeActions.closeAddMenu();
    }
  }

  // The cross-subsystem workspace wiring, injected into projectSession as
  // onOpenWorkspace and run before loadProjectData. projectSession owns the
  // last-opened-project persistence; this just resets and re-seeds App's
  // many editor/AI/cost/color/chat subsystems for the newly opened project.
  function openProjectWorkspace(nextProject: ProjectInfo) {
    resetEditorWorkspace();
    projectPath = nextProject.root_path;
    treeActions.loadCollapseForProject(projectPath);
    workspaceLayout.loadForProject(projectPath);
    layoutPresets.load();
    projectTitle = nextProject.title;
    aiSettings.seedFromProject(nextProject);
    setProjectCost(null, []);
    projectCostExpanded = false;
    appState = { name: "projectOpen", project: nextProject };
    workspaceLayout.activate("outline");
    void chatSessions.hydrateForProject();
    void refreshProjectCost();
    void aiSettings.refreshProjectColor();
    void paneViews.loadForProject(projectPath);
  }

  async function refreshProjectCost(): Promise<void> {
    await storeRefreshProjectCost();
  }

  function resetEditorWorkspace() {
    editorPanes.reset();
    // Flush the current project's layout and detach before the next project's
    // loadForProject re-seeds it (openProjectWorkspace calls this first).
    workspaceLayout.closeForProject();
    paneViews.reset();
    setKnownTags([]);
    setChatSessions([]);
    // Preserve all pane configs. An earlier version stripped chat/preview/
    // prompts/assistants/chats out of `panes`, which made `panes.chats` etc.
    // undefined after a project switch — focusPane then created `{ z }` entries
    // with no left/top/width/height, and paneStyle returned an empty string,
    // so opening those panes did nothing visible. Pane positions and sizes are
    // pure UI state; nothing project-specific lives here.
  }

  // Look up an open editor document by its panel id (editor tabs render by id).
  const editorPaneById = (id: string) => editorPanes.panes.find((pane) => pane.id === id);

  // Stable key of the open editor documents (panes with loaded content), so the
  // reconcile effect below re-runs when a document opens/closes — not on every
  // keystroke (draft edits continuously reassign editorPanes.panes, but this
  // string is unchanged while the set of open ids is). Panel ids never contain "|".
  let openEditorDocKey = $derived(
    editorPanes.panes.filter((pane) => pane.document && pane.scene).map((pane) => pane.id).join("|"),
  );

  // Mirror open editor documents into the tiled layout: a document becomes a tab
  // once its content has loaded (a still-loading or failed-to-load pane never
  // flashes a blank "Editor" tab), and drops out when closed. The layout store
  // owns placement, editorPanes owns the document lifecycle — this reconciles them.
  $effect(() => {
    const openIds = new Set(openEditorDocKey ? openEditorDocKey.split("|") : []);
    for (const group of workspaceLayout.allGroups()) {
      for (const tab of [...group.tabs]) {
        if (isEditorPanelId(tab) && !openIds.has(tab)) workspaceLayout.removePanel(tab);
      }
    }
    for (const id of openIds) {
      if (!workspaceLayout.isPlaced(id)) workspaceLayout.ensureVisible(id);
    }
  });

  // Reflect the focused editor document as its group's active tab.
  $effect(() => {
    const focusedId = editorPanes.focusedEditorPaneId;
    if (focusedId && workspaceLayout.isPlaced(focusedId)) workspaceLayout.activate(focusedId);
  });

  // Noun for the pane's delete button, keyed by document kind (was a
  // scene/lore-only ternary that mislabelled view/prompt/chat panes).
  const PANE_DELETE_NOUN: Record<string, string> = {
    lore: "entry",
    research: "note",
    prompt: "prompt",
    assistant: "assistant",
    chat: "chat",
    view: "view",
  };
  const paneDeleteNoun = (type: string | undefined) => (type && PANE_DELETE_NOUN[type]) || "scene";

  // On-demand regions drop out of the layout when closed and reopen via
  // ensureVisible; the closer is handed to the registrar in markup below.
  const closeRegion = (id: string) => () => workspaceLayout.removePanel(id);

  // Move real keyboard focus onto a region group after a layout focus change so
  // the region is keyboard-reachable (design-language §4). rAF lets the DOM
  // settle (e.g. a collapsed split re-tiling) before we query for the element.
  function focusGroupDom(groupId: string | null) {
    if (!groupId) return;
    requestAnimationFrame(() => {
      // A group that lives inside a collapsed split has no element of its own
      // (the split renders as one strip); fall back to whichever group is now
      // showing the focused panel (`.ws-group.focused`).
      const el =
        document.querySelector<HTMLElement>(`[data-group-id="${groupId}"]`)
        ?? document.querySelector<HTMLElement>(".ws-group.focused");
      el?.focus();
    });
  }

  // Region keyboard nav (#155): Ctrl/Cmd+1…9 jump to the Nth region, F6 /
  // Shift+F6 cycle focus. These are modifier chords, so they're safe to handle
  // even while typing in the editor. (Ctrl+digit is reserved by browsers for
  // tab switching; add Alt — Ctrl+Alt+digit — in the browser, or use the
  // packaged app where the plain chord is free.)
  function handleWorkspaceKeydown(event: KeyboardEvent) {
    if (!isProjectOpen) return;
    if (event.key === "F6") {
      event.preventDefault();
      focusGroupDom(workspaceLayout.cycleFocus(event.shiftKey ? -1 : 1));
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key >= "1" && event.key <= "9") {
      event.preventDefault();
      focusGroupDom(workspaceLayout.focusGroupByIndex(Number(event.key) - 1));
    }
  }

  // Tab-bar accessors for open editor documents (the one dynamic surface class).
  const editorTitle = (id: string) => editorPaneById(id)?.scene?.title ?? "Editor";
  function editorBadge(id: string): { text: string; saved: boolean } | null {
    const pane = editorPaneById(id);
    if (!pane) return null;
    if (pane.saving) return { text: "Saving…", saved: false };
    if (pane.dirty) return { text: "Unsaved", saved: false };
    if (pane.recentlySaved) return { text: "Saved", saved: true };
    return null;
  }

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

  function paneEntryFromAncestor(pane: EditorPaneState): boolean {
    const layerId = pane.scene?.source_layer_id;
    if (!layerId) return false;
    const projectLayer = projectSchemaLayerId();
    if (!projectLayer) return false;
    return layerId !== projectLayer;
  }

  function openPromptsPane() {
    workspaceLayout.ensureVisible("prompts");
  }

  function openMutationsPane() {
    workspaceLayout.ensureVisible("mutations");
  }

  function openAssistantsPane() {
    void refreshAssistantEntries();
    workspaceLayout.ensureVisible("assistants");
  }

  function openChatsPane() {
    void chatSessions.refresh();
    workspaceLayout.ensureVisible("chats");
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

  function metadataListText(value: unknown) {
    if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean).join(", ");
    if (typeof value === "string") return value.trim();
    return "";
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
      await storeRefreshEmbeddedTodos();
      status = result.valid ? "Project repair complete" : "Project repair complete with remaining issues";
    });
  }

  // AI chat sessions. Per-chat state (history, composer, cost/TTL) lives
  // inside ChatBodyView now; App only tracks the session roster (Chats pane)
  // and which chat is currently open in an editor pane (active-row highlight).
  let chatSessionList = $derived($chatSessionsStore);
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
  // Assistant/prompt editors additionally offer the machine-global assistant-tag
  // vocabulary (#88, empty scope → suggest on every field of those editors).
  let assistantTagScoped = $derived(assistantTagsAsScoped($assistantTagsStore));
  let focusedEditorPane = $derived(editorPanes.panes.find((pane) => pane.id === editorPanes.focusedEditorPaneId) ?? editorPanes.panes[0] ?? null);
  // Write-through the focused doc to the editor-focus store so the list panes
  // read it directly instead of having it drilled in (#14 Step 2). App is the
  // sole writer (projection of editorPanes).
  $effect.pre(() => {
    focusedDocumentStore.set(focusedEditorPane?.document ?? null);
  });
  let activeScene = $derived(focusedEditorPane?.document?.type === "scene" ? focusedEditorPane.scene : null);
  let todos = $derived($todosStore);
  // The rebuildable embedded-todo index (GH #45); the Todo pane reads it directly,
  // and each editor pane derives its own status hint from the matching scene.
  let embeddedTodos = $derived($embeddedTodosStore);
  function embeddedHintForScene(sceneId: string): string {
    const items = embeddedTodos.filter((item) => item.scene_id === sceneId);
    if (items.length === 0) return "";
    const open = items.filter((item) => item.status === "open").length;
    const done = items.length - open;
    return `${open} open embedded TODO${open === 1 ? "" : "s"} · ${done} completed.`;
  }
  let validation = $derived($validationStore);
  let metadataSchema = $derived($metadataSchemaStore);
  let promptEntries = $derived($promptEntriesStore);
  let assistantEntries = $derived($assistantEntriesStore);
  // Selected-view specs/presentations per switchable pane (0.5.0 step 4, #81,
  // doc §5). These runes-side reads of paneViews bridge to the legacy `$:` panes
  // by flowing in as props (feedback_svelte5_reactivity_traps).
  let loreViewSpec = $derived(paneViews.specFor("lore"));
  let loreViewPresentation = $derived(paneViews.presentationFor("lore"));
  let assistantViewSpec = $derived(paneViews.specFor("assistant"));
  let assistantViewPresentation = $derived(paneViews.presentationFor("assistant"));
  // Draft: color annotations only — the tree keeps its structural shape
  // (ADR-0022). Evaluate the selected scene view over the flattened structure
  // and hand the per-node colors to the Tree; membership/ordering are ignored.
  let draftColorAnnotations = $derived.by(() => {
    const result = evaluateView(paneViews.specFor("scene"), structureToEvalNodes(structure), {
      schema: metadataSchema,
      resolveView: paneViews.resolveView,
    });
    const map = new Map<string, string | null>();
    for (const [id, ann] of result.annotations) map.set(id, ann.color);
    return map;
  });
  // Draft membership pruning (#101): when the selected view carries a filter,
  // narrow the tree to matching scenes + their kept ancestors (evaluate as a
  // `tree` and collect the surviving node ids). `null` = the whole-universe
  // default → no pruning, full structural tree.
  let draftVisibleIds = $derived.by(() => {
    const spec = paneViews.specFor("scene");
    if (!spec.expr && !(spec.groups && spec.groups.length)) return null;
    const result = evaluateView({ ...spec, presentation: "tree" }, structureToEvalNodes(structure), {
      schema: metadataSchema,
      resolveView: paneViews.resolveView,
    });
    return treeNodeIds(result.groups);
  });
  $effect.pre(() => {
    draftTitleByScene = computeDraftTitleOverrides(editorPanes.panes);
  });
  // Derived in the assistants store (not a function): consumers pass it as a
  // prop, and a bare call in a prop expression wouldn't track its inner roster
  // dependency. See feedback_svelte5_reactivity_traps.
  let defaultAssistantId = $derived($defaultAssistantIdStore);
</script>

<svelte:window on:keydown={handleWorkspaceKeydown} />

<TopBar
  currentTitle={isProjectOpen ? projectTitle : null}
  currentProjectColor={aiSettings.projectColor}
  recentProjects={projectSession.recentProjects}
  projectOpen={isProjectOpen}
  themePref={$themePreference}
  onCycleTheme={() => themePreference.update((p) => nextPreference(p))}
  onSelectRecent={(path) => void projectSession.openProjectAt(path)}
  onOpenFolder={() => projectChooser.openForOpenProject()}
  onNewProject={() => projectChooser.openNewProject()}
  onOpenAssistants={openAssistantsPane}
  onOpenSettings={() => void projectSession.openMachineSettings()}
  onOpenDetailTypes={() => schemaPanes?.openDetailTypes()}
  onOpenProjectNode={() => void editorPanes.openProjectNode()}
  activePreset={workspaceLayout.activePreset}
  userPresets={layoutPresets.presets.map((preset) => preset.name)}
  onApplyPreset={(name) => workspaceLayout.applyPreset(name as PresetName)}
  onApplyUserPreset={(name) => layoutPresets.apply(name)}
  onSavePreset={(name) => layoutPresets.save(name)}
  onDeleteUserPreset={(name) => layoutPresets.remove(name)}
  onResetLayout={() => workspaceLayout.reset()}
/>

<main class="app-main">
  {#if isProjectOpen}
    <Workspace
      title={editorTitle}
      badge={editorBadge}
      onClose={(id) => void editorPanes.close(id)}
      body={editorDocBody}
      actions={editorDocActions}
    />
  {:else}
    <div class="welcome">
      {@render projectBody()}
    </div>
  {/if}

  <!-- SchemaPanes stays mounted for its schema-authoring state; it now registers
       its Detail Types / Detail Type regions into the tiled shell rather than
       rendering its own floating panes. -->
  <SchemaPanes
    bind:this={schemaPanes}
    {isProjectOpen}
    {run}
    setStatus={(message) => (status = message)}
    refreshOpenEditorPaneBaselines={(transform) => editorPanes.refreshOpenEditorPaneBaselines(transform)}
    onOpenTagsManager={() => (tagsManagerOpen = true)}
  />

  <RegionRegistrar
    regions={{
      project: { title: "Project", body: projectBody },
      outline: { title: "Draft", body: outlineBody, actions: outlineActions },
      lore: { title: "Lore", body: loreBody, actions: loreActions },
      research: { title: "Research", body: researchBody },
      prompts: { title: "Prompts", body: promptsBody, closable: true, onClose: closeRegion("prompts") },
      mutations: { title: "Reusable mutations", body: mutationsBody, actions: mutationsActions, closable: true, onClose: closeRegion("mutations") },
      assistants: { title: "Assistants", body: assistantsBody, actions: assistantsActions, closable: true, onClose: closeRegion("assistants") },
      chats: { title: "Chats", body: chatsBody, actions: chatsActions, closable: true, onClose: closeRegion("chats") },
      todo: { title: "TODO", body: todoBody, actions: todoBarActions },
      search: { title: "Search", body: searchBody },
    }}
  />

  {#snippet projectBody()}
    <div class="pane-content project-panel">
      <Project
        {isProjectOpen}
        {projectTitle}
        {projectPath}
        {projectCostTotal}
        {projectCostBreakdown}
        aiHealthResult={aiSettings.healthResult}
        aiHealthChecking={aiSettings.healthChecking}
        {validation}
        bind:aiPolicy={aiSettings.policy}
        bind:aiDefaultProvider={aiSettings.defaultProvider}
        bind:aiDefaultModelClass={aiSettings.defaultModelClass}
        bind:projectCostExpanded
        onValidate={validateProject}
        onOpenChats={openChatsPane}
        onSaveAISettings={() => aiSettings.save()}
        onHealthCheck={() => aiSettings.runHealthCheck()}
        onOpenPrompts={openPromptsPane}
        onOpenMutations={openMutationsPane}
        onRepair={repairProject}
      />
    </div>
  {/snippet}

  {#snippet outlineActions()}
    <ViewSwitcher kind="scene" />
  {/snippet}
  {#snippet outlineBody()}
    <div class="pane-content">
      <Tree
        config={treeActions.manuscriptTree}
        {structure}
        colorAnnotations={draftColorAnnotations}
        visibleIds={draftVisibleIds}
        collapsed={treeActions.collapsedStructureNodes}        draftTitles={draftTitleByScene}
        sectionLabel="Scenes"
        emptyLabel="No scenes yet."
        {run}
        onRequestDelete={(node) => treeActions.requestDeleteTreeNode(treeActions.manuscriptTree, node)}
        addMenuOpenFor={treeActions.addMenuOpenFor}
        addMenuPosition={treeActions.addMenuPosition}
        onToggleAddMenu={(nodeId, event) => treeActions.toggleAddMenu(nodeId, event)}
        onCloseAddMenu={() => treeActions.closeAddMenu()}
      />
    </div>
  {/snippet}

  {#snippet loreActions()}
      <ViewSwitcher kind="lore" />
      <div class="tree-menu-anchor">
        <button
          class="pin-button"
          type="button"
          title="Add entry"
          onmousedown={(event) => event.stopPropagation()}
          onclick={(event) => treeActions.toggleAddMenu(LORE_ADD_MENU_KEY, event)}
        >+ Entry</button>
        {#if treeActions.addMenuOpenFor === LORE_ADD_MENU_KEY}
          <div
            class="row-add-popover"
            style={treeActions.addMenuPosition ? `top: ${treeActions.addMenuPosition.top}px; right: ${treeActions.addMenuPosition.right}px` : ""}
          >
            <span class="row-add-popover-heading">New entry</span>
            <NodeList isEmpty={entryTypeChoicesByKind(metadataSchema, "lore").length === 0}>
              {#each entryTypeChoicesByKind(metadataSchema, "lore") as choice (choice.id)}
                <NodeRow
                  title={choice.name}
                  onClick={() => { treeActions.newLoreEntry(choice.id); treeActions.closeAddMenu(); }}
                />
              {/each}
              {#snippet whenEmpty()}
                <p class="muted">No entry types defined.</p>
              {/snippet}
            </NodeList>
          </div>
        {/if}
      </div>
  {/snippet}
  {#snippet loreBody()}
    <div class="pane-content">
      <Lore
        entries={loreEntries}
        viewSpec={loreViewSpec}
        presentation={loreViewPresentation}
        onOpenEntry={(id) => editorPanes.openLore(id)}
        onMoveNoteToResearch={(entry) => treeActions.requestMoveLoreNoteToResearch(entry)}
      />
    </div>
  {/snippet}

  {#snippet researchBody()}
    <div class="pane-content">
      <Tree
        config={treeActions.researchTree}
        structure={researchStructure}
        collapsed={treeActions.collapsedResearchNodes}        draftTitles={draftTitleByScene}
        sectionLabel="Notes"
        emptyLabel="No topics or notes yet."
        {run}
        onRequestDelete={(node) => treeActions.requestDeleteTreeNode(treeActions.researchTree, node)}
        addMenuOpenFor={treeActions.addMenuOpenFor}
        addMenuPosition={treeActions.addMenuPosition}
        onToggleAddMenu={(nodeId, event) => treeActions.toggleAddMenu(nodeId, event)}
        onCloseAddMenu={() => treeActions.closeAddMenu()}
      />
    </div>
  {/snippet}

  {#snippet promptsBody()}
    <div class="pane-content schema-list">
      <Prompts
        entries={promptEntries}        onOpenEntry={(id) => editorPanes.openPrompt(id)}
        onNewEntry={(entryType) => treeActions.newPromptEntry(entryType)}
      />
    </div>
  {/snippet}

  {#snippet mutationsActions()}
    <button class="pin-button" type="button" title="New mutation set" onmousedown={(event) => event.stopPropagation()} onclick={() => mutationsPane?.openNew()}>+ New set</button>
  {/snippet}
  {#snippet mutationsBody()}
    <div class="pane-content schema-list">
      <Mutations
        bind:this={mutationsPane}
        loreEntries={loreEntries}
        promptEntries={promptEntries}
        structure={structure}
        researchStructure={researchStructure}
        knownTags={knownTags}
      />
    </div>
  {/snippet}

  {#snippet assistantsActions()}
      <ViewSwitcher kind="assistant" />
      <button class="pin-button" type="button" title="Add assistant" onmousedown={(event) => event.stopPropagation()} onclick={() => treeActions.newAssistantEntry()}>+ Assistant</button>
      <button class="pin-button" type="button" title="Assistant tag colors" onmousedown={(event) => event.stopPropagation()} onclick={() => (assistantTagManagerOpen = true)}>Tags…</button>
  {/snippet}
  {#snippet assistantsBody()}
    <div class="pane-content schema-list">
      <Assistants
        entries={assistantEntries}
        viewSpec={assistantViewSpec}
        presentation={assistantViewPresentation}
        defaultAssistantId={defaultAssistantId}
        onOpenEntry={(id) => editorPanes.openAssistant(id)}
        onReorder={reorderAssistantsInLayer}
      />
    </div>
  {/snippet}

  {#snippet chatsActions()}
    <button class="pin-button" type="button" title="Start a new chat" onmousedown={(event) => event.stopPropagation()} onclick={() => chatSessions.createNewChatSession()}>+ New Chat</button>
  {/snippet}
  {#snippet chatsBody()}
    <div class="pane-content schema-list">
      <Chats
        sessions={chatSessionList}
        activeChatId={editorPanes.activeChatId}
        promptEntries={promptEntries}
        assistantEntries={assistantEntries}
        onOpenChat={(id) => run(() => editorPanes.openChat(id))}
        onDeleteChat={(id) => chatSessions.deleteChatSessionFromPane(id)}
      />
    </div>
  {/snippet}

  {#snippet editorDocActions(id: string)}
    {@const editorPane = editorPaneById(id)}
    {#if editorPane}
      <button
        class="pin-button danger"
        type="button"
        disabled={!editorPane.scene}
        title={`Delete this ${paneDeleteNoun(editorPane.document?.type)}`}
        onmousedown={(event) => event.stopPropagation()}
        onclick={() => editorPanes.requestDeleteScene(editorPane.id)}
      >
        Delete
      </button>
    {/if}
  {/snippet}
  {#snippet editorDocBody(id: string)}
    {@const editorPane = editorPaneById(id)}
    {#if editorPane}
      {#if paneEntryFromAncestor(editorPane)}
        <div class="ancestor-banner" title="This entry lives in an ancestor project. Edits write back to the original file.">
          from {editorPane.scene?.source_layer_label ?? "ancestor"}
        </div>
      {/if}
      <NodeEditor
        bind:this={editorPanes.editorPaneComponents[editorPane.id]}
        scene={editorPane.scene}
        documentKind={editorPane.document?.type ?? "scene"}
        promptEntries={promptEntries}
        structure={structure}
        researchStructure={researchStructure}
        loreEntries={loreEntries}
        knownTags={editorPane.document?.type === "assistant" || editorPane.document?.type === "prompt"
          ? [...knownTags, ...assistantTagScoped]
          : knownTags}
        implicitContextMatcher={implicitContextMatcher}
        assistantEntries={assistantEntries}
        defaultAssistantId={defaultAssistantId}
        availableScenes={flattenStructureScenes(structure?.root)}
        metadataReload={editorPanes.metadataReloadsByPane[editorPane.id] ?? null}
        titleReload={editorPanes.titleReloadsByPane[editorPane.id] ?? null}
        dirty={editorPane.dirty}
        todoStatusHint={editorPane.document?.type === "scene" && editorPane.scene && sceneEntryHasBody(editorPane.scene as Scene) ? embeddedHintForScene(editorPane.scene.id) : ""}
        onFocus={() => workspaceLayout.focus(editorPane.id)}
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
        onNavigate={(detail) => navigateToBacklink(detail.id, detail.kind)}
        onOpenChat={(detail) => chatSessions.openChatFromPromptEntry(detail.entry, detail.inputs, detail.sceneId, detail.assistantId)}
      />
    {/if}
  {/snippet}

  {#snippet todoBarActions()}
    <button
      class="pin-button danger"
      type="button"
      disabled={!todos.some((item) => item.status === "done") && !embeddedTodos.some((item) => item.status === "done")}
      title="Delete all completed TODOs"
      onmousedown={(event) => event.stopPropagation()}
      onclick={() => todoActions.deleteCompletedTodos()}
    >
      Delete Done
    </button>
  {/snippet}
  {#snippet todoBody()}
    <div class="pane-content">
      <Todo
        {todos}
        {embeddedTodos}
        bind:newTodo={todoActions.newTodo}
        onAddTodo={() => todoActions.addTodo()}
        onToggleTodo={(item) => todoActions.toggleTodo(item)}
        onUpdateTodoText={(item, text) => todoActions.updateTodoText(item, text)}
        onDeleteTodo={(item) => todoActions.deleteTodo(item)}
        onTodoTextKeydown={(event, item) => todoActions.handleTodoTextKeydown(event, item)}
        onOpenFileTodo={(item) => todoActions.openFileTodo(item)}
        onToggleEmbeddedTodo={(item) => todoActions.toggleEmbeddedTodo(item)}
        onUpdateEmbeddedTodoNote={(item, note) => todoActions.updateEmbeddedTodoNote(item, note)}
        onOpenEmbeddedTodo={(item) => todoActions.openEmbeddedTodo(item)}
        onDeleteEmbeddedTodo={(item) => todoActions.deleteEmbeddedTodo(item)}
      />
    </div>
  {/snippet}

  {#snippet searchBody()}
    <div class="pane-content">
      <Search {run} onOpenHit={(hit) => todoActions.openSearchHit(hit)} />
    </div>
  {/snippet}

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
    onSecondary={() => confirmService.resolveSecondary()}
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
    onOpenSettings={() => void projectSession.openMachineSettings()}
    onClearOverride={() => projectChooser.clearOverride()}
  />

  <MachineSettingsDialog
    open={projectSession.machineSettingsOpen}
    settings={projectSession.machineSettings}
    bind:draft={projectSession.machineSettingsDraft}
    onCancel={() => (projectSession.machineSettingsOpen = false)}
    onSave={() => void projectSession.saveMachineSettings()}
  />

  {#if tagsManagerOpen}
    <TagManagerDialog
      onChanged={() => void refreshAfterTagChange()}
      onClose={() => (tagsManagerOpen = false)}
    />
  {/if}

  {#if assistantTagManagerOpen}
    <AssistantTagManager onClose={() => (assistantTagManagerOpen = false)} />
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
  /* Main area below the top bar. The tiled Workspace fills it; before a project
     opens, the Project region shows centred as a welcome surface. */
  .app-main {
    display: flex;
    flex-direction: column;
    width: 100vw;
    height: calc(100vh - 40px);
    margin-top: 40px;
    overflow: hidden;
  }

  .welcome {
    flex: 1 1 auto;
    min-height: 0;
    display: flex;
    justify-content: center;
    align-items: flex-start;
    padding: var(--sp-5);
    overflow: auto;
  }
  .welcome > :global(.project-panel) {
    width: min(560px, 100%);
  }

  /* Project region content wrapper (rendered as a snippet into the shell). */
  .project-panel {
    display: grid;
    align-content: start;
    gap: var(--sp-2);
    padding: var(--sp-3);
  }

  /* Ancestor-entry documents: a slim banner above the editor (edits still write
     back to the ancestor file). Replaces the old header tint + badge. */
  .ancestor-banner {
    flex: 0 0 auto;
    padding: var(--sp-1) var(--sp-3);
    background: var(--star-soft);
    border-bottom: 1px solid var(--star-border);
    color: var(--text-2);
    font-size: var(--fs-xs);
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
    box-shadow: var(--elev-3);
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
    font-size: var(--fs-xl);
    line-height: 1;
    cursor: pointer;
  }

  .error-toast-close:hover {
    background: color-mix(in srgb, var(--danger) 12%, transparent);
  }
</style>

