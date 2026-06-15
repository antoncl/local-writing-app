import type {
  DirectoryListing,
  EntryTypeDefinition,
  KnownTags,
  LoreEntry,
  LoreEntryList,
  MetadataFieldDefinition,
  MetadataSchema,
  MetadataSchemaLayers,
  MetadataSchemaOverview,
  ProjectInfo,
  ProjectValidation,
  Scene,
  SearchHit,
  StructureDocument,
  TodoDocument,
} from "./types";

const baseUrl = "http://127.0.0.1:8787/api";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  createProject(rootPath: string, title: string, projectsBaseFolder: string) {
    return request<ProjectInfo>("/project/create", {
      method: "POST",
      body: JSON.stringify({ root_path: rootPath, title, projects_base_folder: projectsBaseFolder }),
    });
  },
  openProject(rootPath: string, projectsBaseFolder: string) {
    return request<ProjectInfo>("/project/open", {
      method: "POST",
      body: JSON.stringify({ root_path: rootPath, projects_base_folder: projectsBaseFolder }),
    });
  },
  updateProjectSettings(projectsBaseFolder: string) {
    return request<ProjectInfo>("/project/settings", {
      method: "PATCH",
      body: JSON.stringify({ projects_base_folder: projectsBaseFolder }),
    });
  },
  getStructure() {
    return request<StructureDocument>("/structure");
  },
  getMetadataSchema() {
    return request<MetadataSchema>("/metadata/schema");
  },
  getMetadataSchemaLayers() {
    return request<MetadataSchemaLayers>("/metadata/schema/layers");
  },
  getMetadataSchemaOverview() {
    return request<MetadataSchemaOverview>("/metadata/schema/overview");
  },
  getKnownTags() {
    return request<KnownTags>("/tags");
  },
  upsertMetadataEntryType(layerId: string, entryTypeId: string, entryType: EntryTypeDefinition, allowExisting = true) {
    return request<MetadataSchema>("/metadata/schema/entry-types", {
      method: "PUT",
      body: JSON.stringify({ layer_id: layerId, entry_type_id: entryTypeId, entry_type: entryType, allow_existing: allowExisting }),
    });
  },
  deleteMetadataEntryType(entryTypeId: string) {
    return request<MetadataSchema>("/metadata/schema/entry-types", {
      method: "DELETE",
      body: JSON.stringify({ entry_type_id: entryTypeId }),
    });
  },
  upsertMetadataField(layerId: string, fieldId: string, field: MetadataFieldDefinition, entryType = "scene", allowExisting = true) {
    return request<MetadataSchema>("/metadata/schema/fields", {
      method: "PUT",
      body: JSON.stringify({ layer_id: layerId, field_id: fieldId, field, entry_type: entryType, allow_existing: allowExisting }),
    });
  },
  moveMetadataField(fieldId: string, targetLayerId: string, entryType = "scene") {
    return request<MetadataSchema>("/metadata/schema/fields/move", {
      method: "POST",
      body: JSON.stringify({ field_id: fieldId, target_layer_id: targetLayerId, entry_type: entryType }),
    });
  },
  renameMetadataField(oldFieldId: string, newFieldId: string, entryType = "scene") {
    return request<MetadataSchema>("/metadata/schema/fields/rename", {
      method: "POST",
      body: JSON.stringify({ old_field_id: oldFieldId, new_field_id: newFieldId, entry_type: entryType }),
    });
  },
  deleteMetadataField(fieldId: string, entryType = "scene") {
    return request<MetadataSchema>("/metadata/schema/fields", {
      method: "DELETE",
      body: JSON.stringify({ field_id: fieldId, entry_type: entryType }),
    });
  },
  listDirectories(path?: string) {
    const query = path ? `?path=${encodeURIComponent(path)}` : "";
    return request<DirectoryListing>(`/directories${query}`);
  },
  validateProject() {
    return request<ProjectValidation>("/project/validate", {
      method: "POST",
    });
  },
  repairProject() {
    return request<ProjectValidation>("/project/repair", {
      method: "POST",
    });
  },
  createScene(title: string, parentId?: string) {
    return request<Scene>("/scenes", {
      method: "POST",
      body: JSON.stringify({ title, parent_id: parentId }),
    });
  },
  getScene(sceneId: string) {
    return request<Scene>(`/scenes/${sceneId}`);
  },
  saveScene(scene: Scene, bodyMarkdown: string) {
    return request<Scene>(`/scenes/${scene.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: scene.title,
        body_markdown: bodyMarkdown,
        base_revision: scene.revision,
        status: scene.status,
        entry_type: scene.entry_type,
        metadata: scene.metadata,
      }),
    });
  },
  deleteScene(sceneId: string) {
    return request<StructureDocument>(`/scenes/${sceneId}`, {
      method: "DELETE",
    });
  },
  listLoreEntries() {
    return request<LoreEntryList>("/lore");
  },
  createLoreEntry(title: string, entryType = "lore_note") {
    return request<LoreEntry>("/lore", {
      method: "POST",
      body: JSON.stringify({ title, entry_type: entryType }),
    });
  },
  getLoreEntry(entryId: string) {
    return request<LoreEntry>(`/lore/${entryId}`);
  },
  saveLoreEntry(entry: LoreEntry, bodyMarkdown: string) {
    return request<LoreEntry>(`/lore/${entry.id}`, {
      method: "PUT",
      body: JSON.stringify({
        title: entry.title,
        body_markdown: bodyMarkdown,
        base_revision: entry.revision,
        entry_type: entry.entry_type,
        metadata: entry.metadata,
      }),
    });
  },
  deleteLoreEntry(entryId: string) {
    return request<LoreEntryList>(`/lore/${entryId}`, {
      method: "DELETE",
    });
  },
  getTodos() {
    return request<TodoDocument>("/todos");
  },
  createTodo(text: string, sceneId?: string | null, anchorId?: string | null) {
    return request<TodoDocument>("/todos", {
      method: "POST",
      body: JSON.stringify({
        text,
        scope: sceneId ? "scene" : "project",
        scene_id: sceneId,
        anchor_id: anchorId,
      }),
    });
  },
  updateTodo(
    todoId: string,
    updates: { status?: "open" | "done"; text?: string; scope?: "project" | "scene"; scene_id?: string | null },
  ) {
    return request<TodoDocument>(`/todos/${todoId}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    });
  },
  deleteTodo(todoId: string) {
    return request<TodoDocument>(`/todos/${todoId}`, {
      method: "DELETE",
    });
  },
  search(query: string, includeOpenTodos = false) {
    return request<{ query: string; hits: SearchHit[] }>("/search", {
      method: "POST",
      body: JSON.stringify({ query, include_open_todos: includeOpenTodos }),
    });
  },
};
