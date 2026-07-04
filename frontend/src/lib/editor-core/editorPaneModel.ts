// Editor-pane draft model — the pure, dependency-free core of an open editor
// pane, factored out of App.svelte (#14 P0). An EditorPaneState is the unit the
// MDI editor windows render and autosave: the loaded server document (`scene`),
// the live drafts the user is editing, and the flags that drive the save
// lifecycle. The functions here are the *semantics* of that model — what an
// empty pane is, whether a pane is dirty, the title overrides it projects onto
// the manuscript tree — with no app/store/api coupling, so they're trivially
// testable and reusable by the editor-panes controller (and App's projections).

import type {
  EditableDocument,
  EntryMetadata,
  PromptInputDefinition,
} from "@/lib/types";

// A lightweight handle to the open document: which kind it is + its id. The
// pane resolves the full document into `scene`.
export type DocumentRef = {
  type: "scene" | "lore" | "prompt" | "assistant" | "project" | "structure_node" | "chat" | "research" | "view";
  id: string;
};

export type EditorPaneState = {
  id: string;
  document: DocumentRef | null;
  // The server baseline the drafts are diffed against (immutable until a save
  // or an explicit baseline refresh replaces it).
  scene: EditableDocument | null;
  pinned: boolean;
  dirty: boolean;
  draftTitle: string;
  draftMarkdown: string;
  draftStatus: string;
  draftEntryType: string;
  draftMetadata: EntryMetadata;
  // Per-entry prompt inputs. Only meaningful when document.type === "prompt";
  // ignored for other kinds. Persisted in the entry's YAML on save.
  draftInputs: PromptInputDefinition[];
  saving: boolean;
  // True for ~2s after a successful save so the pane chip can briefly show
  // "Saved". Reset whenever the pane becomes dirty again.
  recentlySaved: boolean;
};

// A fresh, document-less pane (drafts default to a scene-shaped blank).
export function createEmptyEditorPane(id: string): EditorPaneState {
  return {
    id,
    document: null,
    scene: null,
    pinned: false,
    dirty: false,
    draftTitle: "",
    draftMarkdown: "",
    draftStatus: "draft",
    draftEntryType: "scene",
    draftMetadata: {},
    draftInputs: [],
    saving: false,
    recentlySaved: false,
  };
}

export function documentStatus(document: EditableDocument | null): string {
  return document && "status" in document ? document.status : "";
}

export function bodiesEqual(left: string | null | undefined, right: string | null | undefined): boolean {
  // The backend normalizes every entry body on write (`body.rstrip() + "\n"`)
  // but the read path only lstrips, so the round-tripped server baseline always
  // carries a trailing newline the editor draft lacks. A raw `!==` would mark an
  // untouched pane perpetually dirty, autosaving every 6s forever. Compare
  // ignoring trailing whitespace (matching the backend's `rstrip`) so an
  // unedited pane converges to clean; trailing whitespace can never persist
  // anyway, so nothing meaningful is masked.
  return (left ?? "").replace(/\s+$/, "") === (right ?? "").replace(/\s+$/, "");
}

export function metadataEqual(left: EntryMetadata, right: EntryMetadata): boolean {
  return JSON.stringify(left ?? {}) === JSON.stringify(right ?? {});
}

// Deep-clone a metadata object so draft edits never alias the server baseline
// (or vice versa). Shared by App's general metadata handling and the
// editor-panes controller, which clones on every draft update and save.
export function cloneMetadata(metadata: EntryMetadata): EntryMetadata {
  return JSON.parse(JSON.stringify(metadata ?? {})) as EntryMetadata;
}

// Whether the live drafts differ from the server baseline. The single source of
// truth for autosave eligibility.
export function isEditorPaneDirty(
  scene: EditableDocument | null,
  title: string,
  body: string,
  status: string,
  entryType: string,
  metadata: EntryMetadata,
  inputs?: PromptInputDefinition[],
): boolean {
  if (!scene) return false;
  if (title !== scene.title) return true;
  if (!bodiesEqual(body, scene.body)) return true;
  if (documentStatus(scene) ? status !== documentStatus(scene) : false) return true;
  if (entryType !== scene.entry_type) return true;
  if (!metadataEqual(metadata, scene.metadata ?? {})) return true;
  // Prompt-only: inputs are a per-entry array of definitions. Compare the
  // serialised form so reordering / type changes are detected.
  const sceneInputs = (scene as { inputs?: PromptInputDefinition[] }).inputs;
  if (inputs !== undefined && sceneInputs !== undefined) {
    if (JSON.stringify(inputs) !== JSON.stringify(sceneInputs)) return true;
  }
  return false;
}

// Map of scene id -> pending (unsaved) title, for panes whose draft title
// diverges from the saved scene. The manuscript/research trees read this to show
// live renames before they persist.
export function computeDraftTitleOverrides(panes: EditorPaneState[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const pane of panes) {
    const sceneId = pane.scene?.id;
    if (!sceneId) continue;
    const trimmed = pane.draftTitle.trim();
    if (trimmed && trimmed !== pane.scene?.title) {
      map.set(sceneId, trimmed);
    }
  }
  return map;
}
