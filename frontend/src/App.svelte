<script lang="ts">
  import { onMount } from "svelte";
  import { api } from "./api";
  import DocumentEditorPane from "./DocumentEditorPane.svelte";
  import type {
    Backlink,
    DirectoryListing,
    EditableDocument,
    EntryMetadata,
    EntryTypeDefinition,
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataFieldType,
    MetadataSchema,
    MetadataSchemaLayer,
    MetadataSchemaOverview,
    ProjectInfo,
    ProjectValidation,
    SearchHit,
    StructureDocument,
    StructureNode,
    TodoItem,
  } from "./types";

  type AppState =
    | { name: "needsProject" }
    | { name: "projectOpen"; project: ProjectInfo };
  type DocumentRef = { type: "scene" | "lore"; id: string };
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
  let projectsBaseFolder = "";
  let directoryPickerOpen = false;
  let directoryListing: DirectoryListing | null = null;
  let directoryPickerLoading = false;
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
  let todos: TodoItem[] = [];
  let validation: ProjectValidation | null = null;
  let metadataSchema: MetadataSchema | null = null;
  let metadataSchemaOverview: MetadataSchemaOverview | null = null;
  let metadataSchemaLayers: MetadataSchemaLayer[] = [];
  let schemaFieldKind: "scene" | "lore" = "scene";
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
  let schemaTypeKind: "scene" | "lore" = "lore";
  let schemaTypeParent = "";
  let schemaTypeAbstract = false;
  let schemaTypeReadonly = false;
  let selectedSchemaTypeId: string | null = null;
  let draggedSchemaTypeId: string | null = null;
  let schemaSelectedEntryType: EntryTypeDefinition | null = null;
  let schemaNodeTypeOptions: NodeTypeOption[] = [];
  let schemaNodeTypeTree: NodeTypeTreeNode[] = [];
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
    schema: { title: "Custom Data", x: 330, y: 260, width: 360, height: 420, z: 3 },
    schema_field: { title: "Custom Field", x: 708, y: 260, width: 360, height: 420, z: 4 },
    schema_type: { title: "Node Type", x: 708, y: 260, width: 360, height: 390, z: 4 },
    todo: { title: "TODO", x: 1126, y: 18, width: 310, height: 320, z: 4 },
    search: { title: "Search", x: 1126, y: 360, width: 310, height: 320, z: 5 },
  };
  let editorPanes: EditorPaneState[] = [];
  let nextMetadataReloadToken = 1;
  let metadataReloadsByPane: Record<string, MetadataReloadSignal> = {};
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
  $: groupedLoreEntries = groupLoreEntriesByType(filteredLoreEntries, metadataSchema);
  $: schemaSelectedEntryType = metadataSchema?.entry_types[schemaFieldEntryType] ?? metadataSchema?.entry_types.scene ?? null;
  $: schemaFieldKind = schemaSelectedEntryType?.kind === "lore" ? "lore" : "scene";
  $: schemaNodeTypeOptions = buildNodeTypeOptions(metadataSchema);
  $: schemaNodeTypeTree = buildNodeTypeTree(metadataSchema, schemaFieldKind);

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
      draftStatus: "draft",
      draftEntryType: "scene",
      draftMetadata: {},
      saving: false,
    };
  }

  function paneStyle(id: PaneId) {
    const pane = panes[id];
    return `left: ${pane.x}px; top: ${pane.y}px; width: ${pane.width}px; height: ${pane.height}px; z-index: ${pane.z};`;
  }

  function isPaneVisible(id: PaneId) {
    if (id === "project") return true;
    if (!isProjectOpen) return false;
    if (id === "schema") return schemaPaneOpen;
    if (id === "schema_field") return schemaFieldPaneOpen;
    if (id === "schema_type") return schemaTypePaneOpen;
    return !isEditorPaneId(id) || editorPanes.some((pane) => pane.id === id);
  }

  function isEditorPaneId(id: PaneId) {
    return id.startsWith("editor_");
  }

  function openProjectWorkspace(nextProject: ProjectInfo) {
    resetEditorWorkspace();
    projectPath = nextProject.root_path;
    projectTitle = nextProject.title;
    projectsBaseFolder = nextProject.projects_base_folder ?? "";
    appState = { name: "projectOpen", project: nextProject };
    fitPanesToViewport();
    focusPane("outline");
  }

  function resetEditorWorkspace() {
    editorPanes = [];
    knownTags = [];
    focusedEditorPaneId = null;
    nextEditorPaneIndex = 1;
    nextMetadataReloadToken = 1;
    metadataReloadsByPane = {};
    panes = {
      project: panes.project,
      outline: panes.outline,
      lore: panes.lore,
      schema: panes.schema,
      schema_field: panes.schema_field,
      schema_type: panes.schema_type,
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

  async function refreshLoreEntries() {
    loreEntries = (await api.listLoreEntries()).entries;
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
    projectPath = path;
    directoryPickerOpen = false;
  }

  async function createProject() {
    await run(async () => {
      const openedProject = await api.createProject(projectPath, projectTitle, projectsBaseFolder);
      openProjectWorkspace(openedProject);
      await refreshStructure();
      await refreshLoreEntries();
      await refreshMetadataSchema();
      await refreshKnownTags();
      await refreshTodos();
      const initialSceneId = findFirstSceneId(structure?.root);
      if (initialSceneId) {
        await openSceneInEditorPane(initialSceneId);
      }
      status = `Created ${openedProject.title}`;
    });
  }

  async function openProject() {
    await run(async () => {
      const openedProject = await api.openProject(projectPath, projectsBaseFolder);
      openProjectWorkspace(openedProject);
      await refreshStructure();
      await refreshLoreEntries();
      await refreshMetadataSchema();
      await refreshKnownTags();
      await refreshTodos();
      status = `Opened ${openedProject.title}`;
    });
  }

  async function updateProjectSettings() {
    if (!isProjectOpen) return;
    await run(async () => {
      const updatedProject = await api.updateProjectSettings(projectsBaseFolder);
      appState = { name: "projectOpen", project: updatedProject };
      projectsBaseFolder = updatedProject.projects_base_folder ?? "";
      await refreshMetadataSchema();
      validation = await api.validateProject();
      status = "Updated project settings";
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

  function buildNodeTypeTree(schema: MetadataSchema | null, kind: "scene" | "lore"): NodeTypeTreeNode[] {
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
    const rootIds = kind === "lore" && entryTypes.lore_entry ? ["lore_entry"] : roots.sort(compareByName);
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
    schemaTypeKind = parentType?.kind === "scene" ? "scene" : parentType?.kind === "lore" ? "lore" : schemaFieldKind;
    schemaTypeParent = parentTypeId || (schemaSelectedEntryType?.abstract || schemaFieldEntryType !== "scene" ? schemaFieldEntryType : defaultSchemaParentType(schemaFieldKind));
    schemaTypeAbstract = false;
    schemaTypeReadonly = false;
    schemaTypeLayerId = layerId;
    schemaTypePaneOpen = true;
    focusPane("schema_type");
  }

  function openSchemaTypeDetail(typeId: string) {
    const entryType = metadataSchema?.entry_types[typeId];
    if (!entryType) return;
    const source = schemaTypeSource(typeId);
    selectedSchemaTypeId = typeId;
    schemaTypeId = typeId;
    schemaTypeName = entryType.name;
    schemaTypeKind = entryType.kind === "scene" ? "scene" : "lore";
    schemaTypeParent = entryType.parent ?? "";
    schemaTypeAbstract = Boolean(entryType.abstract);
    schemaTypeReadonly = Boolean(source?.built_in);
    schemaTypeLayerId = source?.built_in ? projectSchemaLayerId() : (source?.layer_id ?? projectSchemaLayerId());
    schemaTypePaneOpen = true;
    focusPane("schema_type");
  }

  function updateSchemaTypeName(value: string) {
    schemaTypeName = value;
    if (!schemaTypeReadonly) {
      schemaTypeId = slugifyFieldId(value);
    }
  }

  function defaultSchemaParentType(kind: "scene" | "lore") {
    if (kind === "lore" && metadataSchema?.entry_types.lore_entry) return "lore_entry";
    return "";
  }

  function openSchemaForCustomData(entryType: string, kind: "scene" | "lore") {
    schemaPaneOpen = true;
    schemaFieldEntryType = entryType || defaultSchemaEntryType(kind);
    focusPane("schema");
  }

  function defaultSchemaEntryType(kind: "scene" | "lore") {
    return Object.entries(metadataSchema?.entry_types ?? {}).find(([, definition]) => definition.kind === kind)?.[0] ?? (kind === "lore" ? "lore_note" : "scene");
  }

  function entryTypeIdsForField(fieldId: string, kind: "scene" | "lore") {
    return Object.entries(metadataSchema?.entry_types ?? {})
      .filter(([, definition]) => definition.kind === kind && definition.fields.includes(fieldId))
      .map(([typeId]) => typeId);
  }

  function closeSchemaPane(id: "schema" | "schema_field" | "schema_type") {
    if (id === "schema") schemaPaneOpen = false;
    else if (id === "schema_field") schemaFieldPaneOpen = false;
    else schemaTypePaneOpen = false;
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
      status = "System node types cannot be moved";
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
      status = "Updated metadata schema";
    });
  }

  async function saveSchemaType() {
    if (!schemaTypeLayerId) return;
    await run(async () => {
      const previousTypeId = selectedSchemaTypeId && !schemaTypeReadonly ? selectedSchemaTypeId : null;
      const nextTypeId = schemaTypeId.trim();
      const nextType: EntryTypeDefinition = {
        name: schemaTypeName.trim() || nextTypeId,
        kind: schemaTypeKind,
        parent: schemaTypeParent || null,
        abstract: schemaTypeAbstract,
        fields: previousTypeId ? (metadataSchema?.entry_types[previousTypeId]?.own_fields ?? metadataSchema?.entry_types[previousTypeId]?.fields ?? []) : [],
      };
      if (previousTypeId && previousTypeId !== nextTypeId) {
        status = "Renaming node types is not available yet";
        return;
      }
      metadataSchema = await api.upsertMetadataEntryType(schemaTypeLayerId, nextTypeId, nextType, Boolean(previousTypeId));
      await refreshMetadataSchema();
      validation = await api.validateProject();
      selectedSchemaTypeId = nextTypeId;
      schemaFieldEntryType = nextTypeId;
      status = "Updated node type";
    });
  }

  function requestDeleteSchemaType() {
    if (!selectedSchemaTypeId || schemaTypeReadonly) return;
    const typeName = schemaTypeName || selectedSchemaTypeId;
    confirmation = {
      title: "Delete Node Type",
      message: `Delete "${typeName}"? Existing documents using this type must be changed first.`,
      confirmLabel: "Delete Type",
      destructive: true,
      onConfirm: () => deleteSchemaType(selectedSchemaTypeId!),
    };
  }

  async function deleteSchemaType(typeId: string) {
    metadataSchema = await api.deleteMetadataEntryType(typeId);
    await refreshMetadataSchema();
    validation = await api.validateProject();
    selectedSchemaTypeId = null;
    schemaTypePaneOpen = false;
    status = `Deleted ${typeId}`;
  }

  function requestDeleteSchemaField() {
    if (!selectedSchemaFieldId || selectedSchemaFieldId.startsWith("system:") || schemaFieldReadonly) return;
    const fieldName = schemaFieldName || selectedSchemaFieldId;
    confirmation = {
      title: "Delete Custom Field",
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

  async function newLoreEntry() {
    await run(async () => {
      const entry = await api.createLoreEntry("New Entry", "lore_note");
      await refreshLoreEntries();
      await openLoreEntryInEditorPane(entry.id);
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

  function updateEditorPaneDraft(id: string, title: string, bodyMarkdown: string, status: string, entryType: string, metadata: EntryMetadata) {
    editorPanes = editorPanes.map((pane) =>
      pane.id === id
        ? {
            ...pane,
            dirty:
              isEditorPaneDirty(pane.scene, title, bodyMarkdown, status, entryType, metadata),
            draftTitle: title,
            draftMarkdown: bodyMarkdown,
            draftStatus: status,
            draftEntryType: entryType,
            draftMetadata: cloneMetadata(metadata),
          }
        : pane,
    );
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
  ) {
    return (
      Boolean(scene) &&
      (title !== scene?.title ||
        bodyMarkdown !== scene?.body_markdown ||
        (documentStatus(scene) ? status !== documentStatus(scene) : false) ||
        entryType !== scene?.entry_type ||
        !metadataEqual(metadata, scene?.metadata ?? {}))
    );
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
      documentRefs.map((document) => (document.type === "lore" ? api.getLoreEntry(document.id) : api.getScene(document.id))),
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

      const remainingEditorPanes = editorPanes.filter((candidate) => candidate.id !== id);
      editorPanes = remainingEditorPanes;
      const { [id]: _closedTodos, ...remainingEmbeddedTodos } = embeddedTodosByPane;
      embeddedTodosByPane = remainingEmbeddedTodos;
      const { [id]: _closedReload, ...remainingReloads } = metadataReloadsByPane;
      metadataReloadsByPane = remainingReloads;
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
    const documentKind = pane.document?.type ?? "scene";
    setEditorPaneSaving(id, true);
    try {
      const draftDocument = {
        ...pane.scene,
        title: pane.draftTitle,
        ...(documentKind === "scene" ? { status: pane.draftStatus } : {}),
        entry_type: pane.draftEntryType,
        metadata: cloneMetadata(pane.draftMetadata),
      };
      const savedDocument =
        documentKind === "lore"
          ? await api.saveLoreEntry(draftDocument, pane.draftMarkdown)
          : await api.saveScene(draftDocument, pane.draftMarkdown);
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
    const baseMessage = `Delete "${sceneTitle}"? This removes the ${documentKind === "lore" ? "entry" : "scene"} file from the project.`;
    const message =
      backlinks.length > 0
        ? `${baseMessage}\n\n${backlinks.length} ${backlinks.length === 1 ? "entry references" : "entries reference"} this — those links will become broken:`
        : baseMessage;
    const details = backlinks.map((link) => `${link.title} — ${link.field_name}`);
    confirmation = {
      title: documentKind === "lore" ? "Delete Entry" : "Delete Scene",
      message,
      details,
      confirmLabel: documentKind === "lore" ? "Delete Entry" : "Delete Scene",
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
    } else {
      structure = await api.deleteScene(pane.scene.id);
      await refreshTodos();
    }
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

<main class="workspace">
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isPaneVisible("project")} class="pane project-pane" data-pane-id="project" style={paneStyle("project")} aria-label="Project pane" on:mousedown={() => focusPane("project")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Project pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "project")} on:mousedown={(event) => startPaneDrag(event, "project")}>
      <h2>Project</h2>
    </header>
    <div class="pane-content project-panel">
      <h1>Local Writer</h1>
      <label>
        Projects base folder
        <input bind:value={projectsBaseFolder} placeholder="C:\path\to\writing-base" />
      </label>
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
        <button type="button" disabled={!projectsBaseFolder.trim() || !projectPath.trim()} on:click={createProject}>Create</button>
        <button type="button" disabled={!projectsBaseFolder.trim() || !projectPath.trim()} on:click={openProject}>Open</button>
        <button type="button" disabled={!isProjectOpen} on:click={validateProject}>Validate</button>
      </div>
      {#if isProjectOpen}
        <div class="button-row">
          <button type="button" on:click={updateProjectSettings}>Apply Base Folder</button>
        </div>
      {/if}
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
  <section class:hidden-pane={!isProjectOpen || !schemaPaneOpen} class="pane schema-pane" data-pane-id="schema" style={paneStyle("schema")} aria-label="Custom Data pane" on:mousedown={() => focusPane("schema")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Custom Data pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "schema")} on:mousedown={(event) => startPaneDrag(event, "schema")}>
      <h2>Custom Data</h2>
      <div class="pane-header-actions">
        <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => createSchemaTypeDraft()}>+ Type</button>
        <button class="pin-button" type="button" on:mousedown={(event) => event.stopPropagation()} on:click={() => closeSchemaPane("schema")}>Close</button>
      </div>
    </header>
    <div class="pane-content schema-list">
      <div class="schema-context-heading">
        <strong>{schemaFieldKind === "lore" ? "Lore Entry Types" : "Scene Types"}</strong>
        <small>Drag a custom type onto another type to change its parent.</small>
      </div>
      <div class="schema-node-tree" aria-label={schemaFieldKind === "lore" ? "Lore entry type tree" : "Scene type tree"}>
        {#each schemaNodeTypeTree as node}
          {@render renderNodeTypeCard(node)}
        {/each}
        {#if schemaNodeTypeTree.length === 0}
          <p class="muted">No node types defined for this context.</p>
        {/if}
      </div>
    </div>
    <button class="pane-resize" type="button" aria-label="Resize Custom Data pane" on:keydown={(event) => handlePaneResizeKeydown(event, "schema")} on:mousedown={(event) => startPaneResize(event, "schema")}></button>
  </section>

  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isProjectOpen || !schemaTypePaneOpen} class="pane schema-type-pane" data-pane-id="schema_type" style={paneStyle("schema_type")} aria-label="Node Type pane" on:mousedown={() => focusPane("schema_type")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Node Type pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "schema_type")} on:mousedown={(event) => startPaneDrag(event, "schema_type")}>
      <h2>Node Type</h2>
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
      <label class="inline-check">
        <input type="checkbox" disabled={schemaTypeReadonly} bind:checked={schemaTypeAbstract} />
        Abstract base type
      </label>
      {#if selectedSchemaTypeId}
        <div class="schema-target-layer">
          <strong>Effective fields</strong>
          <span>{metadataSchema?.entry_types[selectedSchemaTypeId]?.fields.length ?? 0}</span>
        </div>
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
    <button class="pane-resize" type="button" aria-label="Resize Node Type pane" on:keydown={(event) => handlePaneResizeKeydown(event, "schema_type")} on:mousedown={(event) => startPaneResize(event, "schema_type")}></button>
  </section>

  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class:hidden-pane={!isProjectOpen || !schemaFieldPaneOpen} class="pane schema-field-pane" data-pane-id="schema_field" style={paneStyle("schema_field")} aria-label="Custom Field pane" on:mousedown={() => focusPane("schema_field")}>
    <header class="pane-header" role="button" tabindex="0" aria-label="Move Custom Field pane" on:keydown={(event) => handlePaneHeaderKeydown(event, "schema_field")} on:mousedown={(event) => startPaneDrag(event, "schema_field")}>
      <h2>Custom Field</h2>
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
    <button class="pane-resize" type="button" aria-label="Resize Custom Field pane" on:keydown={(event) => handlePaneResizeKeydown(event, "schema_field")} on:mousedown={(event) => startPaneResize(event, "schema_field")}></button>
  </section>

  {#each editorPanes as editorPane (editorPane.id)}
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <section
      class:hidden-pane={!isPaneVisible(editorPane.id)}
      class="pane editor-pane"
      data-pane-id={editorPane.id}
      style={paneStyle(editorPane.id)}
      aria-label="Editor pane"
      on:mousedown={() => focusPane(editorPane.id)}
    >
      <header class="pane-header" role="button" tabindex="0" aria-label="Move Editor pane" on:keydown={(event) => handlePaneHeaderKeydown(event, editorPane.id)} on:mousedown={(event) => startPaneDrag(event, editorPane.id)}>
        <h2>{editorPane.scene?.title ?? "Editor"}</h2>
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
        knownTags={knownTags}
        metadataReload={metadataReloadsByPane[editorPane.id] ?? null}
        dirty={editorPane.dirty}
        todoStatusHint={editorPane.document?.type === "scene" ? (embeddedTodoStatusHintsByPane[editorPane.id] ?? "No embedded TODOs. Select text to mark a TODO.") : ""}
        on:focus={() => focusPane(editorPane.id)}
        on:change={(event) =>
          updateEditorPaneDraft(
            editorPane.id,
            event.detail.title,
            event.detail.bodyMarkdown,
            event.detail.status,
            event.detail.entryType,
            event.detail.metadata,
          )}
        on:custom-data={(event) => openSchemaForCustomData(event.detail.entryType, event.detail.kind)}
        on:embeddedTodos={(event) => updateEmbeddedTodosForPane(editorPane.id, event.detail.todos)}
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

{#snippet renderNodeTypeCard(node: NodeTypeTreeNode)}
  {@const typeSource = schemaTypeSource(node.id)}
  {@const fieldEntries = fieldEntriesForEntryType(node.id)}
  {@const fieldsCollapsed = collapsedSchemaFieldsByType[node.id] ?? true}
  <section
    class:active={selectedSchemaTypeId === node.id}
    class="schema-node-card"
    draggable={!typeSource?.built_in}
    role="group"
    aria-label={`${node.label} node type`}
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
          <small>{node.id} · {node.definition.abstract ? "Abstract " : ""}Node Type</small>
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
