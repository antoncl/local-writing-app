// Todos domain store — the top-level TODO roster shown in the Todo pane.
// (Anchor-bound todos are embedded in scene bodies and tracked per-pane, not
// here.) Server-mirrored slice extracted from App.svelte for the #14 state
// layer; `writable` for legacy-safe reads (see docs/frontend-architecture.md).

import { writable } from "svelte/store";
import { api } from "../api";
import type { TodoItem } from "../types";

export const todosStore = writable<TodoItem[]>([]);

// Top-level todos only — `anchor_id` items live inline in scene prose.
export async function refreshTodos(): Promise<void> {
  todosStore.set((await api.getTodos()).items.filter((item) => !item.anchor_id));
}

// Write-through from a mutation returning the full TodoDocument.
export function setTodos(doc: { items: TodoItem[] }): void {
  todosStore.set(doc.items.filter((item) => !item.anchor_id));
}

export function clearTodos(): void {
  todosStore.set([]);
}
