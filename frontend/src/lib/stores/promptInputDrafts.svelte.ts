// The declaration-side of prompt inputs, as a per-instance rune controller —
// the shape `LoreProposalController` / `SnapshotStripController` use, and
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
  MetadataValue,
  NodePickerConfig,
  PromptInputDefinition,
  SelectOption,
} from "@/lib/types";
import { type EntryInputDraft } from "@/lib/utils/promptInputs";

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
   *  on every emit. */
  toCanonical(): PromptInputDefinition[] {
    return this.drafts
      .filter((d) => d.name)
      .map((d) => {
        const out: PromptInputDefinition = {
          name: d.name,
          type: d.type,
        };
        if (d.label) out.label = d.label;
        if (d.required) out.required = true;
        if (d.type === "context_pick" || d.type === "entity_ref" || d.type === "entity_ref_list") {
          // All three ref-shaped types serialize their picker constraint as
          // a NodePickerConfig under `target` (per #40 — same wire shape on
          // both surfaces). `multiple` is derived from the type literal at
          // runtime (entity_ref → false, entity_ref_list → true), so any
          // value the editor wrote is non-load-bearing for entity_ref types.
          // Skip default / options for these types — they don't apply.
          out.target = d.nodePickerConfig as unknown as Record<string, MetadataValue>;
          return out;
        }
        // Persist a type-matched default so the stored YAML carries a real
        // boolean / number rather than a stringly value. `undefined` (and a
        // stray "") means unset → omit `default` entirely (#24).
        if (d.defaultValue !== undefined && d.defaultValue !== "") {
          out.default = this.#defaultForStorage(d.defaultValue, d.type);
        }
        if (d.type === "select") {
          // Emit SelectOption objects from the draft list, preserving the
          // author's label + color picks (used to round-trip-lose them via
          // the comma-string shape — see decisions-inputs-fields-uniformity).
          out.options = d.options
            .filter((o) => o.value.trim() !== "")
            .map((o) => {
              const item: SelectOption = { value: o.value.trim() };
              if (o.label) item.label = o.label;
              if (o.color) item.color = o.color;
              return item;
            });
        }
        return out;
      });
  }

  #toDraft(input: PromptInputDefinition): EntryInputDraft {
    // entity_ref / entity_ref_list / context_pick all carry their picker
    // constraint as a NodePickerConfig under `target` (post-#40). For other
    // types, target is unused — start with an empty config.
    const usesPicker =
      input.type === "context_pick" || input.type === "entity_ref" || input.type === "entity_ref_list";
    const nodePickerConfig =
      usesPicker && input.target && typeof input.target === "object"
        ? (input.target as unknown as NodePickerConfig)
        : ({ kinds: [], presets: [] } as NodePickerConfig);
    return {
      clientId: this.nextDraftId(),
      name: input.name,
      type: input.type,
      label: input.label ?? "",
      defaultValue: input.default === undefined || input.default === null ? undefined : String(input.default),
      // Structured option drafts (value / label / color). Mirrors the field-side
      // editor — see SelectOptionsEditor + decisions-inputs-fields-uniformity.
      options: (input.options ?? []).map((o) => ({
        value: o.value,
        label: o.label ?? "",
        color: o.color ?? null,
        originalValue: o.value,
      })),
      required: Boolean(input.required),
      nodePickerConfig,
      nameDerived: false,
    };
  }

  // Map an editor-side default string onto its stored, type-matched value.
  // boolean → real bool, number → real number (falls back to the raw string
  // if unparseable), everything else (text / long_text / select / refs) →
  // string. Only invoked for a defined, non-empty default (#24).
  #defaultForStorage(raw: string, type: EntryInputDraft["type"]): MetadataValue {
    if (type === "boolean") return raw === "true";
    if (type === "number") {
      const n = Number(raw);
      return Number.isFinite(n) ? n : raw;
    }
    return raw;
  }
}
