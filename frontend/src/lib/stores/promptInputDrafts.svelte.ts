// The declaration-side of prompt inputs, as a per-instance rune controller —
// the shape `EntryProposalController` / `SnapshotStripController` use, and
// NodeEditor already composes.
//
// Inputs live on the entry (not the entry-type). The `drafts` here are the
// editor-side form state (bound into CodeBodyView → EntryInputsEditor); on
// every edit the host rebuilds the canonical `PromptInputDefinition[]` via
// `toCanonical()` and emits it as part of the change event. The host seeds the
// drafts from the open entry on a scene switch (`reseed`) and serializes them
// for save (`toCanonical`); `slugify` + `nextDraftId` are shared into the
// authoring editor so clientIds don't collide and name slugification is
// consistent across the two creation sites. See decisions-inputs-fields-
// uniformity + decisions-node-editor-modularization (Phase 2).
import type {
  DocumentKind,
  EditableDocument,
  PromptInputDefinition,
} from "@/lib/types";
import {
  type EntryInputDraft,
  inputDefinitionToDraft,
  inputDraftToDefinition,
} from "@/lib/utils/promptInputs";

export class PromptInputDraftsController {
  // The editor-side form state — bound into CodeBodyView (`bind:entryInputDrafts`).
  drafts = $state<EntryInputDraft[]>([]);

  // Monotonic client-id counter. A distinct namespace from any other draft
  // source so ids can't collide when both the reseed and the authoring editor
  // mint them.
  #counter = 0;
  // Reactive identity key for the reseed: when the open entry changes (id),
  // re-seed the drafts. Compared via id rather than reference because Svelte
  // may pass the same object reference between renders.
  #lastSeededSceneId: string | null = null;

  // Arrow fields so `this` survives being passed as a prop into CodeBodyView.
  nextDraftId = (): string => {
    this.#counter += 1;
    return `__input_${this.#counter}`;
  };

  slugify = (value: string): string =>
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^[0-9]/, "input_$&");

  /** Seed drafts from the open entry. `scene` only changes when a different
   *  entry is opened or after a save; the user's typing updates `drafts`
   *  locally without touching `scene`, so this won't fight in-flight edits. */
  reseed(scene: EditableDocument | null, documentKind: DocumentKind): void {
    if (documentKind !== "prompt" || !scene) {
      this.#lastSeededSceneId = null;
      return;
    }
    if (scene.id === this.#lastSeededSceneId) return;
    const sceneInputs =
      (scene as unknown as { inputs?: PromptInputDefinition[] }).inputs ?? [];
    this.drafts = sceneInputs.map((input) => this.#toDraft(input));
    this.#lastSeededSceneId = scene.id;
  }

  /** The canonical `PromptInputDefinition[]` for save — rebuilt from the drafts
   *  on every emit. The per-item shaping lives in `inputDraftToDefinition`
   *  (shared with the autosave dirty-check, #1470). */
  toCanonical(): PromptInputDefinition[] {
    return this.drafts.filter((d) => d.name).map(inputDraftToDefinition);
  }

  #toDraft(input: PromptInputDefinition): EntryInputDraft {
    return inputDefinitionToDraft(input, this.nextDraftId());
  }
}
