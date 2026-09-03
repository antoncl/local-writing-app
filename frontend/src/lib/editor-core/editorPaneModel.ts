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
  PromptContextStrategy,
  PromptInputDefinition,
} from "@/lib/types";
import { canonicalizeInputDefinitions } from "@/lib/utils/promptInputs";

// A lightweight handle to the open document: which kind it is + its id. The
// pane resolves the full document into `scene`.
export type DocumentRef = {
  type: "manuscript" | "lore" | "prompt" | "assistant" | "project" | "structure_node" | "chat" | "research" | "view" | "plot_template" | "plot_card" | "plotline" | "tag";
  id: string;
};

export type EditorPaneState = {
  id: string;
  document: DocumentRef | null;
  // The server baseline the drafts are diffed against (immutable until a save
  // or an explicit baseline refresh replaces it).
  scene: EditableDocument | null;
  dirty: boolean;
  draftTitle: string;
  draftMarkdown: string;
  draftStatus: string;
  draftEntryType: string;
  draftMetadata: EntryMetadata;
  // Per-entry prompt inputs. Only meaningful when document.type === "prompt";
  // ignored for other kinds. Persisted in the entry's YAML on save.
  draftInputs: PromptInputDefinition[];
  // The subject entry_types this prompt is offered on in a node's Conversations
  // ＋New menu (ADR-0054 §4 / S4b `offer_on`). Prompt-only, like draftInputs;
  // ignored for other kinds. Persisted in the entry's YAML on save.
  draftOfferOn: string[];
  // The prompt's instance `context_strategy` (ADR-0065 S3 / ADR-0062 D3): which
  // OutputHandler runs its result, plus commit/on_accept/headless. Prompt-only,
  // like draftInputs/draftOfferOn; ignored for other kinds. Persisted in the
  // entry's YAML on save — a save that omits it strips a forked prompt's output
  // config (the wipe bug D3 closes), so this must always ride the save doc.
  draftContextStrategy: PromptContextStrategy | null;
  saving: boolean;
  // True for ~2s after a successful save so the pane chip can briefly show
  // "Saved". Reset whenever the pane becomes dirty again.
  recentlySaved: boolean;
  // True while the pane's most recent save attempt FAILED and has not yet been
  // superseded by a success (#263). Non-transient by design: it persists across
  // edits/retries so the author never sees a failed view look "saved", and clears
  // only on the next successful save. Today only view panes set it (they run their
  // own persist loop, bypassing the generic autosave), but the field is generic.
  saveError: boolean;
  // ADR-0042's authoring layer L (#314), a layer id, for a lore pane: the write
  // target the rail picker chose. `null` for a local entry (save goes to its own
  // file). For an *inherited* entry the pane store seeds it to the open project's
  // layer id — the rest-position override — and the picker moves it up the chain.
  // Non-sticky: reset when the pane loads a different entry (openLore / forkLore).
  authoringLayerId: string | null;
};

// The save-lifecycle transitions a self-persisting body (the view designer, #263)
// reports up to its pane so the shared tab badge reflects its state — views run
// their own debounced save outside `saveEditorPane`, so they push these instead.
export type ViewSaveState = "dirty" | "saving" | "saved" | "error";

// A fresh, document-less pane (drafts default to a scene-shaped blank).
export function createEmptyEditorPane(id: string): EditorPaneState {
  return {
    id,
    document: null,
    scene: null,
    dirty: false,
    draftTitle: "",
    draftMarkdown: "",
    draftStatus: "draft",
    draftEntryType: "manuscript",
    draftMetadata: {},
    draftInputs: [],
    draftOfferOn: [],
    draftContextStrategy: null,
    saving: false,
    recentlySaved: false,
    saveError: false,
    authoringLayerId: null,
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
  offerOn?: string[],
  contextStrategy?: PromptContextStrategy | null,
): boolean {
  if (!scene) return false;
  if (title !== scene.title) return true;
  if (!bodiesEqual(body, scene.body)) return true;
  if (documentStatus(scene) ? status !== documentStatus(scene) : false) return true;
  if (entryType !== scene.entry_type) return true;
  if (!metadataEqual(metadata, scene.metadata ?? {})) return true;
  // Prompt-only: inputs are a per-entry array of definitions. Compare the
  // serialised form so reordering / type changes are detected — but canonicalize
  // both sides first (#1470): the draft is the editor's minimal save payload,
  // while the saved `scene` carries the server's filled model defaults (`hidden`,
  // `required: false`, an empty picker `options`). A raw compare is perpetually
  // unequal, so the pane would autosave itself forever with no edits.
  const sceneInputs = (scene as { inputs?: PromptInputDefinition[] }).inputs;
  if (inputs !== undefined && sceneInputs !== undefined) {
    if (
      JSON.stringify(canonicalizeInputDefinitions(inputs)) !==
      JSON.stringify(canonicalizeInputDefinitions(sceneInputs))
    ) {
      return true;
    }
  }
  // Prompt-only: offer_on is the ＋New targeting allow-list (S4b). Same guarded
  // compare as inputs — a non-prompt scene has no offer_on baseline, so editing
  // this draft can never mark such a pane dirty.
  const sceneOfferOn = (scene as { offer_on?: string[] }).offer_on;
  if (offerOn !== undefined && sceneOfferOn !== undefined) {
    if (JSON.stringify(offerOn) !== JSON.stringify(sceneOfferOn)) return true;
  }
  // Prompt-only: context_strategy is the instance behavior contract (output
  // mode, headless, commit/on_accept — ADR-0065 S3 / ADR-0062 D3). Same guarded
  // compare — a non-prompt scene carries no context_strategy key at all, so
  // editing this draft can never mark such a pane dirty.
  const sceneContextStrategy = (scene as { context_strategy?: PromptContextStrategy | null }).context_strategy;
  if (contextStrategy !== undefined && sceneContextStrategy !== undefined) {
    if (JSON.stringify(contextStrategy ?? null) !== JSON.stringify(sceneContextStrategy ?? null)) return true;
  }
  return false;
}

// The pane's editable non-body fields, as the draft-* bundle the pane holds.
export type DraftFields = {
  draftTitle: string;
  draftStatus: string;
  draftEntryType: string;
  draftMetadata: EntryMetadata;
  draftInputs: PromptInputDefinition[];
  draftOfferOn: string[];
  draftContextStrategy: PromptContextStrategy | null;
};

// The generic three-way rule (ADR-0077 §4/§5): only one side moved off `base` ⇒
// take the mover; both sides moved to the same place ⇒ take it; both moved to
// *different* places ⇒ conflict, with `local` kept as the placeholder (the
// dialog / caller decides what to do with a conflict; this never guesses).
function threeWay<T>(base: T, local: T, remote: T, eq: (a: T, b: T) => boolean): { value: T; conflict: boolean } {
  const localChanged = !eq(local, base);
  const remoteChanged = !eq(remote, base);
  if (!localChanged) return { value: remote, conflict: false };
  if (!remoteChanged) return { value: local, conflict: false };
  if (eq(local, remote)) return { value: local, conflict: false };
  return { value: local, conflict: true };
}

const metaEq = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

// Per-key three-way merge over the union of metadata keys, under the same rule
// as `threeWay`. A key whose merged value is `undefined` (deleted on the
// winning side) is omitted from the result, so a delete actually deletes.
function mergeMetadata(
  base: EntryMetadata,
  local: EntryMetadata,
  remote: EntryMetadata,
): { value: EntryMetadata; conflict: boolean } {
  const keys = new Set([...Object.keys(base ?? {}), ...Object.keys(local ?? {}), ...Object.keys(remote ?? {})]);
  const value: EntryMetadata = {};
  let conflict = false;
  for (const key of keys) {
    const merged = threeWay((base ?? {})[key], (local ?? {})[key], (remote ?? {})[key], metaEq);
    if (merged.conflict) conflict = true;
    if (merged.value !== undefined) value[key] = merged.value;
  }
  return { value, conflict };
}

// Field-level three-way merge for a document's structured (non-body) fields
// (ADR-0077 §4/§5): `base` (last-loaded doc) vs `remote` (re-fetched on-disk
// doc) vs `local` (the pane's live drafts). Each field applies `threeWay`
// independently — disjoint fields merge silently; a field both sides changed
// to *different* values conflicts (local's value rides as the placeholder).
// Metadata is merged per-key, not as a whole object, so editing different keys
// on each side never conflicts. `conflict` is the OR across every field/key;
// `fields` is always fully populated, but only trustworthy when `conflict` is
// false — a caller that finds a conflict falls to the dialog (§4's
// prove-disjoint-or-ask bias), never applies `fields` blind.
export function mergeStructuredFields(
  base: EditableDocument,
  remote: EditableDocument,
  local: DraftFields,
): { fields: DraftFields; conflict: boolean } {
  const strEq = (a: string, b: string) => a === b;
  const title = threeWay(base.title, local.draftTitle, remote.title, strEq);
  const status = threeWay(documentStatus(base), local.draftStatus, documentStatus(remote), strEq);
  const entryType = threeWay(base.entry_type, local.draftEntryType, remote.entry_type, strEq);
  const metadata = mergeMetadata(base.metadata ?? {}, local.draftMetadata ?? {}, remote.metadata ?? {});

  const inputsEq = (a: PromptInputDefinition[], b: PromptInputDefinition[]) =>
    JSON.stringify(canonicalizeInputDefinitions(a)) === JSON.stringify(canonicalizeInputDefinitions(b));
  const inputs = threeWay(
    (base as { inputs?: PromptInputDefinition[] }).inputs ?? [],
    local.draftInputs,
    (remote as { inputs?: PromptInputDefinition[] }).inputs ?? [],
    inputsEq,
  );

  const arrEq = (a: string[], b: string[]) => JSON.stringify(a) === JSON.stringify(b);
  const offerOn = threeWay(
    (base as { offer_on?: string[] }).offer_on ?? [],
    local.draftOfferOn,
    (remote as { offer_on?: string[] }).offer_on ?? [],
    arrEq,
  );

  const contextStrategy = threeWay(
    (base as { context_strategy?: PromptContextStrategy | null }).context_strategy ?? null,
    local.draftContextStrategy,
    (remote as { context_strategy?: PromptContextStrategy | null }).context_strategy ?? null,
    metaEq,
  );

  return {
    fields: {
      draftTitle: title.value,
      draftStatus: status.value,
      draftEntryType: entryType.value,
      draftMetadata: metadata.value,
      draftInputs: inputs.value,
      draftOfferOn: offerOn.value,
      draftContextStrategy: contextStrategy.value,
    },
    conflict:
      title.conflict ||
      status.conflict ||
      entryType.conflict ||
      metadata.conflict ||
      inputs.conflict ||
      offerOn.conflict ||
      contextStrategy.conflict,
  };
}

// Whether `remote` differs from `base` in the prompt-only structured fields
// (inputs / offer_on / context_strategy), canonicalized. The rung-2 field merge
// (#1633) re-seeds the title/status/entry_type/metadata widgets after adopting a
// remote value, but the prompt-input widgets have no such out-of-band re-seed — so
// a concurrent change to them is kept on the dialog path rather than silently
// merged (which the next edit would revert). Prompt panes only; a non-prompt doc
// carries none of these, so this is always false for them.
export function promptFieldsDiffer(base: EditableDocument, remote: EditableDocument): boolean {
  const inputs = (d: EditableDocument) =>
    JSON.stringify(canonicalizeInputDefinitions((d as { inputs?: PromptInputDefinition[] }).inputs ?? []));
  const offer = (d: EditableDocument) => JSON.stringify((d as { offer_on?: string[] }).offer_on ?? []);
  const ctx = (d: EditableDocument) =>
    JSON.stringify((d as { context_strategy?: PromptContextStrategy | null }).context_strategy ?? null);
  return inputs(base) !== inputs(remote) || offer(base) !== offer(remote) || ctx(base) !== ctx(remote);
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
