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
  import type { GroupMember, MetadataFieldDefinition, MetadataValue } from "@/lib/types";

  interface Props {
    field: MetadataFieldDefinition;
    value: MetadataValue;
    /** Emits the whole reordered/edited list — the caller persists it like
     *  any other field value. */
    onChange: (value: MetadataValue) => void;
    readOnly?: boolean;
    implicitContextMatcher?: import("@/lib/editor-core/implicitContextMatcher").CompiledMatcher | null;
  }

  let { field, value, onChange, readOnly = false, implicitContextMatcher = null }: Props = $props();

  const members = $derived(field.item_members ?? []);
  /** item_type sugar → items are bare scalars (flat storage); group shape →
   *  items are records keyed by member key. */
  const scalarItems = $derived(field.item_type != null);

  const INLINE_MEMBER_TYPES = new Set(["text", "number", "select", "color", "boolean"]);
  const density = $derived(
    members.length !== 1 ? "record" : INLINE_MEMBER_TYPES.has(members[0].type) ? "inline" : "longtext",
  );

  const items = $derived(Array.isArray(value) ? (value as MetadataValue[]) : []);

  let openIndex = $state(-1);
  let dragIndex = $state(-1);
  let overIndex = $state(-1);

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
    onChange([...items, scalarItems ? "" : {}]);
    if (density === "record") openIndex = items.length;
  }

  function removeItem(index: number) {
    const copy = items.slice();
    copy.splice(index, 1);
    onChange(copy);
    openIndex = -1;
  }

  function dropOn(index: number) {
    if (dragIndex < 0 || dragIndex === index) return;
    const copy = items.slice();
    const [moved] = copy.splice(dragIndex, 1);
    copy.splice(index, 0, moved);
    onChange(copy);
    openIndex = -1;
  }

  function displayString(v: MetadataValue): string {
    if (v === null || v === undefined) return "";
    if (Array.isArray(v)) return v.map((item) => displayString(item)).join(", ");
    if (typeof v === "object") return "";
    return String(v);
  }

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

<div class="lv" class:read-only={readOnly}>
  {#each items as item, index (index)}
    <div
      class="lv-row"
      class:dragover={overIndex === index}
      role="group"
      ondragover={(event) => {
        if (readOnly || dragIndex < 0) return;
        event.preventDefault();
        overIndex = index;
      }}
      ondragleave={() => {
        if (overIndex === index) overIndex = -1;
      }}
      ondrop={(event) => {
        event.preventDefault();
        overIndex = -1;
        dropOn(index);
      }}
    >
      {#if density === "record"}
        <div class="lv-head" class:open={openIndex === index}>
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
                overIndex = -1;
              }}><i class="ti ti-grip-vertical"></i></span>
          {/if}
          <button
            type="button"
            class="lv-title"
            disabled={readOnly}
            onclick={() => (openIndex = openIndex === index ? -1 : index)}
          >
            {#if rowTitle(item)}{rowTitle(item)}{:else}<span class="lv-untitled">untitled</span>{/if}
            {#if rowSummary(item)}<span class="lv-trail">{rowSummary(item)}</span>{/if}
          </button>
          {#if !readOnly}
            <button type="button" class="lv-x" aria-label="Remove item" onclick={() => removeItem(index)}>
              <i class="ti ti-x"></i>
            </button>
          {/if}
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
                  />
                </div>
              </div>
            {/each}
          </div>
        {/if}
      {:else}
        <div class="lv-head lv-flat" class:tall={density === "longtext"}>
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
                overIndex = -1;
              }}><i class="ti ti-grip-vertical"></i></span>
          {/if}
          <div class="lv-member-value">
            <FieldValueEditor
              field={memberField(members[0])}
              value={itemMemberValue(item, members[0])}
              onChange={(next) => setMemberValue(index, members[0], next)}
              {readOnly}
              {implicitContextMatcher}
            />
          </div>
          {#if !readOnly}
            <button type="button" class="lv-x" aria-label="Remove item" onclick={() => removeItem(index)}>
              <i class="ti ti-x"></i>
            </button>
          {/if}
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
  .lv-row.dragover {
    box-shadow: inset 0 2px 0 var(--accent);
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
  .lv-row:first-of-type + .lv-add,
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
