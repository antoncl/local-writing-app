<script lang="ts">
  // The ordered-list value widget (#698, ADR-0048 §6): ONE row-based
  // add/remove/reorder editor for `list` fields, agreed via the mockup
  // (docs/design/mockups/0048-ordered-list-field.html). The item shape is the
  // resolver-stamped `item_members` — a named group's members, or the
  // item_type sugar normalized to one member — and members render through
  // FieldValueEditor verbatim, so every scalar keeps its default widget
  // (long_text members get MetadataLongTextEditor, selects get
  // ColoredSelect, …).
  //
  // One density rule, derived from the shape, never a second widget:
  //   · one member of an inline-editable type → edit directly in the row;
  //   · one long_text member → row-per-item hosting the long-text editor;
  //   · two-plus members → collapsed title row, expand in place, one at a
  //     time (the schema-field-row idiom). No Done button — the header stays
  //     while open and edits land as typed, the rail's autosave contract.
  import FieldValueEditor from "@/components/widgets/FieldValueEditor.svelte";
  import { dropPositionFromEvent, reorderByPosition } from "@/lib/utils/listOrder";
  import { metadataValueDisplayString } from "@/lib/utils/schemaTypeHelpers";
  import type {
    GroupMember,
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataValue,
    PromptEntrySummary,
    ScopedTag,
    StructureDocument,
  } from "@/lib/types";

  interface Props {
    field: MetadataFieldDefinition;
    value: MetadataValue;
    /** Emits the whole reordered/edited list — the caller persists it like
     *  any other field value. */
    onChange: (value: MetadataValue) => void;
    readOnly?: boolean;
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
    // The candidate rosters a member's entity_ref / tags picker resolves from
    // (ADR-0081) — they are prop-fed and resolved client-side, so a member
    // picker is empty without them. Forwarded verbatim to each member's editor.
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    knownTags?: ScopedTag[];
    tagOrigin?: "project" | "assistant";
    documentKind?: string;
    entryType?: string;
    excludeId?: string | null;
    // ADR-0082 §2/F2, tri-state as of round 2 (P5): forwarded to a member's
    // ReferencePicker verbatim — undefined (the default) means create_missing
    // is not offered. See ReferencePicker for the full rule.
    createLayerId?: string | null | undefined;
  }

  let {
    field,
    value,
    onChange,
    readOnly = false,
    implicitContextMatcher = null,
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    knownTags = [],
    tagOrigin = "project",
    documentKind = "manuscript",
    entryType = "",
    excludeId = null,
    createLayerId = undefined,
  }: Props = $props();

  const members = $derived(field.item_members ?? []);
  /** Scalar sugar → items are bare scalars (flat storage); group shape →
   *  items are records keyed by member key. Reads the resolver's stamped
   *  verdict, never `item_type`: a cross-layer both-keys conflict can leave
   *  item_type set while the group won the tie, and branching on it here
   *  would edit records through scalar inputs (destroying them). */
  const scalarItems = $derived(field.item_scalar === true);

  const INLINE_MEMBER_TYPES = new Set(["text", "number", "select", "color", "boolean"]);
  const density = $derived(
    members.length !== 1 ? "record" : INLINE_MEMBER_TYPES.has(members[0].type) ? "inline" : "longtext",
  );

  const items = $derived(Array.isArray(value) ? (value as MetadataValue[]) : []);

  let openIndex = $state(-1);
  let dragIndex = $state(-1);
  let dropTarget = $state<{ index: number; position: "before" | "after" } | null>(null);

  function memberField(member: GroupMember): MetadataFieldDefinition {
    return {
      name: member.name || member.key,
      type: member.type,
      options: member.options ?? [],
      picker_config: member.picker_config ?? null,
    };
  }

  function isRecord(item: MetadataValue): item is { [key: string]: MetadataValue } {
    return item != null && typeof item === "object" && !Array.isArray(item);
  }

  /** An item that doesn't match the declared shape (a record in a scalar
   *  list, a scalar in a group list — a shape switch left it behind) renders
   *  read-only instead of feeding the wrong editor, which would corrupt it
   *  on the first keystroke. */
  function matchesShape(item: MetadataValue): boolean {
    return scalarItems ? !isRecord(item) : isRecord(item) || item == null;
  }

  function itemMemberValue(item: MetadataValue, member: GroupMember): MetadataValue {
    if (scalarItems) return item;
    return isRecord(item) ? (item[member.key] ?? null) : null;
  }

  function setMemberValue(index: number, member: GroupMember, next: MetadataValue) {
    const copy = items.slice();
    if (scalarItems) {
      copy[index] = next;
    } else {
      const record = isRecord(copy[index]) ? { ...(copy[index] as { [key: string]: MetadataValue }) } : {};
      record[member.key] = next;
      copy[index] = record;
    }
    onChange(copy);
  }

  function addItem() {
    // Capture the new row's index BEFORE onChange: the parent applies the
    // value synchronously, so `items` has already grown by the next line.
    const nextIndex = items.length;
    onChange([...items, scalarItems ? "" : {}]);
    if (density === "record") openIndex = nextIndex;
  }

  function removeItem(index: number) {
    const copy = items.slice();
    copy.splice(index, 1);
    onChange(copy);
    openIndex = -1;
  }

  function dropOn(index: number) {
    const from = dragIndex;
    const position = dropTarget?.position ?? "before";
    dragIndex = -1;
    dropTarget = null;
    if (from < 0 || from === index) return;
    onChange(reorderByPosition(items, from, index, position));
    openIndex = -1;
  }

  // One shared value → string rule (#698): records render as member values
  // joined " · ", never "[object Object]".
  const displayString = metadataValueDisplayString;

  /** Collapsed-row title: the first text-ish member's value (mockup §B). */
  function rowTitle(item: MetadataValue): string {
    const titleMember = members.find((m) => m.type === "text" || m.type === "long_text") ?? members[0];
    return titleMember ? displayString(itemMemberValue(item, titleMember)).trim() : "";
  }

  /** Collapsed-row trail: the other non-empty member values, joined muted. */
  function rowSummary(item: MetadataValue): string {
    const titleMember = members.find((m) => m.type === "text" || m.type === "long_text") ?? members[0];
    return members
      .filter((m) => m !== titleMember)
      .map((m) => displayString(itemMemberValue(item, m)).trim())
      .filter(Boolean)
      .join(" · ");
  }
</script>

{#snippet grip(index: number)}
  {#if !readOnly}
    <span
      class="lv-grip"
      role="presentation"
      draggable="true"
      ondragstart={(event) => {
        dragIndex = index;
        event.dataTransfer?.setData("text/plain", String(index));
      }}
      ondragend={() => {
        dragIndex = -1;
        dropTarget = null;
      }}><i class="ti ti-grip-vertical"></i></span>
  {/if}
{/snippet}

{#snippet removeButton(index: number)}
  {#if !readOnly}
    <button type="button" class="lv-x" aria-label="Remove item" onclick={() => removeItem(index)}>
      <i class="ti ti-x"></i>
    </button>
  {/if}
{/snippet}

<div class="lv" class:read-only={readOnly}>
  {#each items as item, index (index)}
    <div
      class="lv-row"
      class:drop-before={dropTarget?.index === index && dropTarget.position === "before"}
      class:drop-after={dropTarget?.index === index && dropTarget.position === "after"}
      role="group"
      ondragover={(event) => {
        if (readOnly || dragIndex < 0 || dragIndex === index) return;
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
        dropTarget = { index, position: dropPositionFromEvent(event) };
      }}
      ondragleave={() => {
        if (dropTarget?.index === index) dropTarget = null;
      }}
      ondrop={(event) => {
        event.preventDefault();
        dropOn(index);
      }}
    >
      {#if !matchesShape(item)}
        <!-- A shape switch left this item behind (record in a scalar list or
             vice versa): show it read-only rather than feed the wrong editor,
             which would corrupt it on the first keystroke. Remove still works. -->
        <div class="lv-head">
          {@render grip(index)}
          <span class="lv-title lv-mismatch" title="Item doesn't match the field's current item shape">
            {displayString(item) || "untitled"}
          </span>
          {@render removeButton(index)}
        </div>
      {:else if density === "record"}
        <div class="lv-head" class:open={openIndex === index}>
          {@render grip(index)}
          <button
            type="button"
            class="lv-title"
            disabled={readOnly}
            onclick={() => (openIndex = openIndex === index ? -1 : index)}
          >
            {#if rowTitle(item)}{rowTitle(item)}{:else}<span class="lv-untitled">untitled</span>{/if}
            {#if rowSummary(item)}<span class="lv-trail">{rowSummary(item)}</span>{/if}
          </button>
          {@render removeButton(index)}
        </div>
        {#if openIndex === index && !readOnly}
          <div class="lv-edit">
            {#each members as member (member.key)}
              <div class="lv-member">
                <span class="lv-member-name">{member.name || member.key}</span>
                <div class="lv-member-value">
                  <FieldValueEditor
                    field={memberField(member)}
                    value={itemMemberValue(item, member)}
                    onChange={(next) => setMemberValue(index, member, next)}
                    {implicitContextMatcher}
                    {loreEntries}
                    {promptEntries}
                    {structure}
                    {researchStructure}
                    {knownTags}
                    {tagOrigin}
                    {documentKind}
                    {entryType}
                    {excludeId}
                    {createLayerId}
                  />
                </div>
              </div>
            {/each}
          </div>
        {/if}
      {:else}
        <div class="lv-head lv-flat" class:tall={density === "longtext"}>
          {@render grip(index)}
          <div class="lv-member-value">
            <FieldValueEditor
              field={memberField(members[0])}
              value={itemMemberValue(item, members[0])}
              onChange={(next) => setMemberValue(index, members[0], next)}
              {readOnly}
              {implicitContextMatcher}
              {loreEntries}
              {promptEntries}
              {structure}
              {researchStructure}
              {knownTags}
              {tagOrigin}
              {documentKind}
              {entryType}
              {excludeId}
              {createLayerId}
            />
          </div>
          {@render removeButton(index)}
        </div>
      {/if}
    </div>
  {:else}
    {#if readOnly}
      <div class="lv-none">—</div>
    {/if}
  {/each}
  {#if !readOnly}
    <button type="button" class="lv-add" onclick={addItem}>+ Add item</button>
  {/if}
</div>

<style>
  .lv {
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    overflow: hidden;
    min-width: 0;
  }
  .lv.read-only {
    border-style: dashed;
  }
  .lv-row {
    border-bottom: 1px solid var(--divider);
  }
  .lv-row:last-of-type {
    border-bottom: 0;
  }
  /* Edge drop indicators — the same before/after contract every other
     reorderable row surface draws, matching where reorderByPosition inserts. */
  .lv-row.drop-before {
    box-shadow: inset 0 2px 0 var(--accent);
  }
  .lv-row.drop-after {
    box-shadow: inset 0 -2px 0 var(--accent);
  }
  .lv-mismatch {
    color: var(--text-3);
    font-style: italic;
  }
  .lv-head {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 6px;
  }
  .lv-head.tall {
    align-items: flex-start;
  }
  .lv-head.open {
    background: var(--accent-soft);
  }
  .lv-grip {
    color: var(--text-3);
    cursor: grab;
    flex: none;
    display: inline-flex;
    align-items: center;
  }
  .lv-title {
    flex: 1;
    min-width: 0;
    border: 0;
    background: none;
    color: var(--text);
    font: inherit;
    font-size: var(--fs-md);
    text-align: left;
    padding: 2px 0;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .lv-title:disabled {
    cursor: default;
  }
  .lv-untitled {
    color: var(--text-3);
  }
  .lv-trail {
    color: var(--text-3);
    font-size: var(--fs-sm);
    margin-left: 8px;
  }
  .lv-x {
    flex: none;
    border: 0;
    background: none;
    color: var(--text-3);
    cursor: pointer;
    padding: 2px 4px;
    border-radius: 6px;
    visibility: hidden;
  }
  .lv-head:hover .lv-x {
    visibility: visible;
  }
  .lv-x:hover {
    color: var(--danger, var(--text));
    background: var(--inset);
  }
  .lv-edit {
    border-left: 3px solid var(--accent);
    background: var(--accent-soft);
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .lv-member {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }
  .lv-member-name {
    flex: 0 0 92px;
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .lv-member-value {
    flex: 1;
    min-width: 0;
    display: flex;
  }
  .lv-member-value :global(input),
  .lv-member-value :global(textarea) {
    width: 100%;
  }
  .lv-flat {
    padding: 4px 6px;
  }
  .lv-add {
    display: block;
    width: 100%;
    text-align: left;
    border: 0;
    border-top: 1px dashed var(--border);
    background: none;
    color: var(--accent);
    font: inherit;
    font-size: var(--fs-sm);
    padding: 5px 10px;
    cursor: pointer;
  }
  .lv-add:first-child {
    border-top: 0;
  }
  .lv-add:hover {
    background: var(--accent-soft);
  }
  .lv-none {
    color: var(--text-3);
    padding: 4px 8px;
  }
</style>
