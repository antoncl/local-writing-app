<script lang="ts" module>
  import { LIST_ITEM_SCALAR_TYPES } from "@/lib/types";
  import type {
    ListItemScalarType,
    MetadataFieldType,
    MetadataFieldDefinition,
    MetadataGroupDefinition,
    NodePickerConfig,
  } from "@/lib/types";
  import type { OptionDraft } from "@/components/schema/SelectOptionsEditor.svelte";

  // The assembled field draft emitted on save. The parent (App.saveSchemaField)
  // owns persistence (option migration, removed-value confirm, rename, refresh);
  // this component owns the draft + form. (#14 Step 4 — field-editor self-containment.)
  export type FieldDraftPayload = {
    type: MetadataFieldType;
    name: string;
    id: string;
    icon: string | null;
    description: string;
    group: string;
    defaultValue: string | undefined;
    options: OptionDraft[];
    // Computed-field settings. Both are free strings so the editor round-trips
    // any function/scope the backend authorises — including `cost` — and never
    // coerces one it doesn't recognize (#353). Vocabulary + on-disk mapping
    // live in `schemaTypeHelpers.AUTHORABLE_COMPUTED_FUNCTIONS`.
    computedFunction: string;
    computedScope: string;
    pickerConfig: NodePickerConfig;
    // `list` fields only (#698): exactly one is non-null — the item shape is
    // a named group or a single scalar type. Both null for every other type.
    itemGroup: string | null;
    itemType: ListItemScalarType | null;
    // Whether the AI may author this field on a brainstorm commit (ADR-0059 §E).
    // Default true; the parent omits it on save unless false (built-in default).
    aiProposable: boolean;
  };

  // Monotonic per-instance counter → a unique `id` for each editor's section
  // datalist (#1000). More than one field editor can be mounted across schema
  // surfaces; a shared datalist id would cross-wire their suggestion lists.
  let sectionListSeq = 0;
</script>

<script lang="ts">
  // Expand-in-place field editor (metadata revision, mockup C) used by the
  // type editor inside `<section class="pane schema-type-pane">`. One
  // row's editor is open at a time, accent-striped, directly under its row.
  //
  // Self-contained (#14 Step 4): the component owns the in-progress draft as
  // plain local state, initialized once from the `field` prop. Because the host
  // mounts a fresh instance per expanded row, the `let x = field?.…` init
  // captures the right starting values and the user's edits below are never
  // clobbered by a background schema refresh. On save it hands the assembled
  // draft up via `onSave`; the parent owns the side-effects (migration, confirm,
  // rename, refresh). Layer + readonly + which-field context still come in as
  // props (the parent computes them from the schema overview).

  import { untrack } from "svelte";
  import IconPicker from "@/components/widgets/IconPicker.svelte";
  import { anchoredPopover } from "@/lib/actions/anchoredPopover";
  import NodePickerConfigEditor from "@/components/schema/NodePickerConfigEditor.svelte";
  import SelectOptionsEditor from "@/components/schema/SelectOptionsEditor.svelte";
  import DefaultValueEditor from "@/components/schema/DefaultValueEditor.svelte";
  import ToggleSwitch from "@/components/widgets/ToggleSwitch.svelte";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import {
    DEFAULT_FIELD_GLYPH,
    FIELD_TYPE_CHOICES,
    fieldIconClass,
    fieldTypeLabel,
  } from "@/lib/utils/fieldIcons";
  import {
    AUTHORABLE_COMPUTED_FUNCTIONS,
    computedFunctionChoice,
    slugifyFieldId,
  } from "@/lib/utils/schemaTypeHelpers";

  interface Props {
    // --- Context from parent (read-only) ---
    // `field` is the existing definition being edited, or null for a fresh draft.
    // `selectedFieldId` is its stable key (null while creating) — drives the
    // key-rename semantics + the Remove affordance.
    field?: MetadataFieldDefinition | null;
    selectedFieldId?: string | null;
    readonly?: boolean;
    layerId?: string;
    // The schema's named group definitions — the item-shape choices a `list`
    // field can reference (#698). Keyed by group id.
    groups?: Record<string, MetadataGroupDefinition>;
    // Section labels already in use on this type (#1000) — the datalist
    // suggestions behind the freeform Section input, so it doubles as a
    // pick-from-existing dropdown. Distinct not required (deduped below).
    sectionLabels?: string[];
    // --- Callback props (parent owns persistence) ---
    onSave?: (payload: FieldDraftPayload) => void;
    onCancel?: () => void;
    onRemove?: () => void;
  }

  let {
    field = null,
    selectedFieldId = null,
    readonly = false,
    layerId = "",
    groups = {},
    sectionLabels = [],
    onSave = () => {},
    onCancel = () => {},
    onRemove = () => {},
  }: Props = $props();

  // --- Draft state (initialized once at mount from `field`) ---
  // The host remounts a fresh instance per expanded row, so seeding once from
  // the props is correct (a background schema refresh never clobbers edits).
  // Read every prop inside one `untrack` block to avoid `state_referenced_locally`.
  const seed = untrack(() => {
    const f = field;
    return {
      type: (f?.type ?? "text") as MetadataFieldType,
      name: f?.name ?? "",
      id: selectedFieldId ?? "",
      icon: f?.icon ?? null,
      description: f?.description ?? "",
      group: f?.group ?? "",
      // Stringify the persisted default for the editor; null / undefined → "no
      // default". A real `false` boolean default stays editable as "False".
      defaultValue:
        f?.default === undefined || f?.default === null ? undefined : String(f.default),
      // `originalValue` lets a later value rename migrate stored data even after
      // the rows are reordered.
      options: (f?.options ?? []).map((o) => ({
        value: o.value,
        label: o.label ?? "",
        color: o.color ?? null,
        originalValue: o.value,
      })) as OptionDraft[],
      // Preserve the stored function/scope exactly (#353) — a `cost` field
      // (or any function the frontend doesn't yet mirror) round-trips
      // unchanged rather than being coerced to word_count. A fresh / non-
      // computed field seeds word_count with no scope.
      computedFunction: f?.computed?.function ?? "word_count",
      computedScope: f?.computed?.scope ?? "",
      pickerConfig: (f?.picker_config
        ? {
            sources: [...(f.picker_config.sources ?? [])],
            presets: [...(f.picker_config.presets ?? [])],
          }
        : { sources: [{ kind: "lore" }] }) as NodePickerConfig,
      // `list` item shape (#698): "group:<id>" or "scalar:<type>". A field
      // that isn't already a list seeds EMPTY — switching a field's type to
      // List must not silently persist a shape the author never chose; the
      // Done button stays disabled until they pick one.
      itemShape: f?.item_group
        ? `group:${f.item_group}`
        : f?.item_type
          ? `scalar:${f.item_type}`
          : "",
      // Default true (ADR-0059 §E) — a field is AI-writable unless the author
      // opts out. Seeds from an existing field's stored flag.
      aiProposable: f?.ai_proposable ?? true,
    };
  });
  let type: MetadataFieldType = $state(seed.type);
  let name: string = $state(seed.name);
  let id: string = $state(seed.id);
  let icon: string | null = $state(seed.icon);
  let description: string = $state(seed.description);
  let group: string = $state(seed.group);
  let defaultValue: string | undefined = $state(seed.defaultValue);
  let options: OptionDraft[] = $state(seed.options);
  let computedFunction: string = $state(seed.computedFunction);
  let computedScope: string = $state(seed.computedScope);
  // The scope choices the current function offers (empty for word_count, or for
  // a function the frontend doesn't recognize). Drives the Scope select below.
  const computedScopeChoices = $derived(computedFunctionChoice(computedFunction)?.scopes ?? []);
  // An existing field can carry a function this editor doesn't list yet (a
  // later backend addition). Keep it selectable and re-savable rather than
  // silently rewriting it — the same "show the real value" idiom as the list
  // item-shape fallback below.
  const computedFunctionUnknown = $derived(computedFunctionChoice(computedFunction) === undefined);
  let pickerConfig: NodePickerConfig = $state(seed.pickerConfig);
  let itemShape: string = $state(seed.itemShape);
  const itemGroup = $derived(itemShape.startsWith("group:") ? itemShape.slice(6) : null);
  const itemType = $derived(
    itemShape.startsWith("scalar:") ? (itemShape.slice(7) as ListItemScalarType) : null,
  );
  let aiProposable: boolean = $state(seed.aiProposable);
  // The AI-authorship toggle only applies to types the AI can ever propose:
  // references and computed values are never proposed regardless of the flag
  // (backend `NON_PROPOSABLE_FIELD_TYPES`), so the control is hidden for them
  // rather than shown as an inert switch.
  const aiProposableApplies = $derived(
    type !== "computed" && type !== "entity_ref" && type !== "entity_ref_list",
  );
  // Groups offered as item shapes: only members inside the one scalar
  // catalog (LIST_ITEM_SCALAR_TYPES — same source as the backend's positive
  // integrity check). A group with, e.g., an entity_ref member is legal to
  // APPLY (flattened) but would 422 as an item shape, so it isn't offered.
  const shapeableGroups = $derived(
    Object.entries(groups).filter(([, groupDef]) =>
      groupDef.members.every((m) => (LIST_ITEM_SCALAR_TYPES as readonly string[]).includes(m.type)),
    ),
  );
  // An EXISTING field can point at a group the filter above excludes (the
  // group gained an unsupported member later) or that no longer exists — the
  // select must still show the field's real shape rather than render blank
  // and unreachable (the organize-level fallback idiom).
  const currentShapeMissing = $derived(
    itemGroup !== null && !shapeableGroups.some(([groupId]) => groupId === itemGroup),
  );
  // Groups OFFERED as a new item shape hide the built-in system machinery
  // (#1003) — but keep the field's current group if it happens to be a system
  // one (a built-in plot list field), so its shape still shows and validates.
  const offeredGroups = $derived(
    shapeableGroups.filter(([groupId, groupDef]) => !groupDef.system || groupId === itemGroup),
  );
  let typeMenuOpen = $state(false);
  let keyEditing = $state(false);
  let keyManual = $state(false);
  let iconPickerOpen = $state(false);
  let iconBtnEl: HTMLButtonElement | undefined = $state();
  let typeChipEl: HTMLButtonElement | undefined = $state();
  // Flip the type-grid popover above its trigger when there isn't room below
  // (#1001) — opened from a field low in a tall editor it would otherwise run
  // past the fold. (The icon popover no longer needs this: it's body-portaled
  // and viewport-anchored via `anchoredPopover` (#1573), so the pane can't clip
  // it at all — a strictly better fix than this viewport-based estimate, which
  // is blind to the pane's own `overflow` box.)
  function flipUp(el: HTMLElement | undefined, estHeight: number): boolean {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    // Flip only when below is too tight AND above has more room, so it never
    // makes things worse. estHeight ≈ the popover's max height + chrome.
    return spaceBelow < estHeight && rect.top > spaceBelow;
  }
  // The type grid caps at ~260px (2 cols × ~6 rows); flips off its own trigger.
  let typeFlipUp = $state(false);
  $effect(() => {
    typeFlipUp = typeMenuOpen && flipUp(typeChipEl, 260);
  });

  // Section datalist (#1000): distinct, non-empty labels already used on this
  // type. The freeform input lists them so it doubles as a pick-from-existing
  // dropdown; the id is unique per instance (see module counter).
  const sectionSuggestions = $derived([
    ...new Set(sectionLabels.map((s) => s.trim()).filter(Boolean)),
  ]);
  const sectionListId = `sfi-section-list-${(sectionListSeq += 1)}`;

  // Keep the type-specific config blocks coherent when the user picks a
  // different type from the grid.
  function chooseType(next: MetadataFieldType) {
    type = next;
    typeMenuOpen = false;
    if (next === "computed" && computedFunctionChoice(computedFunction) === undefined) {
      chooseFunction("word_count");
    }
  }

  // Switching the computed function resets the scope to that function's default
  // (its first scope) whenever the current scope isn't one it offers — so a
  // counter's `siblings` never rides along onto a `cost` field, and vice versa.
  // word_count (no scopes) clears the scope entirely.
  function chooseFunction(next: string) {
    computedFunction = next;
    const scopes = computedFunctionChoice(next)?.scopes ?? [];
    if (scopes.length === 0) {
      computedScope = "";
    } else if (!scopes.some((s) => s.value === computedScope)) {
      computedScope = scopes[0].value;
    }
  }

  // Auto-derive the stable key only while CREATING a field and only until the
  // key is hand-edited. Once the field exists, the name renames freely and the
  // key changes solely via the explicit "rename (migrates)" path.
  function updateName(value: string) {
    name = value;
    if (!readonly && selectedFieldId === null && !keyManual) {
      id = slugifyFieldId(value);
    }
  }

  function handleKeyInput(value: string) {
    keyManual = true;
    id = slugifyFieldId(value);
  }

  // Click-outside closes the type grid + icon popover (was App-level). Bound to
  // `click`, not `mousedown` (#1001): a press on a scrollbar gutter fires
  // mousedown but no click, so scrolling the popover no longer dismisses it.
  function handleDocumentClick(event: MouseEvent) {
    const target = event.target as HTMLElement | null;
    // The icon popover is body-portaled (#1573), so a click inside it is no
    // longer under `.sfi-icon-anchor` — allow `.sfi-icon-pop` too, or selecting
    // an icon would dismiss the picker.
    if (iconPickerOpen && !target?.closest(".sfi-icon-anchor") && !target?.closest(".sfi-icon-pop")) {
      iconPickerOpen = false;
    }
    if (typeMenuOpen && !target?.closest(".sfi-type-anchor")) typeMenuOpen = false;
  }

  function emitSave() {
    onSave({
      type,
      name,
      id,
      icon,
      description,
      group,
      defaultValue,
      options,
      computedFunction,
      computedScope,
      pickerConfig,
      itemGroup: type === "list" ? itemGroup : null,
      itemType: type === "list" ? itemType : null,
      aiProposable,
    });
  }

  const saveDisabled = $derived(
    !layerId ||
      !id.trim() ||
      !name.trim() ||
      (type === "list" && !itemGroup && !itemType) ||
      // An unresolvable current shape can't be persisted (the backend
      // integrity check 422s it), so block Done and say why inline rather
      // than let the author hit a server error — they must pick a supported
      // shape (or Cancel) to proceed.
      (type === "list" && currentShapeMissing),
  );
</script>

<svelte:window onclick={handleDocumentClick} />

<div class="schema-field-inline" role="group" aria-label="Field settings">
  <div class="sfi-head">
    <div class="sfi-icon-anchor">
      <button
        type="button"
        class="sfr-tile sfi-icon-btn"
        aria-label="Choose icon"
        title="Choose icon"
        bind:this={iconBtnEl}
        onclick={() => (iconPickerOpen = !iconPickerOpen)}
      >
        <i class={fieldIconClass({ type, icon })} aria-hidden="true"></i>
      </button>
      {#if iconPickerOpen}
        <div class="sfi-icon-pop" use:anchoredPopover={{ anchor: iconBtnEl }}>
          <IconPicker
            value={icon}
            defaultGlyph={DEFAULT_FIELD_GLYPH[type] ?? "letter-case"}
            fieldLabel={name || "field"}
            onSelect={(next) => (icon = next)}
            onClose={() => (iconPickerOpen = false)}
          />
        </div>
      {/if}
    </div>
    <input
      class="sfi-name"
      value={name}
      placeholder="Field name"
      aria-label="Field display name"
      oninput={(event) => updateName(event.currentTarget.value)}
    />
    <div class="sfi-type-anchor">
      <button
        type="button"
        class="sfi-type-chip"
        class:open={typeMenuOpen}
        aria-haspopup="true"
        aria-expanded={typeMenuOpen}
        aria-label="Change field type"
        bind:this={typeChipEl}
        onclick={() => (typeMenuOpen = !typeMenuOpen)}
      >
        <i class={`ti ti-${DEFAULT_FIELD_GLYPH[type] ?? "letter-case"}`} aria-hidden="true"></i>
        <span class="sfi-type-chip-label">{fieldTypeLabel(type)}</span>
        <GroupCaret size="xs" />
      </button>
      {#if typeMenuOpen}
        <div class="sfi-type-grid" class:up={typeFlipUp} role="listbox" aria-label="Field type">
          {#each FIELD_TYPE_CHOICES as choice (choice)}
            <button
              type="button"
              class="sfi-type-cell"
              class:selected={type === choice}
              role="option"
              aria-selected={type === choice}
              onclick={() => chooseType(choice)}
            >
              <i class={`ti ti-${DEFAULT_FIELD_GLYPH[choice] ?? "letter-case"}`} aria-hidden="true"></i>
              <span>{fieldTypeLabel(choice)}</span>
            </button>
          {/each}
        </div>
      {/if}
    </div>
  </div>
  <label class="sfi-field sfi-description">
    Description
    <textarea
      value={description}
      placeholder="What is this field for? Shown as a tooltip, and given to the AI when brainstorming this field."
      aria-label="Field description"
      rows="2"
      oninput={(event) => (description = event.currentTarget.value)}
    ></textarea>
  </label>
  {#if aiProposableApplies}
    <div class="sfi-toggle">
      <ToggleSwitch
        checked={aiProposable}
        ariaLabel="AI may write this field"
        onChange={(next) => (aiProposable = next)}
      />
      <span>AI may write this field when committing a brainstorm</span>
    </div>
  {/if}
  <div class="sfi-controls">
    <label class="sfi-field">Section
      <input
        value={group}
        placeholder="— none —"
        aria-label="Section"
        list={sectionListId}
        oninput={(event) => (group = event.currentTarget.value)}
      />
      <datalist id={sectionListId}>
        {#each sectionSuggestions as label (label)}
          <option value={label}></option>
        {/each}
      </datalist>
    </label>
  </div>
  <div class="sfi-key-row">
    {#if keyEditing}
      <span class="sfi-key-tag">key</span>
      <input
        class="sfi-key-input"
        value={id}
        aria-label="Field key"
        oninput={(event) => handleKeyInput(event.currentTarget.value)}
      />
      <span class="sfi-key-hint">{selectedFieldId ? "changing the key migrates existing values" : "auto-derived from the name"}</span>
    {:else if id}
      <span class="sfi-id">key <code>{id}</code></span>
      {#if !readonly}
        <button type="button" class="sfi-key-rename" onclick={() => (keyEditing = true)}>
          {selectedFieldId ? "rename (migrates)" : "edit key"}
        </button>
      {/if}
    {/if}
  </div>
  {#if type === "entity_ref" || type === "entity_ref_list"}
    <div class="schema-field-picker-config">
      <NodePickerConfigEditor
        mode="field"
        config={pickerConfig}
        onChange={(next) => (pickerConfig = next)}
      />
    </div>
  {/if}
  {#if type === "computed"}
    <div class="sfi-computed">
      <label class="sfi-field">Computation
        <select
          value={computedFunction}
          aria-label="Computation"
          onchange={(event) => chooseFunction(event.currentTarget.value)}
        >
          {#if computedFunctionUnknown}
            <!-- Preserve a stored function this editor doesn't list (a later
                 backend addition) rather than coerce it (#353). -->
            <option value={computedFunction} disabled>{computedFunction} (unrecognized — preserved)</option>
          {/if}
          {#each AUTHORABLE_COMPUTED_FUNCTIONS as fn (fn.value)}
            <option value={fn.value}>{fn.label}</option>
          {/each}
        </select>
      </label>
      {#if computedScopeChoices.length > 0}
        <label class="sfi-field">Scope
          <select bind:value={computedScope} aria-label="Scope">
            {#each computedScopeChoices as scope (scope.value)}
              <option value={scope.value}>{scope.label}</option>
            {/each}
          </select>
        </label>
      {/if}
      <p class="sfi-options-hint">
        <i class="ti ti-info-circle" aria-hidden="true"></i>
        computed values are derived automatically and can't be edited on the entry
      </p>
    </div>
  {/if}
  {#if type === "list"}
    <!-- The list type's whole config is ONE question (#698, per the agreed
         mockup): what is an item — a named group (defined once, in Groups,
         never re-declared per list) or a single value. -->
    <div class="sfi-computed">
      <label class="sfi-field">Items are
        <select bind:value={itemShape} aria-label="List item shape">
          {#if !itemShape}
            <option value="" disabled>Choose an item shape…</option>
          {/if}
          {#if currentShapeMissing}
            <!-- The field's real shape stays representable even when the
                 group is filtered out (unsupported members) or deleted —
                 with the reason that actually applies. -->
            <option value={`group:${itemGroup}`} disabled>
              {groups[itemGroup ?? ""]
                ? `${groups[itemGroup ?? ""].name} (current shape — unsupported members)`
                : `${itemGroup} (current shape — group not found)`}
            </option>
          {/if}
          {#if offeredGroups.length > 0}
            <optgroup label="A group…">
              {#each offeredGroups as [groupId, groupDef] (groupId)}
                <option value={`group:${groupId}`}>
                  {groupDef.name} ({groupDef.members.map((m) => m.name || m.key).join(" · ")})
                </option>
              {/each}
            </optgroup>
          {/if}
          <optgroup label="A single value…">
            {#each LIST_ITEM_SCALAR_TYPES as scalarChoice (scalarChoice)}
              <option value={`scalar:${scalarChoice}`}>{fieldTypeLabel(scalarChoice)}</option>
            {/each}
          </optgroup>
        </select>
      </label>
      {#if currentShapeMissing}
        <p class="sfi-options-hint">
          <i class="ti ti-alert-triangle" aria-hidden="true"></i>
          this field's item shape is no longer valid — pick a supported shape to save (existing items keep their shape until then)
        </p>
      {:else}
        <p class="sfi-options-hint">
          <i class="ti ti-info-circle" aria-hidden="true"></i>
          a group shape is defined once, in Groups — reused here, never re-declared
        </p>
      {/if}
    </div>
  {/if}
  {#if type === "select" || type === "multi_select" || (type === "list" && itemType === "select")}
    <SelectOptionsEditor
      options={options}
      onChange={(next) => (options = next)}
    />
  {/if}
  {#if type !== "computed" && type !== "list"}
    <!-- Default-value editor (#38). Shared with the prompt-inputs editor
         via DefaultValueEditor. Empty = no default (the historic
         behaviour). Computed fields omit this — their value is derived,
         not authored. `list` omits it too (v1, #698): the string-typed
         default contract can't carry structured items, and list defaults
         are rare enough to defer rather than half-support. -->
    <label class="sfi-field sfi-default-field">
      Default for new entries
      <DefaultValueEditor
        type={type}
        value={defaultValue}
        options={options}
        ariaLabel="Default for new entries"
        onChange={(next) => (defaultValue = next)}
      />
    </label>
  {/if}
  <div class="sfi-footer">
    <span class="sfi-spacer"></span>
    {#if selectedFieldId}
      <button class="link-danger" type="button" onclick={() => onRemove()}>Remove</button>
    {/if}
    <button class="sfi-cancel" type="button" onclick={() => onCancel()}>Cancel</button>
    <button class="sfi-done" type="button" disabled={saveDisabled} onclick={emitSave}>Done</button>
  </div>
</div>

<style>
  /* Inline field-editor chrome co-located from styles.css (#14). These target
     this component's own elements only — head row, icon picker button, name
     input, the field-type chip + grid picker, the computed-config wrapper, and
     the stable-key row. The form atoms shared with the other schema surfaces
     (.sfi-field/-footer/-cancel/-done/-spacer/-options-hint), the container
     .schema-field-inline (also worn by CodeBodyView's prompt-input editor), and
     the .sfr-tile/.sfr-cog row atoms stay global. */
  .sfi-head {
    display: flex;
    align-items: center;
    gap: 9px;
  }
  .sfi-icon-anchor {
    position: relative;
    flex: none;
  }
  /* The icon picker button wears the tile's shape (.sfr-tile, global); this
     adds the dashed "click to change" treatment over the solid display tile. */
  .sfi-icon-btn.sfr-tile {
    border-style: dashed;
    border-color: var(--border-strong, var(--border-strong));
  }
  .sfi-icon-btn {
    padding: 0;
    cursor: pointer;
  }
  .sfi-icon-btn:hover {
    border-color: var(--accent);
    color: var(--accent-strong);
  }
  /* Body-portaled + viewport-anchored by `anchoredPopover` (#1573); the action
     owns position/left/top, this carries only the portaled elevation tier (must
     clear the modal layer, matching SwatchPicker/TagPicker — not `z-index: 60`,
     which would open behind a dialog embedding this editor). */
  .sfi-icon-pop {
    z-index: 10000;
  }
  .sfi-name {
    flex: 1;
    min-width: 0;
    padding: 6px 9px;
    border: 1px solid var(--border, var(--border));
    border-radius: 8px;
    background: var(--surface);
    font-size: var(--fs-md);
  }
  /* Author help text (#1004). Full-width, vertically resizable. */
  .sfi-description textarea {
    width: 100%;
    box-sizing: border-box;
    padding: 6px 9px;
    border: 1px solid var(--border, var(--border));
    border-radius: 8px;
    background: var(--surface);
    font-family: inherit;
    font-size: var(--fs-md);
    resize: vertical;
  }
  /* Type chip + grid popover (the 11-type field-type picker). */
  .sfi-type-anchor {
    position: relative;
    flex: none;
  }
  .sfi-type-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px 9px;
    border: 1px solid var(--border, var(--border));
    border-radius: 8px;
    background: var(--surface);
    font-size: var(--fs-sm);
    color: var(--text-2, var(--text-2));
    cursor: pointer;
  }
  .sfi-type-chip:hover,
  .sfi-type-chip.open {
    border-color: var(--accent);
    color: var(--accent-strong);
  }
  .sfi-type-chip-label {
    font-weight: 500;
  }
  .sfi-type-grid {
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    z-index: 60;
    display: grid;
    grid-template-columns: repeat(2, minmax(120px, 1fr));
    gap: 4px;
    padding: 6px;
    border: 1px solid var(--border, var(--border));
    border-radius: 10px;
    background: var(--surface);
    box-shadow: var(--elev-2);
  }
  /* Flipped above the chip when there's no room below (#1001). */
  .sfi-type-grid.up {
    top: auto;
    bottom: calc(100% + 6px);
  }
  .sfi-type-cell {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 9px;
    border: 1px solid transparent;
    border-radius: 8px;
    background: transparent;
    font-size: var(--fs-sm);
    color: var(--text-2, var(--text-2));
    text-align: left;
    cursor: pointer;
  }
  .sfi-type-cell i {
    font-size: var(--fs-lg);
    color: var(--text-3, var(--text-3));
  }
  .sfi-type-cell:hover {
    background: var(--inset);
  }
  .sfi-type-cell.selected {
    border-color: var(--accent);
    background: var(--inset);
    color: var(--accent-strong);
    font-weight: 500;
  }
  .sfi-type-cell.selected i {
    color: var(--accent);
  }
  .sfi-computed {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .sfi-controls {
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
  }
  /* The AI-authorship switch sits at the left; the caption flows beside it and
     wraps naturally rather than being pushed right by a stretched control. */
  .sfi-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .sfi-toggle span {
    flex: 1;
    min-width: 0;
  }
  .sfi-id {
    font-size: var(--fs-xs);
    color: var(--text-3, var(--text-3));
  }
  .sfi-id code {
    font-size: var(--fs-xs);
    font-family: var(--mono);
    color: var(--text-2, var(--text-2));
  }
  /* Stable-key row (decision #10): key shown as quiet mono + rename affordance. */
  .sfi-key-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }
  .sfi-key-rename {
    border: 0;
    background: transparent;
    padding: 0;
    font-size: var(--fs-xs);
    color: var(--accent);
    cursor: pointer;
  }
  .sfi-key-rename:hover {
    text-decoration: underline;
  }
  .sfi-key-tag {
    font-size: var(--fs-xs);
    color: var(--text-3, var(--text-3));
  }
  .sfi-key-input {
    width: 160px;
    padding: 5px 8px;
    border: 1px solid var(--accent);
    border-radius: 8px;
    background: var(--surface);
    font-family: var(--mono);
    font-size: var(--fs-sm);
  }
  .sfi-key-hint {
    font-size: var(--fs-xs);
    color: var(--text-3, var(--text-3));
  }
</style>
