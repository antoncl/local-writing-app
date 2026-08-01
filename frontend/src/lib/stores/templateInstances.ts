// Template-instances domain store (ADR-0048 §3 / S7 Slice 5a) — the book's plot
// *arcs*, loaded on project open. The board's arc palette (the collapsible rail)
// reads this light roster directly; each arc's specialized beats live in its
// `metadata.instance_beats`, editable by opening the arc in the NodeEditor. Kept
// separate from the heavy on-demand board projection, the same way the plotlines
// store is — a light list the palette needs whether or not the board is measured.
// Server-mirrored slice, same shape as the plotlines/templates stores.

import { writable } from "svelte/store";
import { api } from "@/lib/api";
import type { TemplateInstanceSummary } from "@/lib/types";

export const templateInstancesStore = writable<TemplateInstanceSummary[]>([]);

export async function refreshTemplateInstances(): Promise<void> {
  templateInstancesStore.set((await api.listTemplateInstances()).entries);
}

// Write-through from a mutation that already returns the canonical roster (delete
// returns the remaining instances), so the palette updates without a second fetch.
export function setTemplateInstances(entries: TemplateInstanceSummary[]): void {
  templateInstancesStore.set(entries);
}

// Delete an arc and mirror the refreshed roster (the palette's remove action). The
// pane-Delete path routes through editorPaneDelete instead; both land here.
export async function deleteTemplateInstance(entryId: string): Promise<void> {
  setTemplateInstances((await api.deleteTemplateInstance(entryId)).entries);
}

export function clearTemplateInstances(): void {
  templateInstancesStore.set([]);
}
