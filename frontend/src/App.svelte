<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "./api";
  import DocumentEditorPane from "./DocumentEditorPane.svelte";
  import type {
    DirectoryListing,
    ProjectInfo,
    ProjectValidation,
    Scene,
    SearchHit,
    StructureDocument,
    StructureNode,
    TodoItem,
  } from "./types";

  type AppState =
    | { name: "needsProject" }
    | { name: "projectOpen"; project: ProjectInfo };
  type DocumentRef = { type: "scene"; id: string };
  type PaneId = "project" | "outline" | "todo" | "search" | string;
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
    scene: Scene | null;
    pinned: boolean;
    dirty: boolean;
    draftTitle: string;
    draftMarkdown: string;
    saving: boolean;
  };
  type ConfirmationState = {
    title: string;
    message: string;
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
  let appState: AppState = { name: "needsProject" };
  $: project = appState.name === "projectOpen" ? appState.project : null;
  $: isProjectOpen = appState.name === "projectOpen";
  let structure: StructureDocument | null = null;
  let focusedEditorPaneId: string | null = null;
  $: focusedEditorPane = editorPanes.find((pane) => pane.id === focusedEditorPaneId) ?? editorPanes[0] ?? null;
  $: activeScene = focusedEditorPane?.scene ?? null;
  let activeParentId: string | undefined = undefined;
  let todos: TodoItem[] = [];
  let validation: ProjectValidation | null = null;
  let newTodo = "";
  let searchQuery = "";
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
    todo: { title: "TODO", x: 1126, y: 18, width: 310, height: 320, z: 4 },
    search: { title: "Search", x: 1126, y: 360, width: 310, height: 320, z: 5 },
  };
  let editorPanes: EditorPaneState[] = [];
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

  onMount(() => {
    fitPanesToViewport();
    return () => {
      document.removeEventListener("mousemove", movePane);
      document.removeEventListener("mouseup", stopPaneDrag);
      document.removeEventListener("mousemove", resizePane);
      document.removeEventListener("mouseup", stopPaneResize);
    };
  });

  function createEmptyEditorPane(id: string): EditorPaneState {
    return {
      id,
      document: null,
      scene: null,
      pinned: false,
      dirty: false,
      draftTitle: "",
      draftMarkdown: "",
      saving: false,
    };
  }

  function paneStyle(id: PaneId) {
    const pane = panes[id];
    return `left: ${pane.x}px; top: ${pane.y}px; width: ${pane.width}px; height: ${pane.height}px; z-index: ${pane.z};`;
  }

  function isPaneVisible(id: PaneId) {
    return id === "project" || (isProjectOpen && (!isEditorPaneId(id) || editorPanes.some((pane) => pane.id === id)));
  }

  function isEditorPaneId(id: PaneId) {
    return id.startsWith("editor_");
  }

  function openProjectWorkspace(nextProject: ProjectInfo) {
    resetEditorWorkspace();
    appState = { name: "projectOpen", project: nextProject };
    fitPanesToViewport();
    focusPane("outline");
  }

  function resetEditorWorkspace() {
    editorPanes = [];
    focusedEditorPaneId = null;
    nextEditorPaneIndex = 1;
    panes = {
      project: panes.project,
      outline: panes.outline,
      todo: panes.todo,
      search: panes.search,
    };
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

  async function refreshTodos() {
    todos = (await api.getTodos()).items.filter((item) => !item.anchor_id);
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
    projectPath = path;
    directoryPickerOpen = false;
  }

  async function createProject() {
    await run(async () => {
      const openedProject = await api.createProject(projectPath, projectTitle);
      await refreshStructure();
      await refreshTodos();
      openProjectWorkspace(openedProject);
      const initialSceneId = findFirstSceneId(structure?.root);
      if (initialSceneId) {
        await openSceneInEditorPane(initialSceneId);
      }
      status = `Created ${openedProject.title}`;
    });
  }

  async function openProject() {
    await run(async () => {
      const openedProject = await api.openProject(projectPath);
      projectTitle = openedProject.title;
      await refreshStructure();
      await refreshTodos();
      openProjectWorkspace(openedProject);
      status = `Opened ${openedProject.title}`;
    });
  }

  function findFirstSceneId(node: StructureNode | null | undefined): string | null {
    if (!node) return null;
    if (node.type === "scene" && node.scene_id) return node.scene_id;
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
            saving: false,
          }
        : pane,
    );
    focusedEditorPaneId = targetPane.id;
    focusPane(targetPane.id);
    status = `Loaded ${scene.title}`;
  }

  function addEditorPane() {
    const id = `editor_${nextEditorPaneIndex}`;
    nextEditorPaneIndex += 1;
    const offset = Math.min(160, editorPanes.length * 28);
    panes = {
      ...panes,
      [id]: {
        title: "Scene Editor",
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

  function updateEditorPaneDraft(id: string, title: string, bodyMarkdown: string) {
    editorPanes = editorPanes.map((pane) =>
      pane.id === id
        ? {
            ...pane,
            dirty: Boolean(pane.scene) && (title !== pane.scene.title || bodyMarkdown !== pane.scene.body_markdown),
            draftTitle: title,
            draftMarkdown: bodyMarkdown,
          }
        : pane,
    );
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

      const remainingEditorPanes = editorPanes.filter((candidate) => candidate.id !== id);
      editorPanes = remainingEditorPanes;
      const { [id]: _closedTodos, ...remainingEmbeddedTodos } = embeddedTodosByPane;
      embeddedTodosByPane = remainingEmbeddedTodos;
      const { [id]: _closedPane, ...remainingPanes } = panes;
      panes = remainingPanes;
      if (focusedEditorPaneId === id) {
        focusedEditorPaneId = remainingEditorPanes[0]?.id ?? null;
      }
    });
  }

  async function saveEditorPane(id: string) {
    const pane = editorPanes.find((candidate) => candidate.id === id);
    if (!pane?.scene) return;
    setEditorPaneSaving(id, true);
    try {
      const savedScene = await api.saveScene({ ...pane.scene, title: pane.draftTitle }, pane.draftMarkdown);
      editorPanes = editorPanes.map((candidate) =>
        candidate.id === id
          ? {
              ...candidate,
              document: { type: "scene", id: savedScene.id },
              scene: savedScene,
              dirty: false,
              draftTitle: savedScene.title,
              draftMarkdown: savedScene.body_markdown,
              saving: false,
            }
          : candidate,
      );
      await refreshStructure();
      await refreshTodos();
      status = `Saved ${savedScene.title}`;
    } catch (caught) {
      setEditorPaneSaving(id, false);
      throw caught;
    }
  }

  function setEditorPaneSaving(id: string, saving: boolean) {
    editorPanes = editorPanes.map((pane) => (pane.id === id ? { ...pane, saving } : pane));
  }

  function requestDeleteEditorPaneScene(id: string) {
    const pane = editorPanes.find((candidate) => candidate.id === id);
    if (!pane?.scene) return;
    const sceneTitle = pane.scene.title;
    confirmation = {
      title: "Delete Scene",
      message: `Delete "${sceneTitle}"? This removes the scene file from the project.`,
      confirmLabel: "Delete Scene",
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
    const sceneTitle = pane.scene.title;
    structure = await api.deleteScene(pane.scene.id);
    await refreshTodos();
    editorPanes = editorPanes.map((candidate) => (candidate.id === id ? createEmptyEditorPane(id) : candidate));
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
      await openSceneInEditorPane(hit.file_id);
      if (hit.todo_id) {
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
    if (!pane?.scene) {
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

<main class="workspace">
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isPaneVisible("project")} class="pane project-pane" data-pane-id="project" style={paneStyle("project")} aria-label="Project pane" on:mousedown={() => focusPane("project")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Project pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "project")} on:mousedown={(event) => startPaneDrag(event, "project")}>
      <h2>Project</h2>
    </header>
    <div class="pane-content project-panel">
      <h1>Local Writer</h1>
      <label>
        Project folder
        <div class="path-picker-row">
          <input bind:value={projectPath} placeholder="C:\path\to\my-novel" />
          <button type="button" on:click={openDirectoryPicker}>Browse</button>
        </div>
      </label>
      <label>
        Title
        <input bind:value={projectTitle} />
      </label>
      <div class="button-row">
        <button type="button" on:click={createProject}>Create</button>
        <button type="button" on:click={openProject}>Open</button>
        <button type="button" disabled={!isProjectOpen} on:click={validateProject}>Validate</button>
      </div>
      {#if validation}
        <section class:invalid={!validation.valid} class="validation-panel" aria-label="Project validation result">
          <h3>{validation.valid ? "Project Looks Consistent" : "Project Issues Found"}</h3>
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
        <button on:click={() => newScene(activeParentId)}>+</button>
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

  {#each editorPanes as editorPane (editorPane.id)}
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <section
      class:hidden-pane={!isPaneVisible(editorPane.id)}
      class="pane editor-pane"
      data-pane-id={editorPane.id}
      style={paneStyle(editorPane.id)}
      aria-label="Scene Editor pane"
      on:mousedown={() => focusPane(editorPane.id)}
    >
      <header class="pane-header" role="button" tabindex="0" aria-label="Move Scene Editor pane" on:keydown={(event) => handlePaneHeaderKeydown(event, editorPane.id)} on:mousedown={(event) => startPaneDrag(event, editorPane.id)}>
        <h2>{editorPane.scene?.title ?? "Scene Editor"}</h2>
        <div class="pane-header-actions">
          {#if editorPane.dirty}
            <span class="pane-status">Unsaved</span>
          {/if}
          <button
            class="pin-button"
            type="button"
            disabled={editorPane.saving || !editorPane.dirty}
            title={editorPane.saving ? "Saving this scene" : "Save this scene"}
            on:mousedown={(event) => event.stopPropagation()}
            on:click={() => run(() => saveEditorPane(editorPane.id))}
          >
            {editorPane.saving ? "Saving" : "Save"}
          </button>
          <button
            class="pin-button danger"
            type="button"
            disabled={!editorPane.scene}
            title="Delete this scene"
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
        dirty={editorPane.dirty}
        todoStatusHint={embeddedTodoStatusHintsByPane[editorPane.id] ?? "No embedded TODOs. Select text to mark a TODO."}
        on:focus={() => focusPane(editorPane.id)}
        on:change={(event) => updateEditorPaneDraft(editorPane.id, event.detail.title, event.detail.bodyMarkdown)}
        on:embeddedTodos={(event) => updateEmbeddedTodosForPane(editorPane.id, event.detail.todos)}
      />
      <button class="pane-resize" type="button" aria-label="Resize Scene Editor pane" on:keydown={(event) => handlePaneResizeKeydown(event, editorPane.id)} on:mousedown={(event) => startPaneResize(event, editorPane.id)}></button>
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

  {#if error}
    <section class="error-toast">{error}</section>
  {/if}
</main>

{#snippet renderTree(node: StructureNode, depth: number)}
  <div class="tree-row" style={`padding-left: ${depth * 14}px`}>
    {#if node.type === "scene" && node.scene_id}
      <button class="tree-scene" on:click={() => run(() => openSceneInEditorPane(node.scene_id!))}>{node.title}</button>
    {:else}
      <button class="tree-group" on:click={() => (activeParentId = node.id)}>{node.title}</button>
    {/if}
  </div>
  {#each nodeChildren(node) as child}
    {@render renderTree(child, depth + 1)}
  {/each}
{/snippet}
