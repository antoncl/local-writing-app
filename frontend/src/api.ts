import type {
  DirectoryListing,
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
  createProject(rootPath: string, title: string) {
    return request<ProjectInfo>("/project/create", {
      method: "POST",
      body: JSON.stringify({ root_path: rootPath, title }),
    });
  },
  openProject(rootPath: string) {
    return request<ProjectInfo>("/project/open", {
      method: "POST",
      body: JSON.stringify({ root_path: rootPath }),
    });
  },
  getStructure() {
    return request<StructureDocument>("/structure");
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
      }),
    });
  },
  deleteScene(sceneId: string) {
    return request<StructureDocument>(`/scenes/${sceneId}`, {
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
