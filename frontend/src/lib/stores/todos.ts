// Todos domain store — the top-level TODO roster shown in the Todo pane.
// (Anchor-bound todos are embedded in scene bodies and tracked per-pane, not
// here.) Server-mirrored slice extracted from App.svelte for the #14 state
// layer; `writable` for legacy-safe reads (see docs/frontend-architecture.md).

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { EmbeddedTodoRecord, TodoItem } from "@/lib/types";

export const todosStore = writable<TodoItem[]>([]);

// The rebuildable embedded-todo index (in-prose markers across all scenes,
// GH #45). Editor-pane independent — scanned from disk, refreshed on project
// open, after any scene save, and after any embedded-todo mutation.
export const embeddedTodosStore = writable<EmbeddedTodoRecord[]>([]);

// Top-level todos only — `anchor_id` items live inline in scene prose.
export async function refreshTodos(): Promise<void> {
  todosStore.set((await api.getTodos()).items.filter((item) => !item.anchor_id));
}

export async function refreshEmbeddedTodos(): Promise<void> {
  embeddedTodosStore.set((await api.getEmbeddedTodos()).items);
}

// Write-through from a todo mutation. Sets the list verbatim (the mutation
// callers pass exactly what the prior App.svelte assignments did — the
// project-open/refresh path filters anchor_id, the per-mutation path does not).
export function setTodos(items: TodoItem[]): void {
  todosStore.set(items);
}

export function clearTodos(): void {
  todosStore.set([]);
  embeddedTodosStore.set([]);
}
