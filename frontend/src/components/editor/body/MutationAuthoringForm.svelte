<script lang="ts" module>
  export type MutationDraft = { entity: string; field: string; value: string; markerId?: string };
</script>

<script lang="ts">
  // Authoring/edit form for lore mutations (#33, #56). Reuses the node editor's
  // field-editing widgets — ReferencePicker (→ NodePicker) to pick the entity,
  // and FieldValueEditor per field so every value uses that field type's own
  // control (the inputs-uniformity principle). Create mode sets one or more
  // fields (→ N markers). Edit mode (given `initial`) edits one existing marker
  // and can delete it.
  import { untrack } from "svelte";
  import ReferencePicker from "@/components/widgets/ReferencePicker.svelte";
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import type {
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataSchema,
    MetadataValue,
    PromptEntrySummary,
    ScopedTag,
    StructureDocument,
  } from "@/lib/types";

  let {
    loreEntries = [],
    promptEntries = [],
    schema = null,
    structure = null,
    researchStructure = null,
    knownTags = [],
    implicitContextMatcher = null,
    initial = null,
    presetEntityId = "",
    onSubmit,
    onDelete,
    onCancel,
  }: {
    loreEntries: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    schema: MetadataSchema | null;
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    knownTags?: ScopedTag[];
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    initial?: MutationDraft | null;
    /** Pre-selected entity id for create mode (e.g. from `/mutate Alice`). */
    presetEntityId?: string;
    onSubmit: (drafts: MutationDraft[]) => void;
    onDelete?: (markerId: string) => void;
    onCancel: () => void;
  } = $props();

  const editing = $derived(Boolean(initial?.markerId));

  // The dialog re-mounts on each open ({#if} in the parent), so capturing the
  // initial prop values once is intentional (untrack silences the lint).
  let entityId = $state(untrack(() => initial?.entity ?? presetEntityId ?? ""));
  // field id -> { on, value }. Value is a normalized MetadataValue from the editor.
  let picks = $state<Record<string, { on: boolean; value: MetadataValue }>>(
    untrack(() => (initial ? { [initial.field]: { on: true, value: initial.value } } : {})),
  );

  const entity = $derived(loreEntries.find((e) => e.id === entityId) ?? null);

  // Intrinsic node fields (not schema fields) that are always mutable.
  const INTRINSIC: Array<{ id: string; def: MetadataFieldDefinition }> = [
    { id: "title", def: { name: "Title (name)", type: "text", options: [] } as MetadataFieldDefinition },
    { id: "body", def: { name: "Body", type: "long_text", options: [] } as MetadataFieldDefinition },
  ];

  // The entity's mutable fields: intrinsic title/body + its resolved schema
  // fields, minus computed (derived) and collection types (multi_select / tags /
  // entity_ref_list are additive-flavored — v1.1). In edit mode, just the one.
  const fieldOptions = $derived.by((): Array<{ id: string; label: string; def: MetadataFieldDefinition }> => {
    if (!entity) return [];
    if (initial) {
      const def = schema?.fields[initial.field] ?? INTRINSIC.find((f) => f.id === initial.field)?.def
        ?? ({ name: initial.field, type: "text", options: [] } as MetadataFieldDefinition);
      return [{ id: initial.field, label: def.name ?? initial.field, def }];
    }
    const opts = INTRINSIC.map((f) => ({ id: f.id, label: f.def.name, def: f.def }));
    const ids = schema?.entry_types[entity.entry_type]?.fields ?? [];
    for (const id of ids) {
      const def = schema?.fields[id];
      if (!def) continue;
      if (["computed", "multi_select", "tags", "entity_ref_list"].includes(def.type)) continue;
      opts.push({ id, label: def.name ?? id, def });
    }
    return opts;
  });

  const entityRefField = {
    name: "Entity",
    type: "entity_ref",
    options: [],
    picker_config: { kinds: ["lore"] },
  } as MetadataFieldDefinition;

  function isFilled(value: MetadataValue): boolean {
    if (value === null || value === undefined || value === "") return false;
    if (Array.isArray(value)) return value.length > 0;
    return true;
  }

  function toMarkerString(value: MetadataValue): string {
    if (value === null || value === undefined) return "";
    if (typeof value === "boolean") return value ? "true" : "false";
    return String(value);
  }

  const canSubmit = $derived(
    Boolean(entity) && fieldOptions.some((f) => picks[f.id]?.on && isFilled(picks[f.id]?.value)),
  );

  function selectEntity(value: string | string[]) {
    entityId = Array.isArray(value) ? (value[0] ?? "") : value;
  }

  function toggle(id: string, on: boolean) {
    picks[id] = { on, value: picks[id]?.value ?? "" };
  }

  function setValue(id: string, value: MetadataValue) {
    picks[id] = { on: picks[id]?.on ?? true, value };
  }

  function submit() {
    if (!entity) return;
    const drafts: MutationDraft[] = [];
    for (const f of fieldOptions) {
      const pick = picks[f.id];
      if (pick?.on && isFilled(pick.value)) {
        drafts.push({
          entity: entity.id,
          field: f.id,
          value: toMarkerString(pick.value),
          ...(initial?.markerId ? { markerId: initial.markerId } : {}),
        });
      }
    }
    if (drafts.length > 0) onSubmit(drafts);
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
    } else if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && canSubmit) {
      event.preventDefault();
      submit();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="mutation-overlay" role="presentation" onclick={onCancel}>
  <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
  <div
    class="mutation-card"
    role="dialog"
    aria-label="Record lore mutation"
    tabindex="-1"
    onclick={(e) => e.stopPropagation()}
  >
    <header class="mutation-head">
      <h3>{editing ? "Edit mutation" : "Record lore mutation"}</h3>
      <p>The change takes effect here and in every later scene.</p>
    </header>

    <div class="mutation-row">
      <span class="mutation-label">Entity</span>
      <ReferencePicker
        field={entityRefField}
        value={entityId}
        ariaLabel="Entity"
        loreEntries={loreEntries}
        promptEntries={promptEntries}
        structure={structure}
        researchStructure={researchStructure}
        on:change={(e) => selectEntity(e.detail.value)}
      />
    </div>

    {#if entity}
      <div class="mutation-fields">
        {#each fieldOptions as f (f.id)}
          <div class="mutation-field">
            <label class="mutation-check">
              <input
                type="checkbox"
                checked={picks[f.id]?.on ?? false}
                disabled={editing}
                onchange={(e) => toggle(f.id, e.currentTarget.checked)}
              />
              <span>{f.label}</span>
            </label>
            {#if picks[f.id]?.on}
              <div class="mutation-value">
                <FieldValueEditor
                  field={f.def}
                  value={picks[f.id]?.value ?? ""}
                  ariaLabel={f.label}
                  loreEntries={loreEntries}
                  promptEntries={promptEntries}
                  structure={structure}
                  researchStructure={researchStructure}
                  implicitContextMatcher={implicitContextMatcher}
                  knownTags={knownTags}
                  documentKind="lore"
                  entryType={entity.entry_type}
                  onChange={(v) => setValue(f.id, v)}
                />
              </div>
            {/if}
          </div>
        {/each}
      </div>
    {/if}

    <footer class="mutation-foot">
      {#if editing && initial?.markerId}
        <button type="button" class="danger" onclick={() => onDelete?.(initial.markerId!)}>Delete</button>
      {/if}
      <span class="mutation-foot-spacer"></span>
      <button type="button" class="ghost" onclick={onCancel}>Cancel</button>
      <button type="button" class="primary" disabled={!canSubmit} onclick={submit}>
        {editing ? "Save" : "Insert mutation"}
      </button>
    </footer>
  </div>
</div>

<style>
  .mutation-overlay {
    position: fixed;
    inset: 0;
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.28);
  }
  .mutation-card {
    width: min(460px, 92vw);
    max-height: 82vh;
    overflow-y: auto;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.24);
    padding: 18px;
  }
  .mutation-head h3 {
    margin: 0 0 2px;
    font-size: 1.05rem;
    color: var(--text);
  }
  .mutation-head p {
    margin: 0 0 14px;
    font-size: 0.82rem;
    color: var(--text-3);
  }
  .mutation-row {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-bottom: 12px;
  }
  .mutation-label {
    font-size: 0.78rem;
    font-weight: 600;
    color: var(--text-2);
  }
  .mutation-fields {
    display: flex;
    flex-direction: column;
    gap: 10px;
    border-top: 1px solid var(--border);
    padding-top: 12px;
    margin-bottom: 12px;
  }
  .mutation-field {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .mutation-check {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.9rem;
    color: var(--text);
    cursor: pointer;
  }
  .mutation-value {
    display: flex;
    padding-left: 22px;
  }
  .mutation-value > :global(*) {
    flex: 1 1 auto;
    min-width: 0;
  }
  .mutation-foot {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .mutation-foot-spacer {
    flex: 1 1 auto;
  }
  button {
    padding: 7px 14px;
    border-radius: 6px;
    font: inherit;
    cursor: pointer;
    border: 1px solid var(--border);
  }
  button.ghost {
    background: transparent;
    color: var(--text-2);
  }
  button.danger {
    background: transparent;
    color: #b4442f;
    border-color: color-mix(in oklab, #b4442f 40%, transparent);
  }
  button.primary {
    background: var(--accent);
    border-color: var(--accent);
    color: #fff;
    font-weight: 600;
  }
  button.primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
