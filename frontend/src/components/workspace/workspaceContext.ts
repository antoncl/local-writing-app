// Editor-document render hooks for the tiled workspace (#32). Region content
// comes from the global panelRegistry; editor documents are the one dynamic,
// always-closable surface class, so their rendering is threaded to the
// recursive WorkspaceNode via context. App builds this once for <Workspace/>.

import type { Snippet } from "svelte";
import type { PanelId } from "@/lib/types";

export const WORKSPACE_KEY = Symbol("workspace-editor");

export type WorkspaceEditor = {
  // Tab label for an open document (its title).
  title: (id: PanelId) => string;
  // Save-state badge ("Saving…" / "Unsaved" / "Saved"), or null when clean.
  badge: (id: PanelId) => { text: string; saved: boolean } | null;
  // Close (save-and-close) a document tab.
  onClose: (id: PanelId) => void;
  // The document editor, keyed by panel id (branches in App scope so the
  // NodeEditor bindings stay where the editor state lives).
  body: Snippet<[PanelId]>;
  // Per-document tab-bar affordances (Delete, Pin).
  actions: Snippet<[PanelId]>;
};
