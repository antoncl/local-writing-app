// Editor-focus UI store — the cross-pane selection projection the list panes
// (Tree, Lore, Prompts, Assistants) read for their active-row highlight and
// pin-star indicator. Unlike the other stores this is NOT server-mirrored: it
// is a projection of App's per-pane `editorPanes` state. App is the SOLE writer
// (two `$:` write-throughs); the panes only read. This replaces drilling
// focusedDocument + pinnedKeys as props into every list pane (#14 Step 2).
//
// (Not an event bus — a store with a single, traceable writer. See
// docs/frontend-architecture.md.)

import { writable } from "svelte/store";

// The document open in the currently-focused editor pane, or null. The loose
// `{ type; id }` shape matches what the panes compare against (App's richer
// DocumentRef union is assignable to it).
export const focusedDocumentStore = writable<{ type: string; id: string } | null>(null);

// `"<type>:<id>"` keys for every node open in a pinned editor pane.
export const pinnedKeysStore = writable<Set<string>>(new Set());

export function setFocusedDocument(doc: { type: string; id: string } | null): void {
  focusedDocumentStore.set(doc);
}

export function setPinnedKeys(keys: Set<string>): void {
  pinnedKeysStore.set(keys);
}
