// Todo + search actions — the TODO/Search opener glue lifted out of App.svelte
// (#14 P0). A singleton rune controller (mirrors editorPanes / projectSession /
// aiSettings): the file-todo CRUD, the embedded-todo mutators, and the navigation
// openers that route a search hit / todo into an editor pane.
//
// Embedded (in-prose) todos are a rebuildable index over scenes (GH #45), NOT
// state owned by a live editor pane. So their mutations go through intentful
// backend endpoints (api.updateEmbeddedTodo / deleteEmbeddedTodo) and then
// reconcile any open pane via the editorPanes controller — they no longer reach
// into the mounted editor component. The reactive lists themselves live in the
// todos store (todosStore / embeddedTodosStore); this controller owns the
// actions + the `newTodo` compose field.

import { get } from "svelte/store";
import { api } from "@/lib/api";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import {
  embeddedTodosStore,
  refreshEmbeddedTodos,
  setTodos,
  todosStore,
} from "@/lib/stores/todos";
import type { EmbeddedTodoRecord, Scene, SearchHit, TodoItem } from "@/lib/types";

class TodoActions {
  // The Todo pane's "Add" compose field (two-way bound).
  newTodo = $state("");

  // ---- Injected host hooks (set in App.onMount) ----
  run: (action: () => Promise<void>) => Promise<boolean> = async (action) => {
    await action();
    return true;
  };
  setStatus: (message: string) => void = () => {};
  // The scene focused in an editor pane, so a new todo scopes to it (or stays
  // project-level when nothing is open).
  getActiveSceneId: () => string | undefined = () => undefined;

  // ---- File todos (todo.yaml) ----
  async addTodo(): Promise<void> {
    if (!this.newTodo.trim()) return;
    await this.run(async () => {
      setTodos((await api.createTodo(this.newTodo.trim(), this.getActiveSceneId())).items);
      this.newTodo = "";
    });
  }

  async toggleTodo(item: TodoItem): Promise<void> {
    await this.run(async () => {
      setTodos((await api.updateTodo(item.id, { status: item.status === "open" ? "done" : "open" })).items);
    });
  }

  async updateTodoText(item: TodoItem, text: string): Promise<void> {
    const trimmed = text.trim();
    if (!trimmed || trimmed === item.text) return;
    await this.run(async () => {
      setTodos((await api.updateTodo(item.id, { text: trimmed })).items);
    });
  }

  async deleteTodo(item: TodoItem): Promise<void> {
    await this.run(async () => {
      setTodos((await api.deleteTodo(item.id)).items);
      this.setStatus("Deleted TODO");
    });
  }

  handleTodoTextKeydown(event: KeyboardEvent, item: TodoItem): void {
    const input = event.currentTarget as HTMLTextAreaElement;
    if (event.key === "Enter" && event.ctrlKey) {
      event.preventDefault();
      input.blur();
    } else if (event.key === "Escape") {
      input.value = item.text;
      input.blur();
    }
  }

  async deleteCompletedTodos(): Promise<void> {
    const completedTodos = get(todosStore).filter((item) => item.status === "done");
    const completedEmbedded = get(embeddedTodosStore).filter((item) => item.status === "done");
    if (completedTodos.length === 0 && completedEmbedded.length === 0) return;
    await this.run(async () => {
      let nextTodos = get(todosStore);
      for (const item of completedTodos) {
        nextTodos = (await api.deleteTodo(item.id)).items;
      }
      setTodos(nextTodos.filter((item) => !item.anchor_id));
      for (const item of completedEmbedded) {
        await editorPanes.flushSceneIfDirty(item.scene_id);
        const scene = await api.deleteEmbeddedTodo(item.scene_id, item.todo_id);
        await editorPanes.reconcileSceneFromServer(scene);
      }
      if (completedEmbedded.length > 0) await refreshEmbeddedTodos();
      const deletedCount = completedTodos.length + completedEmbedded.length;
      this.setStatus(`Deleted ${deletedCount} completed TODO${deletedCount === 1 ? "" : "s"}`);
    });
  }

  // ---- Embedded (in-prose) todos (GH #45) ----
  // Each mutation: flush the open pane's unsaved prose first (no data loss),
  // hit the intentful endpoint, reconcile the open pane from the returned scene,
  // then re-scan the index.
  async toggleEmbeddedTodo(item: EmbeddedTodoRecord): Promise<void> {
    await this.#mutateEmbedded(item.scene_id, () =>
      api.updateEmbeddedTodo(item.scene_id, item.todo_id, {
        status: item.status === "open" ? "done" : "open",
      }),
    );
  }

  async updateEmbeddedTodoNote(item: EmbeddedTodoRecord, note: string): Promise<void> {
    if (note === item.note) return;
    await this.#mutateEmbedded(item.scene_id, () =>
      api.updateEmbeddedTodo(item.scene_id, item.todo_id, { note }),
    );
  }

  async deleteEmbeddedTodo(item: EmbeddedTodoRecord): Promise<void> {
    await this.#mutateEmbedded(item.scene_id, () => api.deleteEmbeddedTodo(item.scene_id, item.todo_id));
  }

  async #mutateEmbedded(sceneId: string, mutate: () => Promise<Scene>): Promise<void> {
    await this.run(async () => {
      await editorPanes.flushSceneIfDirty(sceneId);
      const scene = await mutate();
      await editorPanes.reconcileSceneFromServer(scene);
      await refreshEmbeddedTodos();
    });
  }

  // ---- Navigation openers ----
  async openSearchHit(hit: SearchHit): Promise<void> {
    if (hit.file_id === "project") return;
    await this.run(async () => {
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

  async openEmbeddedTodo(item: EmbeddedTodoRecord): Promise<void> {
    await this.run(async () => {
      await editorPanes.openScene(item.scene_id);
      window.setTimeout(() => editorPanes.highlightEmbeddedTodoInOpenPane(item.scene_id, item.todo_id), 0);
    });
  }

  async openFileTodo(item: TodoItem): Promise<void> {
    if (!item.scene_id) return;
    await this.run(async () => {
      await editorPanes.openScene(item.scene_id!);
    });
  }
}

export const todoActions = new TodoActions();
