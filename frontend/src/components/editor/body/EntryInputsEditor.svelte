<!--
  EntryInputsEditor — the declared-inputs editor for a prompt entry. Extracted
  from CodeBodyView (#14, P2): the `<details class="entry-inputs-editor">` block
  plus all the draft-mutation + drag-reorder helpers.

  Owns presentational-only state (which row is expanded, the drag indices). The
  persisted piece — `entryInputDrafts` — is bind:'d to the parent so the parent's
  save logic owns serialization. `nextInputDraftId`/`entrySlugify` are shared from
  the parent so clientIds don't collide and slugification stays consistent across
  the two creation sites (see NodeEditor's reseed path).
-->
<script lang="ts">
  import DefaultValueEditor from "@/components/schema/DefaultValueEditor.svelte";
  import NodePickerConfigEditor from "@/components/schema/NodePickerConfigEditor.svelte";
  import SchemaFieldRow from "@/components/schema/SchemaFieldRow.svelte";
  import SelectOptionsEditor from "@/components/schema/SelectOptionsEditor.svelte";
  import { DEFAULT_FIELD_GLYPH } from "@/lib/utils/fieldIcons";
  import { type EntryInputDraft } from "@/lib/utils/promptInputs";
  import type { NodePickerConfig, PromptInputType } from "@/lib/types";

  interface Props {
    // Persisted shape (bind:'d by the parent); parent owns serialization.
    entryInputDrafts?: EntryInputDraft[];
    // Shared id factory + slug helper — same counters/rules as NodeEditor's
    // reseed path, so clientIds don't collide and names slugify consistently.
    nextInputDraftId: () => string;
    entrySlugify: (value: string) => string;
    // Outbound: declared-inputs changed (#14 — replaces inputsChange dispatch).
    onInputsChange?: () => void;
  }

  let {
    entryInputDrafts = $bindable([]),
    nextInputDraftId,
    entrySlugify,
    onInputsChange,
  }: Props = $props();

  // Which input row is currently expanded for editing. Matches the schema
  // field-row pattern (App.svelte: expandedSchemaFieldId): one row open at a
  // time, click anywhere on a collapsed row to expand it. Inputs whose
  // clientId is the expanded one render their full editor body; the rest
  // render the compact row chrome only. context_pick rows ignore this state
  // — they own their entire row via NodePickerConfigEditor mode="prompt".
  let expandedInputClientId: string | null = $state(null);

  function toggleInputRow(clientId: string): void {
    expandedInputClientId = expandedInputClientId === clientId ? null : clientId;
  }

  // Short label for the type chip in the collapsed row. Mirrors the
  // dropdown options in the expanded editor below.
  const INPUT_TYPE_LABEL: Record<string, string> = {
    text: "Text",
    long_text: "Long Text",
    number: "Number",
    boolean: "Boolean",
    select: "Select",
    entity_ref: "Entity Reference",
    entity_ref_list: "Entity Reference List",
    context_pick: "Context Picker",
    scene_ref: "Scene Reference",
    color: "Colour",
  };

  function inputIconClass(type: string): string {
    const glyph = DEFAULT_FIELD_GLYPH[type as keyof typeof DEFAULT_FIELD_GLYPH] ?? "letter-case";
    return `ti ti-${glyph}`;
  }

  function addEntryInput(): void {
    const draft: EntryInputDraft = {
      clientId: nextInputDraftId(),
      name: "",
      type: "text",
      label: "",
      defaultValue: undefined,
      options: [],
      required: false,
      nodePickerConfig: { kinds: [], presets: [] },
      nameDerived: true,
    };
    entryInputDrafts = [...entryInputDrafts, draft];
    // Auto-expand new rows so the empty grid is visible immediately —
    // matches the field-row editor's create-then-edit-inline flow.
    expandedInputClientId = draft.clientId;
    onInputsChange?.();
  }

  function removeEntryInput(index: number): void {
    const removed = entryInputDrafts[index];
    entryInputDrafts = entryInputDrafts.filter((_, i) => i !== index);
    if (removed && expandedInputClientId === removed.clientId) {
      expandedInputClientId = null;
    }
    onInputsChange?.();
  }

  function updateEntryInputLabel(index: number, label: string): void {
    entryInputDrafts = entryInputDrafts.map((draft, i) => {
      if (i !== index) return draft;
      const next = { ...draft, label };
      if (draft.nameDerived) next.name = entrySlugify(label);
      return next;
    });
    onInputsChange?.();
  }

  function updateEntryInputName(index: number, name: string): void {
    entryInputDrafts = entryInputDrafts.map((draft, i) =>
      i !== index ? draft : { ...draft, name: entrySlugify(name), nameDerived: false },
    );
    onInputsChange?.();
  }

  function updateEntryInput(
    index: number,
    patch: Partial<EntryInputDraft>,
  ): void {
    entryInputDrafts = entryInputDrafts.map((draft, i) =>
      i !== index ? draft : { ...draft, ...patch },
    );
    onInputsChange?.();
  }

  // Default-value setter for the type-aware controls. An empty string from
  // any control means "Unset" → stored as undefined (no default) (#24).
  function setEntryInputDefault(index: number, raw: string): void {
    updateEntryInput(index, { defaultValue: raw === "" ? undefined : raw });
  }

  function updateEntryInputNodePickerConfig(
    index: number,
    config: NodePickerConfig,
  ): void {
    updateEntryInput(index, { nodePickerConfig: config });
  }

  function moveEntryInput(from: number, to: number): void {
    if (from === to || from < 0 || to < 0) return;
    if (from >= entryInputDrafts.length || to >= entryInputDrafts.length) return;
    const next = entryInputDrafts.slice();
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    entryInputDrafts = next;
    onInputsChange?.();
  }

  // Linear before/after reorder for the inputs list. Mirrors the tree's
  // drag-handle UX but without the "into" mode — inputs are a flat list.
  let inputDragFromIndex: number | null = $state(null);
  let inputDragOverIndex: number | null = $state(null);
  let inputDragOverPosition: "before" | "after" | null = $state(null);

  function handleInputDragStart(event: DragEvent, index: number) {
    inputDragFromIndex = index;
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", String(index));
    }
  }

  function handleInputDragEnd() {
    inputDragFromIndex = null;
    inputDragOverIndex = null;
    inputDragOverPosition = null;
  }

  function handleInputDragOver(event: DragEvent, index: number) {
    if (inputDragFromIndex === null || inputDragFromIndex === index) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
    const target = event.currentTarget;
    if (!(target instanceof HTMLElement)) return;
    const rect = target.getBoundingClientRect();
    const position: "before" | "after" = event.clientY - rect.top < rect.height / 2 ? "before" : "after";
    if (inputDragOverIndex !== index || inputDragOverPosition !== position) {
      inputDragOverIndex = index;
      inputDragOverPosition = position;
    }
  }

  function handleInputDrop(event: DragEvent, index: number) {
    event.preventDefault();
    const from = inputDragFromIndex;
    const position = inputDragOverPosition;
    handleInputDragEnd();
    if (from === null || position === null || from === index) return;
    let to = position === "before" ? index : index + 1;
    if (from < to) to -= 1;
    moveEntryInput(from, to);
  }
</script>

<details class="entry-inputs-editor">
  <summary>
    Inputs <small>{entryInputDrafts.length}</small>
    <small class="entry-inputs-hint">declared on this prompt · use as <code>&lbrace;&lbrace; input.&lt;id&gt; &rbrace;&rbrace;</code></small>
  </summary>
  {#if entryInputDrafts.length === 0}
    <p class="muted entry-inputs-empty">No inputs yet. Click + Input to declare one.</p>
  {/if}
  {#each entryInputDrafts as draft, index (draft.clientId)}
    {#if draft.type === "context_pick"}
      <!-- context_pick owns its entire row (chevron · label · id ·
           type select · Required · Multiple · ×). Generic input types
           still render the .prompt-input-grid below. -->
      <div
        class="prompt-input-row prompt-input-row-context"
        role="group"
        class:dragging={inputDragFromIndex === index}
        class:drop-before={inputDragOverIndex === index && inputDragOverPosition === "before"}
        class:drop-after={inputDragOverIndex === index && inputDragOverPosition === "after"}
        ondragover={(e) => handleInputDragOver(e, index)}
        ondrop={(e) => handleInputDrop(e, index)}
      >
        <span
          class="tree-handle prompt-input-handle"
          draggable="true"
          role="button"
          tabindex="-1"
          aria-label="Drag to reorder"
          ondragstart={(e) => handleInputDragStart(e, index)}
          ondragend={handleInputDragEnd}
        >⋮⋮</span>
        <NodePickerConfigEditor
          config={draft.nodePickerConfig}
          label={draft.label}
          name={draft.name}
          required={draft.required}
          onChange={(config) => updateEntryInputNodePickerConfig(index, config)}
          onLabelChange={(value) => updateEntryInputLabel(index, value)}
          onNameChange={(value) => updateEntryInputName(index, value)}
          onRequiredChange={(value) => updateEntryInput(index, { required: value })}
          onTypeChange={(value) => updateEntryInput(index, { type: value })}
          onRemove={() => removeEntryInput(index)}
        />
      </div>
    {:else}
      {@const isExpanded = expandedInputClientId === draft.clientId}
      <!-- Collapsed-by-default row mirroring App.svelte's schema-field-row
           (decisions-inputs-fields-uniformity / #37). Click to expand into
           the inline editor below; new rows auto-expand. Composes the shared
           SchemaFieldRow owner so the chrome stays identical across surfaces;
           the meta snippet supplies the input-specific accessor pill + req
           badge + cog (its classes stay in this component's scope). -->
      <SchemaFieldRow
        rowClass="prompt-input-row-collapsed"
        iconClass={inputIconClass(draft.type)}
        name={draft.label || draft.name || "(unnamed input)"}
        typeLabel={INPUT_TYPE_LABEL[draft.type] ?? draft.type}
        expanded={isExpanded}
        draggable={entryInputDrafts.length > 1}
        dragging={inputDragFromIndex === index}
        dropBefore={inputDragOverIndex === index && inputDragOverPosition === "before"}
        dropAfter={inputDragOverIndex === index && inputDragOverPosition === "after"}
        onToggle={() => toggleInputRow(draft.clientId)}
        onDragStart={(e) => handleInputDragStart(e, index)}
        onDragEnd={handleInputDragEnd}
        onDragOver={(e) => handleInputDragOver(e, index)}
        onDrop={(e) => handleInputDrop(e, index)}
      >
        {#snippet meta()}
          {#if draft.name}
            <code class="prompt-input-accessor-mini">&lbrace;&lbrace; input.{draft.name} &rbrace;&rbrace;</code>
          {/if}
          {#if draft.required}<span class="prompt-input-required-badge" title="Required">req</span>{/if}
          <i class={`ti sfr-cog ${isExpanded ? "ti-chevron-up" : "ti-settings"}`} aria-hidden="true"></i>
        {/snippet}
      </SchemaFieldRow>
      {#if isExpanded}
        <div class="schema-field-inline prompt-input-inline">
          <div class="prompt-input-grid">
            <label>
              Label
              <input value={draft.label} placeholder="Topic to brainstorm" oninput={(e) => updateEntryInputLabel(index, (e.currentTarget as HTMLInputElement).value)} />
            </label>
            <label>
              ID
              <input value={draft.name} placeholder="topic_to_brainstorm" oninput={(e) => updateEntryInputName(index, (e.currentTarget as HTMLInputElement).value)} />
            </label>
            <label>
              Type
              <select value={draft.type} onchange={(e) => updateEntryInput(index, { type: (e.currentTarget as HTMLSelectElement).value as PromptInputType, defaultValue: undefined })}>
                <option value="text">Text</option>
                <option value="long_text">Long Text</option>
                <option value="number">Number</option>
                <option value="boolean">Boolean</option>
                <option value="select">Select</option>
                <option value="entity_ref">Entity Reference</option>
                <option value="entity_ref_list">Entity Reference List</option>
                <option value="context_pick">Context Picker</option>
                <option value="scene_ref">Scene Reference</option>
              </select>
            </label>
            <label>
              Default
              <DefaultValueEditor
                type={draft.type}
                value={draft.defaultValue}
                options={draft.options}
                onChange={(next) => setEntryInputDefault(index, next ?? "")}
              />
            </label>
            <label class="prompt-input-required">
              <input type="checkbox" checked={draft.required} onchange={(e) => updateEntryInput(index, { required: (e.currentTarget as HTMLInputElement).checked })} />
              Required
            </label>
            <button type="button" class="prompt-input-remove" title="Remove input" onclick={() => removeEntryInput(index)}>×</button>
          </div>
          {#if draft.type === "select"}
            <!-- Row-per-option editor — same SelectOptionsEditor the
                 metadata-field side uses. Replaces the comma-string text
                 box that round-tripped-lost labels and colors. See
                 decisions-inputs-fields-uniformity. -->
            <div class="prompt-input-options-editor">
              <SelectOptionsEditor
                options={draft.options}
                showMigrationHint={false}
                onChange={(next) => updateEntryInput(index, { options: next })}
              />
            </div>
          {/if}
          {#if draft.type === "entity_ref" || draft.type === "entity_ref_list"}
            <!-- Picker constraint config — same NodePickerConfigEditor the
                 metadata-field side uses (App.svelte:4666). mode="field"
                 hides presets + scene binding (entity_ref doesn't have
                 those concepts) and the Multiple toggle (cardinality is
                 implied by the type literal). See decisions-inputs-fields-
                 uniformity / #40. -->
            <div class="prompt-input-picker">
              <NodePickerConfigEditor
                mode="field"
                config={draft.nodePickerConfig}
                onChange={(config) => updateEntryInputNodePickerConfig(index, config)}
              />
            </div>
          {/if}
        </div>
      {/if}
    {/if}
  {/each}
  <div class="entry-inputs-add">
    <button type="button" onclick={addEntryInput}>+ Input</button>
  </div>
</details>

<style>
  /* Prompt-input row meta-cluster atoms co-located from styles.css (#14).
     Rendered in the `meta` snippet passed to SchemaFieldRow, so they carry
     this component's scope. The row chrome lives in SchemaFieldRow.svelte;
     .sfr-cog stays global. */

  /* Compact accessor pill rendered in the collapsed row's meta strip. */
  .prompt-input-accessor-mini {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 10.5px;
    color: var(--text-3);
    background: var(--inset);
    border: 1px solid var(--divider);
    border-radius: 4px;
    padding: 1px 6px;
  }

  /* "req" badge surfaced in the collapsed row so the author can tell at a
     glance which inputs are required without expanding them. */
  .prompt-input-required-badge {
    font-size: 9.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 1px 6px;
    border-radius: 999px;
    background: var(--accent-soft, color-mix(in srgb, var(--accent) 14%, var(--surface)));
    color: var(--accent-strong, var(--accent));
  }

  /* --- Entry-inputs editor, co-located from styles.css (#14). Child-DOM
     reaches use :global: .danger (NodePickerConfigEditor), .prompt-input-grid
     label controls (DefaultValueEditor). --- */
  .entry-inputs-editor {
    padding: 6px 12px;
    background: var(--inset);
    border-top: 1px solid var(--border);
    font-size: 13px;
  }
  .entry-inputs-editor[open] {
    max-height: 50vh;
    overflow-y: auto;
  }
  .entry-inputs-editor > summary {
    cursor: pointer;
    user-select: none;
    font-weight: 600;
    color: var(--text);
    display: flex;
    align-items: baseline;
    gap: 6px;
  }
  .entry-inputs-editor > summary > small {
    color: var(--text-3);
    font-weight: 400;
  }
  .entry-inputs-hint {
    margin-left: auto;
    font-size: 11px;
  }
  .entry-inputs-hint > code {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 0 4px;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }
  .entry-inputs-empty {
    margin: 6px 0;
    font-size: 12px;
  }
  .entry-inputs-add {
    margin-top: 6px;
  }
  .entry-inputs-editor .prompt-input-row {
    position: relative;
    margin: 6px 0;
    padding: 8px 8px 8px 22px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 4px;
  }
  .entry-inputs-editor .prompt-input-handle {
    position: absolute;
    top: 50%;
    left: 4px;
    transform: translateY(-50%);
    font-size: 14px;
  }
  .entry-inputs-editor .prompt-input-row.dragging {
    opacity: 0.45;
  }
  .entry-inputs-editor .prompt-input-row.drop-before::before,
  .entry-inputs-editor .prompt-input-row.drop-after::after {
    content: "";
    position: absolute;
    left: 4px;
    right: 4px;
    height: 2px;
    background: var(--accent);
    border-radius: 2px;
    pointer-events: none;
  }
  .entry-inputs-editor .prompt-input-row.drop-before::before {
    top: -2px;
  }
  .entry-inputs-editor .prompt-input-row.drop-after::after {
    bottom: -2px;
  }
  .entry-inputs-editor .prompt-input-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 6px 10px;
    align-items: end;
  }
  .entry-inputs-editor .prompt-input-row-context {
    margin-bottom: 8px;
  }
  .entry-inputs-editor .prompt-input-picker {
    margin-top: 8px;
  }
  .entry-inputs-editor .prompt-input-options-editor {
    margin-top: 8px;
  }
  .entry-inputs-editor .prompt-input-inline {
    margin-top: 2px;
  }
  .entry-inputs-editor .prompt-input-grid > label {
    display: grid;
    gap: 2px;
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-3);
  }
  .entry-inputs-editor .prompt-input-grid > label :global(input),
  .entry-inputs-editor .prompt-input-grid > label :global(select) {
    padding: 3px 6px;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 12px;
    background: var(--surface);
  }
  .entry-inputs-editor .prompt-input-required {
    flex-direction: row;
    align-items: center;
    gap: 4px;
  }
  .entry-inputs-editor .prompt-input-required > input {
    margin: 0;
  }
  .entry-inputs-editor .prompt-input-remove {
    align-self: end;
    border: 1px solid transparent;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    font-size: 16px;
    line-height: 1;
    padding: 0 8px;
    border-radius: 4px;
  }
  .entry-inputs-editor .prompt-input-remove:hover {
    background: var(--danger-soft);
    color: var(--danger);
    border-color: var(--danger-border);
  }
  .prompt-input-row {
    display: grid;
    gap: 6px;
    padding: 8px;
    border: 1px dashed var(--border);
    border-radius: 6px;
    background: var(--surface);
  }
  .prompt-input-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 6px 8px;
  }
  .prompt-input-options {
    grid-column: 1 / -1;
  }
  .prompt-input-row :global(.danger) {
    justify-self: end;
    background: transparent;
    border: 1px solid var(--danger-border);
    color: var(--danger);
  }
  .prompt-input-row :global(.danger):hover {
    background: var(--danger-soft);
  }
</style>
