import type { DirectoryListing, ProjectInfo, Scene, SearchHit, StructureDocument, TodoDocument } from "./types";

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
  createTodo(text: string, sceneId?: string | null) {
    return request<TodoDocument>("/todos", {
      method: "POST",
      body: JSON.stringify({
        text,
        scope: sceneId ? "scene" : "project",
        scene_id: sceneId,
      }),
    });
  },
  updateTodo(todoId: string, status: "open" | "done") {
    return request<TodoDocument>(`/todos/${todoId}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
  },
  search(query: string) {
    return request<{ query: string; hits: SearchHit[] }>("/search", {
      method: "POST",
      body: JSON.stringify({ query }),
    });
  },
};
