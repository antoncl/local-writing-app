<script lang="ts" module>
  export type MutationDraft = {
    entity: string;
    field: string;
    op?: string; // "replace" (default) | "add" | "remove" (#58)
    value: string;
    markerId?: string;
    name?: string;
    group?: string;
  };
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
  import { api } from "@/lib/api";
  import { createMutationId } from "@/lib/editor-core/mutationNodes";
  import type {
    TransformationEntrySummary,
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

  const COLLECTION_TYPES = ["multi_select", "tags", "entity_ref_list"];
  const isCollectionType = (type: string) => COLLECTION_TYPES.includes(type);

  // Name-ish fields carry the scene-granular resolution caveat (#61): a rename
  // resolves per scene, so detection uses one name for the whole scene of the
  // change. Surfaced inline exactly when the writer picks such a field.
  const NAME_FIELDS = ["title", "name", "aliases"];
  const isNameField = (id: string) => NAME_FIELDS.includes(id);

  // The dialog re-mounts on each open ({#if} in the parent), so capturing the
  // initial prop values once is intentional (untrack silences the lint).
  let entityId = $state(untrack(() => initial?.entity ?? presetEntityId ?? ""));
  // field id -> { on, value }. Value is a normalized MetadataValue from the editor.
  let picks = $state<Record<string, { on: boolean; value: MetadataValue }>>(
    untrack(() => (initial ? { [initial.field]: { on: true, value: initial.value } } : {})),
  );
  // field id -> collection op ("replace" | "add" | "remove"). Only meaningful for
  // collection fields; scalar fields are always replace (#58).
  let ops = $state<Record<string, string>>(
    untrack(() => (initial?.op && initial.field ? { [initial.field]: initial.op } : {})),
  );

  const entity = $derived(loreEntries.find((e) => e.id === entityId) ?? null);

  // #62 in-flow: apply a saved transformation set, or capture the composed change
  // as a new reusable set. Both only in create mode. §6: an optional name labels
  // the change (shared across the co-authored group).
  let mode = $state<"manual" | "apply">("manual");
  let changeName = $state("");
  let saveAsSet = $state(false);
  let allSets = $state<TransformationEntrySummary[]>([]);
  // Type-scoped picker: only sets whose target matches the picked entity's type.
  const applicableSets = $derived(
    entity ? allSets.filter((s) => s.target_entry_type === entity.entry_type) : [],
  );

  $effect(() => {
    if (editing) return;
    let cancelled = false;
    api
      .listTransformationEntries()
      .then((res) => {
        if (!cancelled) allSets = res.entries;
      })
      .catch(() => {
        if (!cancelled) allSets = [];
      });
    return () => {
      cancelled = true;
    };
  });

  async function applySet(setId: string) {
    if (!entity) return;
    let full;
    try {
      full = await api.getTransformationEntry(setId);
    } catch {
      return;
    }
    // Expand to N independent inline markers as a co-authored group (shared name
    // + group default to the set's title) — a stamp, individually editable after.
    const group = createMutationId();
    const drafts: MutationDraft[] = full.rows.map((row) => ({
      entity: entity!.id,
      field: row.field,
      op: row.op || "replace",
      value: row.value,
      name: full.title,
      group,
    }));
    if (drafts.length > 0) onSubmit(drafts);
  }

  // The item-widget field def for an add/remove op: a collection resolves to its
  // single-element type (entity_ref_list → entity_ref, multi_select → select,
  // tags → text), so each add/remove marker carries one element (doc §1.5).
  function itemFieldDef(def: MetadataFieldDefinition): MetadataFieldDefinition {
    if (def.type === "entity_ref_list") return { ...def, type: "entity_ref" };
    if (def.type === "multi_select") return { ...def, type: "select" };
    return { ...def, type: "text" };
  }

  // The effective field def for a field's current op: item widget for add/remove,
  // the whole-collection widget for replace (and always for scalars).
  function effectiveDef(id: string, def: MetadataFieldDefinition): MetadataFieldDefinition {
    const op = ops[id] ?? "replace";
    return isCollectionType(def.type) && op !== "replace" ? itemFieldDef(def) : def;
  }

  function setOp(id: string, op: string) {
    ops[id] = op;
    // The value shape differs between replace (whole) and add/remove (one item),
    // so reset the pending value when the op changes.
    picks[id] = { on: picks[id]?.on ?? true, value: "" };
  }

  // Intrinsic node fields (not schema fields) that are always mutable.
  const INTRINSIC: Array<{ id: string; def: MetadataFieldDefinition }> = [
    { id: "title", def: { name: "Title (name)", type: "text", options: [] } as MetadataFieldDefinition },
    { id: "body", def: { name: "Body", type: "long_text", options: [] } as MetadataFieldDefinition },
  ];

  // The entity's mutable fields: intrinsic title/body + its resolved schema
  // fields, minus computed (derived). Collection fields (multi_select / tags /
  // entity_ref_list) are included and gain an add/remove/replace op selector
  // (#58). In edit mode, just the one.
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
      if (def.type === "computed") continue;
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
    const rows: { field: string; op: string; value: string }[] = [];
    for (const f of fieldOptions) {
      const pick = picks[f.id];
      if (!pick?.on || !isFilled(pick.value)) continue;
      const op = isCollectionType(f.def.type) ? (ops[f.id] ?? "replace") : "replace";
      // add/remove carry one element each; an array-valued item widget mints one
      // marker per element (doc §1.2). replace carries the whole value.
      const values =
        op !== "replace" && Array.isArray(pick.value)
          ? pick.value.map((item) => toMarkerString(item))
          : [toMarkerString(pick.value)];
      for (const value of values) {
        drafts.push({
          entity: entity.id,
          field: f.id,
          op,
          value,
          ...(initial?.markerId
            ? { markerId: initial.markerId, name: initial.name, group: initial.group }
            : {}),
        });
        rows.push({ field: f.id, op, value });
      }
    }
    if (drafts.length === 0) return;
    if (!editing) {
      // Co-authored group (§6): a shared name + group tie a plural change into one
      // nameable, close-together unit. Each record's interval stays independent.
      const named = changeName.trim();
      if (named || drafts.length > 1) {
        const group = createMutationId();
        for (const draft of drafts) {
          draft.group = group;
          if (named) draft.name = named;
        }
      }
      // Capture (§5.3): also save the composed change as a reusable set — the
      // entity is dropped (rows + target entry-type only), so it's a template.
      if (saveAsSet) {
        void api
          .createTransformationEntry({
            title: named || "Untitled set",
            target_entry_type: entity.entry_type,
            rows,
          })
          .catch(() => {});
      }
    }
    onSubmit(drafts);
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

    {#if entity && !editing && applicableSets.length > 0}
      <div class="mutation-mode" role="tablist">
        <button type="button" class:active={mode === "manual"} onclick={() => (mode = "manual")}>Set fields manually</button>
        <button type="button" class:active={mode === "apply"} onclick={() => (mode = "apply")}>Apply a saved set</button>
      </div>
    {/if}

    {#if entity && mode === "apply" && !editing}
      <ul class="set-list">
        {#each applicableSets as set (set.id)}
          <li>
            <button type="button" class="set-row" onclick={() => applySet(set.id)}>
              <span class="set-name">{set.title}</span>
              <span class="set-count">{set.row_count} field{set.row_count === 1 ? "" : "s"}</span>
            </button>
          </li>
        {/each}
      </ul>
    {:else if entity}
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
              {#if picks[f.id]?.on && isCollectionType(f.def.type)}
                <select
                  class="mutation-op"
                  aria-label="{f.label} operation"
                  value={ops[f.id] ?? "replace"}
                  onchange={(e) => setOp(f.id, e.currentTarget.value)}
                >
                  <option value="replace">Replace all</option>
                  <option value="add">Add item</option>
                  <option value="remove">Remove item</option>
                </select>
              {/if}
            </label>
            {#if picks[f.id]?.on}
              <div class="mutation-value">
                <FieldValueEditor
                  field={effectiveDef(f.id, f.def)}
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
              {#if isNameField(f.id)}
                <p class="mutation-note">
                  Name changes resolve <strong>per scene</strong>: within the scene of the change,
                  auto-detection uses one name for the whole scene.
                  <a
                    href="https://github.com/antoncl/local-writing-app/blob/master/docs/mutations.md#how-resolution-works--and-its-one-limit"
                    target="_blank"
                    rel="noopener"
                  >How resolution works ↗</a>
                </p>
              {/if}
            {/if}
          </div>
        {/each}
      </div>
      {#if !editing}
        <div class="mutation-capture">
          <label class="mutation-label" for="mutation-change-name">Name this change (optional)</label>
          <input
            id="mutation-change-name"
            class="mutation-name-input"
            value={changeName}
            placeholder="e.g. Full Moon transformation"
            oninput={(e) => (changeName = e.currentTarget.value)}
          />
          <label class="mutation-check">
            <input type="checkbox" checked={saveAsSet} onchange={(e) => (saveAsSet = e.currentTarget.checked)} />
            <span>Save as a reusable set for {entity.entry_type}</span>
          </label>
        </div>
      {/if}
    {/if}

    <footer class="mutation-foot">
      {#if editing && initial?.markerId}
        <button type="button" class="danger" onclick={() => onDelete?.(initial.markerId!)}>Delete</button>
      {/if}
      <span class="mutation-foot-spacer"></span>
      <button type="button" class="ghost" onclick={onCancel}>Cancel</button>
      {#if !(mode === "apply" && !editing)}
        <button type="button" class="primary" disabled={!canSubmit} onclick={submit}>
          {editing ? "Save" : "Insert mutation"}
        </button>
      {/if}
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
  .mutation-op {
    margin-left: auto;
    font: inherit;
    font-size: 0.78rem;
    padding: 2px 6px;
    border-radius: 5px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-2);
  }
  .mutation-value {
    display: flex;
    padding-left: 22px;
  }
  .mutation-note {
    margin: 4px 0 0;
    padding-left: 22px;
    font-size: 0.74rem;
    line-height: 1.35;
    color: var(--text-3);
  }
  .mutation-note a {
    color: var(--accent);
    white-space: nowrap;
  }
  .mutation-mode {
    display: flex;
    gap: 4px;
    margin-bottom: 12px;
  }
  .mutation-mode button {
    flex: 1 1 0;
    padding: 6px 10px;
    font-size: 0.82rem;
    background: transparent;
    color: var(--text-2);
  }
  .mutation-mode button.active {
    background: color-mix(in oklab, var(--accent) 14%, transparent);
    border-color: var(--accent);
    color: var(--text);
    font-weight: 600;
  }
  .set-list {
    list-style: none;
    margin: 0 0 12px;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .set-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
    width: 100%;
    padding: 8px 10px;
    text-align: left;
    background: transparent;
    color: var(--text);
  }
  .set-row:hover {
    background: var(--surface-2, rgba(0, 0, 0, 0.04));
  }
  .set-count {
    font-size: 0.76rem;
    color: var(--text-3);
    flex: 0 0 auto;
  }
  .mutation-capture {
    display: flex;
    flex-direction: column;
    gap: 6px;
    border-top: 1px solid var(--border);
    padding-top: 12px;
    margin-bottom: 12px;
  }
  .mutation-name-input {
    padding: 6px 8px;
    border-radius: 6px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    font: inherit;
    font-size: 0.85rem;
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
