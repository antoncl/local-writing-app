<script lang="ts">
  import { onMount, tick } from "svelte";
  import { api } from "@/lib/api";
  import { installGlobalErrorLogging, reportClientError } from "@/lib/errorLog";
  import CodeEditor from "@/components/widgets/CodeEditor.svelte";
  import NodeEditor from "@/components/editor/NodeEditor.svelte";
  import DirectoryPickerModal from "@/components/dialogs/DirectoryPickerModal.svelte";
  import SchemaPanes from "@/components/schema/SchemaPanes.svelte";
  import StructureTree from "@/components/panes/StructureTree.svelte";
  import Lore from "@/components/panes/Lore.svelte";
  import Assistants from "@/components/panes/Assistants.svelte";
  import Prompts from "@/components/panes/Prompts.svelte";
  import PlotTemplates from "@/components/panes/PlotTemplates.svelte";
  import PlotBoardPane from "@/components/panes/PlotBoardPane.svelte";
  import Mutations from "@/components/panes/Mutations.svelte";
  import GuideView from "@/components/panes/GuideView.svelte";
  import AiSpendPane from "@/components/panes/AiSpendPane.svelte";
  import MutationSetEditor from "@/components/editor/body/MutationSetEditor.svelte";
  import {
    openNewMutationSet,
    mutationSetEditorStore,
    closeMutationSetEditor,
    refreshMutationSetEntries,
  } from "@/lib/stores/mutationSets";
  import { refreshReferenceIndexInBackground } from "@/lib/stores/references";
  import Chats from "@/components/panes/Chats.svelte";
  import Search from "@/components/panes/Search.svelte";
  import Todo from "@/components/panes/Todo.svelte";
  import Workspace from "@/components/workspace/Workspace.svelte";
  import { isLeafNode, findNodeBySceneId } from "@/lib/utils/treeHelpers";
  import { structureNodeTitle } from "@/lib/utils/nodeTitle";
  import CreateProjectWizard from "@/components/dialogs/CreateProjectWizard.svelte";
  import MachineSettingsDialog from "@/components/dialogs/MachineSettingsDialog.svelte";
  import ImportDocumentsModal from "@/components/dialogs/ImportDocumentsModal.svelte";
  import ConfirmModal from "@/components/dialogs/ConfirmModal.svelte";
  import ConflictDiffModal from "@/components/dialogs/ConflictDiffModal.svelte";
  import FinalizeRoleplayDialog from "@/components/dialogs/FinalizeRoleplayDialog.svelte";
  import AIPolicyModal from "@/components/dialogs/AIPolicyModal.svelte";
  import ValidateModal from "@/components/dialogs/ValidateModal.svelte";
  import PromoteAction from "@/components/dialogs/PromoteAction.svelte";
  import PlainTextEditor from "@/components/widgets/PlainTextEditor.svelte";
  import PromptInputField from "@/components/widgets/PromptInputField.svelte";
  import TopBar from "@/components/chrome/TopBar.svelte";
  import { installThemeWiring, themePreference, nextPreference, type ThemePreference } from "@/lib/utils/theme";
  import { renderChatContent } from "@/lib/utils/chatMessageRender";
  import { declarationRows, toggledDeclaration } from "@/lib/utils/projectChain";
  import { get } from "svelte/store";
  import { chatSessionsStore, setChatSessions } from "@/lib/stores/chats";
  import {
    todosStore,
    embeddedTodosStore,
    refreshTodos as storeRefreshTodos,
    refreshEmbeddedTodos as storeRefreshEmbeddedTodos,
  } from "@/lib/stores/todos";
  import { knownTagsStore, refreshKnownTags as storeRefreshKnownTags, setKnownTags, tagVocabularyRevision } from "@/lib/stores/tags";
  import { assistantTagsStore, refreshAssistantTags, assistantTagsAsScoped } from "@/lib/stores/assistantTags";
  import { validationStore, setValidation, clearValidation } from "@/lib/stores/validation";
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
  import { plotTemplatesStore } from "@/lib/stores/plotTemplates";
  import { refreshPlotBoard } from "@/lib/stores/plotBoard";
  import { plotlineReveal } from "@/lib/stores/plotlines";
  import { openProjectHidden } from "@/lib/stores/hiddenLibrary";
  import {
    assistantEntriesStore,
    defaultAssistantIdStore,
    refreshAssistantEntries as storeRefreshAssistantEntries,
    setAssistantEntries,
  } from "@/lib/stores/assistants";
  import {
    metadataSchemaStore,
    projectLayerIdStore,
  } from "@/lib/stores/schema";
  import { isInherited, readOnlyInPlace } from "@/lib/utils/provenance";
  import { implicitContextMatcherStore } from "@/lib/stores/derived";
  import { paneViews } from "@/lib/stores/paneViews.svelte";
  import { focusedDocumentStore } from "@/lib/stores/editorFocus";
  import { workspaceLayout, isEditorPanelId } from "@/lib/stores/workspaceLayout.svelte";
  import { editorRailLayout } from "@/lib/stores/editorRailLayout.svelte";
  import { type PresetName } from "@/lib/stores/workspaceLayout.serialize";
  import { layoutPresets } from "@/lib/stores/layoutPresets.svelte";
  import RegionRegistrar from "@/components/workspace/RegionRegistrar.svelte";
  import {
    type EditorPaneState,
    computeDraftTitleOverrides,
  } from "@/lib/editor-core/editorPaneModel";
  import { editorPanes } from "@/lib/stores/editorPanes.svelte";
  import { roleplayPresence } from "@/lib/stores/roleplayPresence.svelte";
  import { flushDirtyPanesOnHide } from "@/lib/stores/editorPaneSave";
  import { entryBrainstorm } from "@/lib/stores/entryBrainstorm.svelte";
  import { confirmService } from "@/lib/stores/confirmService.svelte";
  import { conflictDiffService } from "@/lib/stores/conflictDiffService.svelte";
  import { projectChooser } from "@/lib/stores/projectChooser.svelte";
  import { createWizard } from "@/lib/stores/createWizard.svelte";
  import { projectSession } from "@/lib/stores/projectSession.svelte";
  import { aiSettings } from "@/lib/stores/aiSettings.svelte";
  import { todoActions } from "@/lib/stores/todoActions.svelte";
  import { treeActions } from "@/lib/stores/treeActions.svelte";
  import { chatSessions } from "@/lib/stores/chatSessions.svelte";
  import { aiSpend } from "@/lib/stores/aiSpend.svelte";
  import {
    openPromptsPane,
    openPlotTemplatesPane,
    openMutationsPane,
    openGuidePane,
    openAiSpendPane,
    openAssistantsPane,
    openChatsPane,
  } from "@/lib/stores/paneOpeners";
  import TagManagerDialog from "@/components/dialogs/TagManagerDialog.svelte";
  import type {
    AssistantEntrySummary,
    CodeFencedBody,
    Scene,
    LooseScene,
    NodePickerConfig,
    ProjectInfo,
    ProjectValidation,
    SearchHit,
    StructureDocument,
    StructureNode,
    TodoItem,
    ViewSpec,
  } from "@/lib/types";

  type AppState =
    | { name: "needsProject" }
    | { name: "projectOpen"; project: ProjectInfo };
  // The tree rendering + inline CRUD live in StructureTree.svelte (via
  // ViewNodeList); the per-kind TreeConfig contracts, node
  // create/cascade-delete/add-menu actions, and the lore→research migration
  // live in the treeActions controller (lib/stores/treeActions). App owns only
  // the structure data + view spec it passes down.

  let projectPath = $state("");
  let projectTitle = $state("Untitled Project");

  // AI policy, the provider health check, and the top-bar
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
  let appState = $state<AppState>({ name: "needsProject" });
  // One "Manage tags" home governs both vocabularies (#247 PR-3b).
  let tagsManagerOpen = $state(false);
  // The finalize-roleplay modal (ADR-0070 S3), opened imperatively from the ≡ menu.
  let finalizeDialog = $state<FinalizeRoleplayDialog | null>(null);
  // "Import documents" (#635) — the loose-scene adoption surface, opened from the
  // app menu. Its list comes from its own read, not the validation report.
  let importDocsOpen = $state(false);
  // The per-project AI policy modal, launched from the project node window's
  // action (#417). App owns the guard, like the other dialogs.
  let aiPolicyModalOpen = $state(false);
  // The project-validation modal, launched from the same project window action
  // strip (#417). `validating` drives the modal's "Checking…" state; both
  // validate and repair toggle it so the result never flashes stale.
  let validateModalOpen = $state(false);
  let validating = $state(false);
  let looseScenes = $state<LooseScene[]>([]);
  let importBusy = $state(false);
  // The Lore pane owns its own add-menu (a ViewNodeList feature, #112 4c-iv); this
  // ref lets the pane-header "+ Entry" button drive it.
  let loreRef = $state<{ toggleAddMenu: (event?: MouseEvent) => void; isAddMenuOpen: () => boolean }>();
  let promptsRef = $state<{ toggleAddMenu: (event?: MouseEvent) => void; isAddMenuOpen: () => boolean }>();
  let activeParentId: string | undefined = undefined;
  let draftTitleByScene = $state(new Map<string, string>());
  // The schema-authoring surface (state, the entry-type→kind→tree cascade, and
  // all persistence handlers) lives in SchemaPanes.svelte (#14 P0). App holds
  // only the instance ref so it can drive the three entry points.
  let schemaPanes: SchemaPanes | undefined = $state();
  let error = $state("");
  let status = "No project open";
  // The editor-pane MDI surface (open panes, drafts, autosave lifecycle, the
  // open*/embedded-TODO bridge) lives in the editorPanes controller
  // (lib/stores/editorPanes). App keeps only the projections it renders.

  let cleanupThemeWiring: (() => void) | null = null;

  onMount(() => {
    // Catch the failures that never reach run() — uncaught render errors, dropped
    // promises — and record them to the project's errors.log too (#386).
    installGlobalErrorLogging();
    // Clicking a tab in the tiled shell focuses that document; editorPanes sets
    // focusedEditorPaneId directly when it opens/raises a pane, and the effect
    // below mirrors that into the active tab.
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
    conflictDiffService.onRun = run;
    // Project chooser drives only the open-project picker; the projectSession
    // controller owns the open/create lifecycle. App feeds the picker its start
    // dir + error sink and routes its chosen path into projectSession.
    projectChooser.onError = (message) => { error = message; };
    projectChooser.onOpenProject = (path) => void projectSession.openProjectAt(path);
    projectChooser.getStartPath = () => projectPath;
    // The create-project wizard (#318) owns new-project creation now. It writes
    // the machine root itself (step 1, first run) and hands projectSession the
    // resolved path/title/declaration on Create.
    createWizard.onError = (message) => { error = message; };
    createWizard.getStartPath = () => projectPath;
    createWizard.onSaveRootFolder = (folder) => projectSession.saveDefaultProjectsFolder(folder);
    createWizard.onCreateProject = (path, title, inherits, aiPolicy, nodeMetadata, description) =>
      projectSession.createProjectAt(path, title, inherits, aiPolicy, nodeMetadata, description);
    // AI-step substrate (#547). Provider credentials + assistants are
    // machine-global, so every write forces the machine layer (layer_id "") and
    // the new book inherits the result — the wizard has no project of its own
    // yet. See the create-timing note on #547.
    createWizard.getMachineSettings = () => projectSession.machineSettings;
    createWizard.onSaveProviderCredential = (field, value) =>
      projectSession.saveProviderCredential(field, value);
    // First-run AI policy is the app-wide default (#746) — machine-global like
    // the credentials/assistants above; the new book inherits it.
    createWizard.onSaveAppPolicy = async (policy) => {
      await projectSession.saveAiPolicy(policy);
    };
    createWizard.onReorderAssistants = async (orderedIds) => {
      await run(async () => {
        setAssistantEntries((await api.reorderAssistants(orderedIds, "")).entries);
      });
    };
    createWizard.onUnlistAssistant = async (entryId) => {
      await run(async () => {
        setAssistantEntries((await api.unlistAssistant(entryId, "")).entries);
      });
    };
    createWizard.onHireAssistant = async (title, provider, tier, model) => {
      await run(async () => {
        const created = await api.createAssistantEntry(title, "");
        await api.saveAssistantEntry({
          ...created,
          metadata: {
            ...created.metadata,
            ai_provider: provider,
            ai_capability_tier: tier,
            ai_model: model,
          },
        });
        await storeRefreshAssistantEntries();
      });
    };
    // The projectSession controller owns machine settings + the open/create/
    // rehydrate flow; App injects status/run and the cross-subsystem workspace
    // wiring (openProjectWorkspace) + the post-load schema sync.
    projectSession.run = run;
    projectSession.setStatus = (message) => { status = message; };
    projectSession.onOpenWorkspace = openProjectWorkspace;
    projectSession.onProjectDataLoaded = () => schemaPanes?.syncSelection();
    // A declaration change (#426) returns a fresh project without opening one,
    // so it folds in the same way an AI-settings save does — appState only, no
    // workspace teardown.
    projectSession.onProjectUpdated = (project) => {
      appState = { name: "projectOpen", project };
    };
    cleanupThemeWiring = installThemeWiring();
    // Eagerly fetch machine settings (so the chat panel + inputs dialog can show
    // the assistant roster without a round-trip) and auto-rehydrate the
    // last-opened project so an HMR reload / plain F5 doesn't drop the user back
    // to "No project open." Failure is non-fatal.
    void projectSession.rehydrate();
    // Assistant tags are machine-global (like the roster) — load once at startup
    // so colored chips + suggestions are ready before a project opens (#88).
    void refreshAssistantTags();
    // Flush dirty panes on the way out (#369). `visibilitychange: hidden` fires
    // earlier and more reliably (tab switch, minimize, mobile background) while
    // the page is still alive to complete a normal, uncapped save. `pagehide` is
    // the terminal backstop (tab/window close, navigation); only it needs the
    // keepalive hint (whose ~64KB body cap is why the visibility path stays
    // normal). Between them a paragraph typed just before leaving reaches disk.
    const onPageHide = () => void flushDirtyPanesOnHide(editorPanes, { keepalive: true });
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") void flushDirtyPanesOnHide(editorPanes);
    };
    window.addEventListener("pagehide", onPageHide);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("pagehide", onPageHide);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      editorPanes.dispose();
      cleanupThemeWiring?.();
    };
  });

  // The cross-subsystem workspace wiring, injected into projectSession as
  // onOpenWorkspace and run before loadProjectData. projectSession owns the
  // last-opened-project persistence; this just resets and re-seeds App's
  // many editor/AI/color/chat subsystems for the newly opened project.
  function openProjectWorkspace(nextProject: ProjectInfo) {
    resetEditorWorkspace();
    projectPath = nextProject.root_path;
    openProjectHidden(projectPath);
    workspaceLayout.loadForProject(projectPath);
    editorRailLayout.loadForProject(projectPath);
    layoutPresets.load();
    projectTitle = nextProject.title;
    aiSettings.seedFromProject(nextProject);
    appState = { name: "projectOpen", project: nextProject };
    workspaceLayout.activate("outline");
    void chatSessions.hydrateForProject();
    void aiSettings.refreshProjectColor();
    void paneViews.loadForProject(projectPath);
  }

  function resetEditorWorkspace() {
    editorPanes.reset();
    // Flush the current project's layout and detach before the next project's
    // loadForProject re-seeds it (openProjectWorkspace calls this first).
    workspaceLayout.closeForProject();
    paneViews.reset();
    setKnownTags([]);
    setChatSessions([]);
    // The AI Spend singleton would otherwise paint the previous project's
    // totals under the next one until its refetch lands.
    aiSpend.reset();
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

  // Reflect the focused editor document as its group's active tab — but only
  // when the focused pane actually *changes* (#1470). `activate()` raises the
  // tab and pulls DOM focus; firing it on every effect re-run (e.g. a background
  // autosave re-rendering the pane) yanks focus back from wherever the user has
  // since moved — the guide, another pane — every few seconds. Guarding on a
  // real change keeps the tab-sync intent without the theft.
  let lastActivatedFocusId: string | null = null;
  $effect(() => {
    const focusedId = editorPanes.focusedEditorPaneId;
    if (focusedId === lastActivatedFocusId) return;
    lastActivatedFocusId = focusedId;
    if (focusedId && workspaceLayout.isPlaced(focusedId)) workspaceLayout.activate(focusedId);
  });

  // A plotline backlink no longer opens an editor pane — it asks to be revealed on the
  // board (ADR-0053 §3, plotlineReveal). Bring the board pane into view; PlotEditor
  // expands the target node and clears the one-shot once its projection is in.
  $effect(() => {
    if ($plotlineReveal) openPlotBoardPane();
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
    plot_template: "template",
    plot_card: "card",
    plotline: "plotline",
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
    // Ctrl+M: maximize (zoom) the focused tile / restore it (#219, §F). Ctrl
    // only, NOT Cmd — Cmd+M is the macOS/Electron "minimize window" shortcut
    // (and preventDefault can't reliably suppress that OS-level chord).
    if (event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && event.key.toLowerCase() === "m") {
      event.preventDefault();
      workspaceLayout.toggleZoomFocused();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key >= "1" && event.key <= "9") {
      event.preventDefault();
      focusGroupDom(workspaceLayout.focusGroupByIndex(Number(event.key) - 1));
    }
  }

  // Tab-bar accessors for open editor documents (the one dynamic surface class).
  // A manuscript pane resolves through the shared display-title resolver so its
  // reorder-live {number} rides the tab too ("Scene 3"); reading `structure`
  // (a $derived over the store) keeps it live on reorder. Non-manuscript panes
  // (lore, chat, research) aren't in the manuscript tree → fall back to the raw
  // scene title, unchanged.
  const editorTitle = (id: string) => {
    const pane = editorPaneById(id);
    if (!pane?.scene) return "Editor";
    const node = structure?.root ? findNodeBySceneId(structure.root, pane.scene.id) : null;
    return node ? structureNodeTitle(node, metadataSchema) : pane.scene.title;
  };
  function editorBadge(id: string): { text: string; saved: boolean; error?: boolean } | null {
    const pane = editorPaneById(id);
    if (!pane) return null;
    // A failed save outranks every other state: it must stay visible on the tab
    // even after the author moves on, and never look "saved" (#263).
    if (pane.saveError) return { text: "Save failed", saved: false, error: true };
    if (pane.saving) return { text: "Saving…", saved: false };
    if (pane.dirty) return { text: "Unsaved", saved: false };
    if (pane.recentlySaved) return { text: "Saved", saved: true };
    return null;
  }
  // The #710 slice-3 hand-off dot: resolve the tab's panel id to its node id and
  // ask the brainstorm bridge whether a review is pending there. Reactive because
  // both the pane list and entryBrainstorm's map are `$state`, so the dot clears
  // the moment the review is committed or discarded on the entry.
  function editorReviewPending(id: string): boolean {
    const nodeId = editorPaneById(id)?.scene?.id;
    return nodeId != null && entryBrainstorm.hasProposalFor(nodeId);
  }

  // The funnel every user action's failure collapses through — the frontend
  // choke point twin of the backend error middleware (ADR-0056 §2/§4, #386).
  // Actions route their failures here (and the global listeners in errorLog.ts
  // catch the rest) so logging happens by construction, not by each site
  // remembering to. Keep it one funnel; don't scatter per-action try/catch.
  async function run(action: () => Promise<void>): Promise<boolean> {
    error = "";
    try {
      await action();
      return true;
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
      // The on-screen string is erased by the next action; also record it durably
      // so a failure the author didn't read in time isn't lost forever (#386).
      reportClientError(caught, "run");
      return false;
    }
  }

  async function refreshStructure() {
    await storeRefreshStructure();
  }

  // Persist the assistant priority sequence computed by Assistants.svelte.
  // App owns assistantEntries (the chat pane reads it too), so the api calls +
  // state update stay here; the drag UI lives in the component. Both write to
  // the LOCAL layer — curation is the open project's opinion (#332/#333) — so
  // neither takes a layer id and the pane does no layer arithmetic.
  async function setAssistantOrder(orderedIds: string[]) {
    await run(async () => {
      setAssistantEntries((await api.reorderAssistants(orderedIds)).entries);
    });
  }

  async function unlistAssistant(entryId: string) {
    await run(async () => {
      setAssistantEntries((await api.unlistAssistant(entryId)).entries);
    });
  }

  async function refreshAssistantEntries() {
    await storeRefreshAssistantEntries();
  }

  async function refreshKnownTags() {
    await storeRefreshKnownTags();
  }

  // A tag merge/rename rewrites tag values across documents on disk; pull the new
  // rosters AND re-sync the entry lists + open editors so the change is reflected
  // everywhere immediately (not just on next reload). One reconcile serves BOTH
  // vocabularies (#247 PR-3): assistant governance flows through the same
  // vocabulary-revision signal, and its rename/merge rewrites assistant nodes
  // (`metadata.tags`) + prompt docs (`metadata.assistant_tags`), so the assistant
  // roster + list belong here too. Refreshing the untouched vocabulary on a given
  // op is two cheap GETs — the uniform reconcile is worth that over two signals.
  async function refreshAfterTagChange() {
    await refreshKnownTags();
    await refreshAssistantTags();
    await run(async () => {
      setLoreEntries((await api.listLoreEntries()).entries);
      setPromptEntries((await api.listPromptEntries()).entries);
      await refreshAssistantEntries();
      await editorPanes.refreshOpenEditorPaneBaselines();
    });
  }

  // Any vocabulary-governance op (the + popover's governance surface, the tag
  // manager) bumps `tagVocabularyRevision` after it rewrites tags on disk;
  // reconcile once, here — so no picker has to thread a callback up through the
  // components between it and App just to re-sync (#247). Skips the initial 0.
  $effect(() => {
    if ($tagVocabularyRevision > 0) void refreshAfterTagChange();
  });

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
    // For an ADR-0049 Library tenant (a prompt, or a plot template — ADR-0048
    // S4c) the banner's "inherited / read-only here" is the backend's own
    // `editable` verdict, read through the SAME helper as NodeEditor's read-only
    // lock (#689) — so the banner and the lock cannot disagree. This also drops
    // the tenant path's dependence on the async schema store: the flag rides on
    // the document, so the banner no longer lags the lock during schema load (the
    // #676 review's concern, now removed rather than worked around).
    if (pane.document?.type === "prompt" || pane.document?.type === "plot_template") {
      return readOnlyInPlace(pane.scene);
    }
    // Lore and other inheritable kinds keep the display-only provenance read
    // (#313), shared with the level pill and rail treatment. Reads the store
    // REACTIVELY so the banner re-renders when the schema layers finish loading;
    // fails open in the gap, which is fine for a non-gating affordance.
    return isInherited({ source_layer_id: pane.scene?.source_layer_id }, $projectLayerIdStore);
  }

  function openPlotBoardPane() {
    // Fetch-then-show, like openChatsPane / openAssistantsPane — but through run()
    // so an HTTP error surfaces in the banner rather than being swallowed. The
    // pane opens immediately and shows "Loading…" until the projection resolves.
    void run(() => refreshPlotBoard());
    workspaceLayout.ensureVisible("plotEditor");
  }

  function sceneEntryHasBody(scene: Scene): boolean {
    const entryDefinition = metadataSchema?.entry_types[scene.entry_type];
    return entryDefinition?.has_body ?? true;
  }

  // Every kind the reference index can produce, not lore-else-scene (#344).
  // The dispatch lives on the controller with the openers it chooses between;
  // `run` puts an unopenable kind's message in the error banner.
  function navigateToBacklink(id: string, kind: string) {
    void run(() => editorPanes.openNodeOfKind(id, kind));
  }

  function metadataListText(value: unknown) {
    if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean).join(", ");
    if (typeof value === "string") return value.trim();
    return "";
  }

  async function validateProject() {
    // Drop the prior result before re-checking so a run that fails mid-flight
    // (run() swallows the error) can't leave a stale "looks consistent" on the
    // modal — `validating` masks the cleared state until a fresh result lands.
    clearValidation();
    validating = true;
    try {
      await run(async () => {
        const result = await api.validateProject();
        setValidation(result);
        status = result.valid ? "Project validation passed" : "Project validation found issues";
      });
    } finally {
      validating = false;
    }
  }

  async function repairProject() {
    clearValidation();
    validating = true;
    try {
      await run(async () => {
        const result = await api.repairProject();
        setValidation(result);
        await refreshStructure();
        await refreshTodos();
        await storeRefreshEmbeddedTodos();
        status = result.valid ? "Project repair complete" : "Project repair complete with remaining issues";
      });
    } finally {
      validating = false;
    }
  }

  // Offer to unwrap an entry whose whole body is one code fence (#1628). Fetch
  // the fresh unwrapped body, open the entry, and propose it as a standard
  // revision review — reusing the AI-revision surface, so the user reviews the
  // before/after and Commits or Declines. The write is the commit, never here;
  // declining leaves the fenced body untouched. Close the modal so the review
  // on the entry is visible.
  async function unwrapCodeFencedBody(fenced: CodeFencedBody) {
    await run(async () => {
      const { body } = await api.unwrapLoreCodeFencePreview(fenced.id);
      validateModalOpen = false;
      await editorPanes.openLore(fenced.id);
      entryBrainstorm.propose(fenced.id, { body, fields: {} });
      status = `Review the unwrap of “${fenced.title}”`;
    });
  }

  async function openImportDocs() {
    await run(async () => {
      looseScenes = await api.getLooseScenes();
      importDocsOpen = true;
    });
  }

  async function importLooseScenes(sceneIds: string[]) {
    await run(async () => {
      importBusy = true;
      try {
        await api.importLooseScenes(sceneIds);
        await refreshStructure();
        // Refresh the offer from its own read (#635): imported files drop off the
        // list; a malformed file the backend skipped stays, so it's still shown.
        looseScenes = await api.getLooseScenes();
        const stillLoose = new Set(looseScenes.map((loose) => loose.id));
        const added = sceneIds.filter((id) => !stillLoose.has(id)).length;
        status = added === 1 ? "Added 1 document to the manuscript" : `Added ${added} documents to the manuscript`;
      } finally {
        importBusy = false;
      }
    });
  }

  // AI chat sessions. Per-chat state (history, composer, cost/TTL) lives
  // inside ChatBodyView now; App only tracks the session roster (Chats pane)
  // and which chat is currently open in an editor pane (active-row highlight).
  let chatSessionList = $derived($chatSessionsStore);
  let project = $derived(appState.name === "projectOpen" ? appState.project : null);
  // The declaration editor's rows (#417 slice 4b), fed to the breadcrumb popover
  // that replaced the Project pane's Inheritance section. The whole enumeration,
  // not the declared subset — the popover offers exactly the rows the breadcrumb
  // hides. The toggle side effect stays in the TopBar wiring below.
  let inheritRows = $derived(declarationRows(project?.ancestors));
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
  let activeScene = $derived(focusedEditorPane?.document?.type === "manuscript" ? focusedEditorPane.scene : null);
  // The ≡-menu "Finalize roleplay…" action is enabled only when the focused scene
  // actually holds roleplay beats (ADR-0070 S3), surfaced per-pane from its editor.
  let canFinalizeRoleplay = $derived(!!activeScene && roleplayPresence.has(focusedEditorPane?.id));
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

  // The mutation-set editor dialog is hoisted here (ADR-0055 §3) so it opens
  // from EITHER trigger — the Mutations-pane "+" or a lore card's "New staged
  // change" — through the shared `mutationSetEditorStore`. (It used to mount
  // inside the Mutations pane, which only rendered when that pane was open.)
  // A pinned set adds a set→subject edge, so refresh the reverse index too.
  async function onMutationSetSaved() {
    closeMutationSetEditor();
    await refreshMutationSetEntries().catch(() => {});
    refreshReferenceIndexInBackground();
  }
  let plotTemplates = $derived($plotTemplatesStore);
  let assistantEntries = $derived($assistantEntriesStore);
  // The per-pane selected-view spec is no longer derived here: an explicit-view
  // pane declares `view: { kind }` on its region entry, and the central RegionBody
  // outlet resolves `paneViews.specFor(kind, schema)` and hands it to the body
  // snippet (#258, ADR-0022 / ADR-0032 §D Amdt 1) — one source drives the selector
  // and the list, so App no longer wires the switcher or the spec per pane.
  // Draft/Research tree evaluation now lives inside StructureTree (#112): it
  // derives one ViewResult from `structure` + the pane's viewSpec, replacing the
  // App-side double-eval (color annotations + membership pruning) that stood here.
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
  chain={project?.chain ?? []}
  childProjects={project?.children ?? []}
  onOpenProjectPath={(path) => void projectSession.openProjectAt(path)}
  projectOpen={isProjectOpen}
  themePref={$themePreference}
  onCycleTheme={() => themePreference.update((p) => nextPreference(p))}
  onSelectRecent={(path) => void projectSession.openProjectAt(path)}
  onRemoveRecent={(path) => projectSession.removeRecentProject(path)}
  onOpenFolder={() => projectChooser.openForOpenProject()}
  onNewProject={() => void projectSession.startCreateWizard()}
  onOpenAssistants={openAssistantsPane}
  onOpenSettings={() => void projectSession.openMachineSettings()}
  onOpenDetailTypes={() => schemaPanes?.openDetailTypes()}
  onOpenProjectNode={() => void editorPanes.openProjectNode()}
  onOpenChats={openChatsPane}
  onOpenPrompts={openPromptsPane}
  onOpenPlotTemplates={openPlotTemplatesPane}
  onOpenPlotBoard={openPlotBoardPane}
  onOpenMutations={openMutationsPane}
  onOpenAiSpend={openAiSpendPane}
  onOpenGuides={openGuidePane}
  onOpenImport={openImportDocs}
  onManageAllTags={() => (tagsManagerOpen = true)}
  canFinalize={canFinalizeRoleplay}
  onFinalizeRoleplay={() => activeScene && finalizeDialog?.open(activeScene)}
  {inheritRows}
  inheritSaving={projectSession.declarationSaving}
  onToggleInherit={(path) =>
    void projectSession.setDeclaration(toggledDeclaration(project?.ancestors, path))}
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
      reviewPending={editorReviewPending}
      onClose={(id) => void editorPanes.close(id)}
      body={editorDocBody}
      actions={editorDocActions}
    />
  {:else}
    <div class="welcome" data-testid="no-project">
      <!-- The Project pane is gone (#417 slice 6); this is the only remaining
           no-project state, inlined here rather than routed through a pane that
           could vanish. Once a project opens, the tiled Workspace takes over. -->
      <p class="muted welcome-hint">
        No project open. Pick one from the switcher above — recents, browse, or create new.
      </p>
    </div>
  {/if}

  <!-- SchemaPanes stays mounted for its schema-authoring state; it now registers
       its Types tree + per-type editor regions into the tiled shell rather than
       rendering its own floating panes. -->
  <SchemaPanes
    bind:this={schemaPanes}
    {isProjectOpen}
    {run}
    setStatus={(message) => (status = message)}
    refreshOpenEditorPaneBaselines={(transform) => editorPanes.refreshOpenEditorPaneBaselines(transform)}
  />

  <RegionRegistrar
    regions={{
      outline: { title: "Draft", body: outlineBody, view: { kind: "manuscript", switcher: true } },
      lore: { title: "Lore", body: loreBody, actions: loreActions, view: { kind: "lore", switcher: true } },
      research: { title: "Research", body: researchBody, view: { kind: "research" } },
      prompts: { title: "Prompts", body: promptsBody, actions: promptsActions, view: { kind: "prompt", switcher: true }, closable: true, onClose: closeRegion("prompts") },
      plotTemplates: { title: "Plot templates", body: plotTemplatesBody, actions: plotTemplatesActions, view: { kind: "plot" }, closable: true, onClose: closeRegion("plotTemplates") },
      plotEditor: { title: "Plot board", body: plotEditorBody, closable: true, onClose: closeRegion("plotEditor") },
      mutations: { title: "Reusable mutations", body: mutationsBody, actions: mutationsActions, closable: true, onClose: closeRegion("mutations") },
      assistants: { title: "Assistants", body: assistantsBody, actions: assistantsActions, view: { kind: "assistant", switcher: true }, closable: true, onClose: closeRegion("assistants") },
      chats: { title: "Chats", body: chatsBody, actions: chatsActions, view: { kind: "chat", switcher: true }, closable: true, onClose: closeRegion("chats") },
      todo: { title: "TODO", body: todoBody, actions: todoBarActions },
      search: { title: "Search", body: searchBody },
      guide: { title: "Guides", body: guideBody, closable: true, onClose: closeRegion("guide") },
      aiSpend: { title: "AI spend", body: aiSpendBody, closable: true, onClose: closeRegion("aiSpend") },
    }}
  />

  {#snippet outlineBody(viewSpec: ViewSpec | undefined)}
    <div class="pane-content">
      {#if viewSpec}
      <StructureTree
        config={treeActions.manuscriptTree}
        {structure}
        {viewSpec}
        draftTitles={draftTitleByScene}
        sectionLabel="Scenes"
        emptyLabel="No scenes yet."
        {run}
        onRequestDelete={(node) => treeActions.requestDeleteTreeNode(treeActions.manuscriptTree, node)}
      />
      {/if}
    </div>
  {/snippet}

  {#snippet loreActions()}
      <!-- The add-menu popover is owned by Lore's ViewNodeList (mode-agnostic,
           #112 4c-iv); this header button just drives its imperative handles. -->
      <div class="tree-menu-anchor">
        <button
          class="pin-button"
          type="button"
          title="Add entry"
          aria-label="Add entry"
          class:active={loreRef?.isAddMenuOpen() ?? false}
          onmousedown={(event) => event.stopPropagation()}
          onclick={(event) => loreRef?.toggleAddMenu(event)}
        >+</button>
      </div>
  {/snippet}
  {#snippet loreBody(viewSpec: ViewSpec | undefined)}
    <div class="pane-content">
      <Lore
        bind:this={loreRef}
        entries={loreEntries}
        {viewSpec}
        onOpenEntry={(id) => editorPanes.openLore(id)}
      />
    </div>
  {/snippet}

  {#snippet researchBody(viewSpec: ViewSpec | undefined)}
    <div class="pane-content">
      {#if viewSpec}
      <StructureTree
        config={treeActions.researchTree}
        structure={researchStructure}
        {viewSpec}
        draftTitles={draftTitleByScene}
        sectionLabel="Notes"
        emptyLabel="No topics or notes yet."
        {run}
        onRequestDelete={(node) => treeActions.requestDeleteTreeNode(treeActions.researchTree, node)}
      />
      {/if}
    </div>
  {/snippet}

  {#snippet promptsActions()}
    <!-- The add-menu popover is owned by Prompts' ViewNodeList (mirrors Lore); this
         header button just drives its imperative handles. -->
    <div class="tree-menu-anchor">
      <button
        class="pin-button"
        type="button"
        title="Add prompt"
        aria-label="Add prompt"
        class:active={promptsRef?.isAddMenuOpen() ?? false}
        onmousedown={(event) => event.stopPropagation()}
        onclick={(event) => promptsRef?.toggleAddMenu(event)}
      >+</button>
    </div>
  {/snippet}
  {#snippet promptsBody(viewSpec: ViewSpec | undefined)}
    <div class="pane-content schema-list">
      <Prompts
        bind:this={promptsRef}
        entries={promptEntries}
        {viewSpec}
        onOpenEntry={(id) => editorPanes.openPrompt(id)}
        onNewEntry={(entryType) => treeActions.newPromptEntry(entryType)}
        onCloneEntry={(id) => run(() => editorPanes.forkPrompt(id))}
        onRunEntry={(id) => {
          const entry = promptEntries.find((p) => p.id === id);
          if (entry) run(() => chatSessions.openChatFromPromptEntry(entry, {}, null));
        }}
      />
    </div>
  {/snippet}

  {#snippet plotTemplatesActions()}
    <button class="pin-button" type="button" title="New template" aria-label="New template" onmousedown={(event) => event.stopPropagation()} onclick={() => treeActions.newPlotTemplate()}>+</button>
  {/snippet}
  {#snippet plotTemplatesBody(viewSpec: ViewSpec | undefined)}
    <div class="pane-content schema-list">
      <PlotTemplates
        entries={plotTemplates}
        {viewSpec}
        onOpenEntry={(id) => editorPanes.openPlotTemplate(id)}
        onCloneEntry={(id) => run(() => editorPanes.forkPlotTemplate(id))}
      />
    </div>
  {/snippet}

  {#snippet plotEditorBody()}
    <!-- No .pane-content here: the board is a canvas, not a padded/scrolling list.
         The host fills the tile (`.ws-doc > *:last-child` gets flex:1) so the
         SvelteFlow surface has a definite height to render into. -->
    <div class="plot-board-host">
      <PlotBoardPane />
    </div>
  {/snippet}

  {#snippet mutationsActions()}
    <button class="pin-button" type="button" title="New mutation set" aria-label="New mutation set" onmousedown={(event) => event.stopPropagation()} onclick={() => openNewMutationSet()}>+</button>
  {/snippet}
  {#snippet mutationsBody()}
    <div class="pane-content schema-list">
      <Mutations />
    </div>
  {/snippet}

  {#snippet guideBody()}
    <!-- No .pane-content: GuideView owns its own reading layout (fixed picker +
         scrolling serif prose), filling the tile via `.ws-doc > *:last-child`. -->
    <GuideView />
  {/snippet}

  {#snippet aiSpendBody()}
    <div class="pane-content">
      <AiSpendPane projectKey={projectPath} />
    </div>
  {/snippet}

  {#snippet assistantsActions()}
      <button class="pin-button" type="button" title="Add assistant" aria-label="Add assistant" onmousedown={(event) => event.stopPropagation()} onclick={() => treeActions.newAssistantEntry()}>+</button>
  {/snippet}
  {#snippet assistantsBody(viewSpec: ViewSpec | undefined)}
    <div class="pane-content schema-list">
      <Assistants
        entries={assistantEntries}
        {viewSpec}
        onOpenEntry={(id) => editorPanes.openAssistant(id)}
        onSetOrder={setAssistantOrder}
        onUnlist={unlistAssistant}
      />
    </div>
  {/snippet}

  {#snippet chatsActions()}
    <button class="pin-button" type="button" title="Start a new chat" aria-label="Start a new chat" onmousedown={(event) => event.stopPropagation()} onclick={() => chatSessions.createNewChatSession()}>+</button>
  {/snippet}
  {#snippet chatsBody(viewSpec: ViewSpec | undefined)}
    <div class="pane-content schema-list">
      <Chats
        sessions={chatSessionList}
        {viewSpec}
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
      {#if editorPane.document?.type === "project"}
        <!-- Project-only actions, re-homed from the (vanishing) Project pane to
             the project window (#417). AI Policy is fails-closed (the modal owns
             the explicit Save; this button only opens it); Validate opens the
             result modal and kicks off a fresh check. -->
        <button
          class="pin-button"
          type="button"
          title="Check this project's files for problems"
          aria-label="Validate project"
          onmousedown={(event) => event.stopPropagation()}
          onclick={() => {
            validateModalOpen = true;
            void validateProject();
          }}
        >
          Validate
        </button>
        <button
          class="pin-button"
          type="button"
          title="Set this project's AI access policy"
          aria-label="AI policy"
          onmousedown={(event) => event.stopPropagation()}
          onclick={() => (aiPolicyModalOpen = true)}
        >
          AI Policy
        </button>
      {/if}
      <PromoteAction documentKind={editorPane.document?.type} entry={editorPane.scene} ownLayerId={$projectLayerIdStore} />
      <!-- The project node is its own window; deleting it would remove
           `project.md` (#750). Offer Delete on every other kind, never on the
           project itself — belt to the requestDeleteScene guard's braces. -->
      <button
        class="pin-button danger"
        type="button"
        disabled={!editorPane.scene || editorPane.document?.type === "project"}
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
        <!-- ADR-0049 Library tenants (a prompt, or a plot template — ADR-0048 S4c)
             share the read-only-in-place banner and the clone-to-a-new-id gesture;
             only the noun and the fork method differ. Lore is the odd one out (an
             in-place fork that keeps the id). -->
        {@const paneKind = editorPane.document?.type}
        {@const isPlotTemplate = paneKind === "plot_template"}
        {@const isLibraryTenant = paneKind === "prompt" || isPlotTemplate}
        {@const tenantNoun = isPlotTemplate ? "template" : "prompt"}
        {@const isShipped =
          isLibraryTenant && !!(editorPane.scene as { is_library?: boolean } | undefined)?.is_library}
        <div
          class="ancestor-banner"
          title={isLibraryTenant
            ? isShipped
              ? `This ${tenantNoun} ships with the app and is read-only here. Clone it for an editable copy in this project.`
              : `This ${tenantNoun} is inherited from an ancestor project and is read-only here. Clone it for an editable copy in this project.`
            : "This entry lives in an ancestor project. Edits write back to the original file."}
        >
          <span>{isShipped ? "Shipped with the app" : `from ${editorPane.scene?.source_layer_label ?? "ancestor"}`}</span>
          {#if paneKind === "lore" && editorPane.scene}
            <button
              class="fork-button"
              type="button"
              title="Fork into an editable copy in this project — keeps the id, stops inheriting"
              aria-label="Fork into this project"
              onclick={() => run(() => editorPanes.forkLore(editorPane.scene!.id))}
            >
              <span aria-hidden="true">⧉</span> Fork here
            </button>
          {:else if isLibraryTenant && editorPane.scene}
            <!-- Any inherited Library tenant (Library or an ancestor project, #676)
                 clones to a new local id — the "duplicate the default" gesture,
                 not lore's in-place fork. -->
            <button
              class="fork-button"
              type="button"
              title={`Clone this inherited ${tenantNoun} into an editable copy in this project`}
              aria-label="Clone into this project"
              onclick={() =>
                run(() =>
                  isPlotTemplate
                    ? editorPanes.forkPlotTemplate(editorPane.scene!.id)
                    : editorPanes.forkPrompt(editorPane.scene!.id),
                )}
            >
              <span aria-hidden="true">⧉</span> Clone to edit
            </button>
          {/if}
        </div>
      {/if}
<!-- Key the bind:this off the stable snippet param `id`, NOT `editorPane.id`:
           Svelte re-evaluates a bind:this target on teardown, and `editorPane`
           (= editorPaneById(id)) is already undefined once the pane is closed —
           dereferencing `.id` there threw and aborted the whole effect flush, so
           the layout reconcile never ran and dead editor tabs were left as
           "Editor" ghosts (#806). `id` always equals editorPane.id. -->
      <NodeEditor
        bind:this={editorPanes.editorPaneComponents[id]}
        scene={editorPane.scene}
        documentKind={editorPane.document?.type ?? "manuscript"}
        promptEntries={promptEntries}
        structure={structure}
        researchStructure={researchStructure}
        loreEntries={loreEntries}
        knownTags={editorPane.document?.type === "assistant" || editorPane.document?.type === "prompt"
          ? [...knownTags, ...assistantTagScoped]
          : knownTags}
        tagOrigin={editorPane.document?.type === "assistant" || editorPane.document?.type === "prompt"
          ? "assistant"
          : "project"}
        implicitContextMatcher={implicitContextMatcher}
        assistantEntries={assistantEntries}
        defaultAssistantId={defaultAssistantId}
        availableScenes={flattenStructureScenes(structure?.root)}
        metadataReload={editorPanes.metadataReloadsByPane[editorPane.id] ?? null}
        titleReload={editorPanes.titleReloadsByPane[editorPane.id] ?? null}
        dirty={editorPane.dirty}
        recentlySaved={editorPane.recentlySaved}
        authoringLayerId={editorPane.authoringLayerId}
        hostPaneId={editorPane.id}
        todoStatusHint={editorPane.document?.type === "manuscript" && editorPane.scene && sceneEntryHasBody(editorPane.scene as Scene) ? embeddedHintForScene(editorPane.scene.id) : ""}
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
            detail.offer_on,
            detail.context_strategy,
          )}
        onCustomData={(detail) => schemaPanes?.openForCustomData(detail.entryType, detail.kind, editorPane.id)}
        onNavigate={(detail) => navigateToBacklink(detail.id, detail.kind)}
        onOpenChat={(detail) => chatSessions.openChatFromPromptEntry(detail.entry, detail.inputs, detail.sceneId, { assistantId: detail.assistantId })}
        onViewSaveState={(state) => editorPanes.setViewSaveState(editorPane.id, state)}
        onAuthoringLayerChange={(layerId) => editorPanes.setEditorPaneAuthoringLayer(editorPane.id, layerId)}
        onResetField={(fieldId) => editorPane.scene && run(() => editorPanes.resetLoreOverrideField(editorPane.scene!.id, fieldId))}
        onFlushScene={async () => {
          // A capture photographs the file and a restore overwrites it, so both
          // must run against a file that already holds the author's latest
          // words — autosave is a 6-second idle debounce behind (#401).
          if (editorPane.scene) await editorPanes.flushSceneIfDirty(editorPane.scene.id);
        }}
        onSceneRestored={(restored) => editorPanes.reconcileSceneFromServer(restored)}
        onInteriorityChange={(has) => roleplayPresence.set(editorPane.id, has)}
        onReviewFreeze={(entryId, committer) =>
          committer
            ? void editorPanes.beginReviewLock(entryId, committer)
            : editorPanes.endReviewLock(entryId)}
        onFlushReviewCommit={(entryId) => editorPanes.flushReviewCommit(entryId)}
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
    initialPath={projectChooser.pickerInitialPath}
    title={projectChooser.pickerTitle}
    selectLabel={projectChooser.pickerSelectLabel}
    enforceWithinRoot={true}
    onClose={() => projectChooser.closePicker()}
    onSelect={(path) => projectChooser.useDirectory(path)}
  />

  <ConfirmModal
    state={confirmService.active}
    onCancel={() => confirmService.dismiss()}
    onConfirm={(dontShowAgain) => confirmService.resolve(dontShowAgain)}
    onSecondary={() => confirmService.resolveSecondary()}
  />

  <ConflictDiffModal />

  <CreateProjectWizard />

  <MachineSettingsDialog
    open={projectSession.machineSettingsOpen}
    settings={projectSession.machineSettings}
    bind:draft={projectSession.machineSettingsDraft}
    onCancel={() => projectSession.cancelMachineSettings()}
    onSave={() => void projectSession.saveMachineSettings()}
    onApplyPolicy={(policy) => projectSession.saveAiPolicy(policy)}
    health={{
      onCheck: () => void aiSettings.runHealthCheck(),
      result: aiSettings.healthResult,
      checking: aiSettings.healthChecking,
      disabledReason: !isProjectOpen
        ? "Open a project to test the AI connection."
        : (project?.ai_policy ?? "off") === "off"
          ? "This project's AI access is off, so there is nothing to reach."
          : null,
    }}
  />

  <ImportDocumentsModal
    open={importDocsOpen}
    {looseScenes}
    busy={importBusy}
    onClose={() => (importDocsOpen = false)}
    onImport={importLooseScenes}
  />

  <AIPolicyModal open={aiPolicyModalOpen} onClose={() => (aiPolicyModalOpen = false)} />
  <ValidateModal
    open={validateModalOpen}
    onClose={() => (validateModalOpen = false)}
    {validation}
    checking={validating}
    onRepair={repairProject}
    onUnwrap={unwrapCodeFencedBody}
  />

  <FinalizeRoleplayDialog
    bind:this={finalizeDialog}
    {promptEntries}
    {loreEntries}
    availableScenes={flattenStructureScenes(structure?.root)}
    onFlush={(id) => editorPanes.flushSceneIfDirty(id)}
    onFinalized={(restored) => editorPanes.reconcileSceneFromServer(restored)}
  />
  {#if tagsManagerOpen}
    <TagManagerDialog onClose={() => (tagsManagerOpen = false)} />
  {/if}

  {#if $mutationSetEditorStore}
    <MutationSetEditor
      initial={$mutationSetEditorStore.editing}
      preset={$mutationSetEditorStore.preset ?? null}
      schema={metadataSchema}
      loreEntries={loreEntries}
      promptEntries={promptEntries}
      structure={structure}
      researchStructure={researchStructure}
      knownTags={knownTags}
      onSaved={onMutationSetSaved}
      onCancel={closeMutationSetEditor}
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
  /* Main area below the top bar. The tiled Workspace fills it; before a project
     opens, a centred welcome hint shows instead. */
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
  .welcome-hint {
    width: min(560px, 100%);
    margin: var(--sp-1) 0;
    font-size: var(--fs-md);
  }

  /* The plot board fills its tile (a canvas, not a padded list); PlotEditor's
     own root takes 100% of this flex host. */
  .plot-board-host {
    display: flex;
    min-height: 0;
  }

  /* Ancestor-entry documents: a slim banner above the editor (edits still write
     back to the ancestor file). Replaces the old header tint + badge. */
  .ancestor-banner {
    flex: 0 0 auto;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    padding: var(--sp-1) var(--sp-3);
    background: var(--star-soft);
    border-bottom: 1px solid var(--star-border);
    color: var(--text-2);
    font-size: var(--fs-xs);
  }

  .ancestor-banner .fork-button {
    flex: 0 0 auto;
    padding: 2px var(--sp-2);
    border: 1px solid var(--star-border);
    border-radius: 999px;
    background: transparent;
    color: var(--star);
    font-size: var(--fs-xs);
    cursor: pointer;
  }

  .ancestor-banner .fork-button:hover {
    background: color-mix(in oklab, var(--star) 16%, transparent);
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

