import type { EmbeddedTodoList, Scene, TodoDocument } from "@/lib/types";
import { request } from "./core";

export const todosApi = {
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
  // Embedded (in-prose) todos: a rebuildable index over scenes, plus intentful
  // single-marker mutators that rewrite one marker without a full body save
  // (GH #45). The mutators return the updated scene so an open pane reconciles.
  getEmbeddedTodos() {
    return request<EmbeddedTodoList>("/todos/embedded");
  },
  updateEmbeddedTodo(sceneId: string, todoId: string, updates: { status?: "open" | "done"; note?: string }) {
    return request<Scene>(`/scenes/${sceneId}/todos/${todoId}`, {
      method: "PATCH",
      body: JSON.stringify(updates),
    });
  },
  deleteEmbeddedTodo(sceneId: string, todoId: string) {
    return request<Scene>(`/scenes/${sceneId}/todos/${todoId}`, {
      method: "DELETE",
    });
  },
};
