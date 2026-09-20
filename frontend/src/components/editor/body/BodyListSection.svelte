<script lang="ts">
  // Body List Section (#2043): one `list` field whose item shape carries a
  // long_text member, rendered as a repeating body section — a heading, then
  // one sub-section per item (its title member renamed in place, its other
  // scalar members as rail rows via BodyItemRows, its long_text members as
  // stacked MetadataLongTextEditors). Storage is unchanged: every write is a
  // whole-array `on.change`, mirroring ListValueEditor's own add/remove/
  // reorder recipe (index-based, `reorderByPosition`/`dropPositionFromEvent`).
  import { tick } from "svelte";
  import type { Editor } from "@tiptap/core";
  import MetadataLongTextEditor from "@/components/widgets/MetadataLongTextEditor.svelte";
  import FieldValue from "@/components/widgets/FieldValue.svelte";
  import BodyItemRows from "@/components/editor/body/BodyItemRows.svelte";
  import { listItemEditorId, type BodyListSection } from "@/lib/editor-core/bodySections";
  import { dropPositionFromEvent, reorderByPosition } from "@/lib/utils/listOrder";
  import type { SectionRegistry } from "@/lib/editor-core/sectionKeyboardBridge";
  import type { CompiledMatcher } from "@/lib/editor-core/implicitContextMatcher";
  import type { GroupMember } from "@/lib/schemaTypes";
  import type {
    DocumentKind,
    LoreEntrySummary,
    MetadataFieldDefinition,
    MetadataSchema,
    MetadataValue,
    NavigateTarget,
    PromptEntrySummary,
    StructureDocument,
  } from "@/lib/types";

  interface Model {
    section: BodyListSection;
    items: MetadataValue[];
    readOnly: boolean;
    schema: MetadataSchema;
    entryType: string;
    documentKind: DocumentKind;
    /** "compact" (#2043 slice 3): the plot board hosts the same section inside a
     *  node, at node scale — smaller heading type, no outer gutter/measure. */
    density?: "prose" | "compact";
  }
  interface Deps {
    register: SectionRegistry;
    sectionIndex: (editorId: string) => number;
    implicitContextMatcher: CompiledMatcher | null;
    loreEntries: LoreEntrySummary[];
    promptEntries: PromptEntrySummary[];
    structure: StructureDocument | null;
    researchStructure: StructureDocument | null;
    excludeId: string | null;
    createLayerId: string | null;
    tagTitleById: ReadonlyMap<string, string>;
  }
  interface Callbacks {
    change: (items: MetadataValue[]) => void;
    editorReady: (editorId: string, editor: Editor, phase: "ready" | "destroy") => void;
    navigate: (payload: NavigateTarget) => void;
  }

  interface Props {
    model: Model;
    deps: Deps;
    on: Callbacks;
  }

  let { model, deps, on }: Props = $props();

  const items = $derived(model.items);
  const n = $derived(items.length);

  function recordOf(item: MetadataValue): Record<string, MetadataValue> {
    return item != null && typeof item === "object" && !Array.isArray(item) ? (item as Record<string, MetadataValue>) : {};
  }
  function memberValue(item: MetadataValue, key: string): MetadataValue {
    return recordOf(item)[key] ?? null;
  }
  function stringOf(v: MetadataValue): string {
    return typeof v === "string" ? v : "";
  }
  function titleOf(item: MetadataValue): string {
    return model.section.titleKey ? stringOf(memberValue(item, model.section.titleKey)) : "";
  }
  function memberField(member: GroupMember): MetadataFieldDefinition {
    return {
      name: member.name || member.key,
      type: member.type,
      options: member.options ?? [],
      picker_config: member.picker_config ?? null,
    } as MetadataFieldDefinition;
  }

  function writeMember(index: number, key: string, value: MetadataValue) {
    const copy = items.slice();
    copy[index] = { ...recordOf(copy[index]), [key]: value };
    on.change(copy);
  }
  function clearMember(index: number, key: string) {
    const copy = items.slice();
    const record = { ...recordOf(copy[index]) };
    delete record[key];
    copy[index] = record;
    on.change(copy);
  }

  function addItem() {
    on.change([...items, {}]);
  }
  function removeItem(index: number) {
    const copy = items.slice();
    copy.splice(index, 1);
    on.change(copy);
  }

  let rootEl = $state<HTMLElement | null>(null);

  async function itemKeydown(e: KeyboardEvent, index: number) {
    if ((e.ctrlKey || e.metaKey) && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
      e.preventDefault();
      // The title input commits on `change` (blur/Enter), so a reorder mid-
      // edit carries the uncommitted title along instead of dropping it: the
      // array is rebuilt from the input's live value, then reordered, in ONE
      // write (a write-then-reorder pair would reorder the stale prop).
      const typed = (e.currentTarget as HTMLInputElement).value;
      const current = items.slice();
      if (model.section.titleKey && typed !== titleOf(items[index])) {
        current[index] = { ...recordOf(current[index]), [model.section.titleKey]: typed };
      }
      let refocus: number | null = null;
      if (e.key === "ArrowUp" && index > 0) {
        on.change(reorderByPosition(current, index, index - 1, "before"));
        refocus = index - 1;
      } else if (e.key === "ArrowDown" && index < items.length - 1) {
        on.change(reorderByPosition(current, index, index + 1, "after"));
        refocus = index + 1;
      }
      if (refocus !== null) {
        await tick();
        rootEl?.querySelector<HTMLElement>(`[data-list-item="${model.section.id}:${refocus}"] .bs-item-title`)?.focus();
      }
      return;
    }
    if (e.key === "Escape") {
      const target = e.currentTarget as HTMLInputElement;
      target.value = titleOf(items[index]);
      target.blur();
    }
  }

  // Drag-to-reorder (mirrors ListValueEditor's index-based recipe).
  let dragIndex = $state(-1);
  let dropTarget = $state<{ index: number; position: "before" | "after" } | null>(null);

  function startDrag(e: DragEvent, index: number) {
    dragIndex = index;
    e.dataTransfer?.setData("text/plain", String(index));
    if (e.dataTransfer) e.dataTransfer.effectAllowed = "move";
  }
  function endDrag() {
    dragIndex = -1;
    dropTarget = null;
  }
  function dragOver(e: DragEvent, index: number) {
    if (dragIndex < 0 || dragIndex === index) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
    dropTarget = { index, position: dropPositionFromEvent(e) };
  }
  function dragLeave(index: number) {
    if (dropTarget?.index === index) dropTarget = null;
  }
  function drop(e: DragEvent, index: number) {
    e.preventDefault();
    const from = dragIndex;
    const position = dropTarget?.position ?? "before";
    dragIndex = -1;
    dropTarget = null;
    if (from >= 0 && from !== index) on.change(reorderByPosition(items, from, index, position));
  }
</script>

<section
  class="bs-block bs-list"
  class:compact={model.density === "compact"}
  id={model.density === "compact" ? undefined : `section-${model.section.id}`}
  data-field-section={model.section.id}
  bind:this={rootEl}
>
  <!-- The `id={`section-…`}` anchor is the editor document's Go-to target
       (RailFieldRow's "Go to …" jump / the arrow-bridge focus). A board node
       (compact density) hosts the SAME section as the NodeEditor body, so it
       must not shadow that anchor with a second element carrying the same id. -->
  <h2 class="bs-h2">
    {model.section.label}
    <span class="bs-caption">list · {n} {n === 1 ? "item" : "items"}</span>
    {#if !model.readOnly}
      <button type="button" class="bs-add" aria-label={`Add ${model.section.label} item`} onclick={addItem}>+</button>
    {/if}
  </h2>
  {#each items as item, index (index)}
    <section
      class="bs-item"
      class:drop-before={dropTarget?.index === index && dropTarget.position === "before"}
      class:drop-after={dropTarget?.index === index && dropTarget.position === "after"}
      data-list-item={`${model.section.id}:${index}`}
      role="group"
      ondragover={(e) => dragOver(e, index)}
      ondrop={(e) => drop(e, index)}
      ondragleave={() => dragLeave(index)}
    >
      <h3 class="bs-h3 bs-item-head">
        <span class="bs-ord">{index + 1}</span>
        {#if model.section.titleKey && !model.readOnly}
          <input
            class="bs-item-title"
            type="text"
            aria-label={`${model.section.label} ${index + 1} title`}
            value={titleOf(item)}
            onchange={(e) => writeMember(index, model.section.titleKey!, e.currentTarget.value)}
            onkeydown={(e) => itemKeydown(e, index)}
          />
        {:else}
          <span class="bs-item-title-text">{titleOf(item) || `Item ${index + 1}`}</span>
        {/if}
        {#if !model.readOnly}
          <span class="bs-item-ops">
            <span
              class="bs-drag"
              draggable="true"
              title="Drag to reorder"
              aria-hidden="true"
              ondragstart={(e) => startDrag(e, index)}
              ondragend={endDrag}
            >⋮⋮</span>
            <button type="button" class="bs-remove" aria-label={`Remove item ${index + 1}`} onclick={() => removeItem(index)}>×</button>
          </span>
        {/if}
      </h3>
      {#if model.section.factMembers.length > 0}
        <BodyItemRows
          model={{
            members: model.section.factMembers,
            record: recordOf(item),
            readOnly: model.readOnly,
            schema: model.schema,
            entryType: model.entryType,
            documentKind: model.documentKind,
            itemKey: `${model.section.id}:${index}`,
          }}
          deps={{
            loreEntries: deps.loreEntries,
            promptEntries: deps.promptEntries,
            structure: deps.structure,
            researchStructure: deps.researchStructure,
            implicitContextMatcher: deps.implicitContextMatcher,
            excludeId: deps.excludeId,
            createLayerId: deps.createLayerId,
            tagTitleById: deps.tagTitleById,
          }}
          on={{
            write: (k, v) => writeMember(index, k, v),
            clear: (k) => clearMember(index, k),
            navigate: on.navigate,
          }}
        />
      {/if}
      {#each model.section.proseMembers as member (member.key)}
        <h4 class="bs-h4">{member.name || member.key}</h4>
        <div class="bs-body">
          {#if model.readOnly}
            <FieldValue field={memberField(member)} value={memberValue(item, member.key)} ariaLabel={member.name} />
          {:else}
            <MetadataLongTextEditor
              ariaLabel={`${model.section.label} ${index + 1} ${member.name}`}
              value={stringOf(memberValue(item, member.key))}
              matcher={deps.implicitContextMatcher}
              onChange={(v) => writeMember(index, member.key, v)}
              onEditorReady={(editor, phase) => on.editorReady(listItemEditorId(model.section.id, index, member.key), editor, phase)}
              neighbours={() => deps.register.neighboursFor(deps.sectionIndex(listItemEditorId(model.section.id, index, member.key)))}
            />
          {/if}
        </div>
      {/each}
    </section>
  {/each}
  {#if !model.readOnly}
    <button type="button" class="bs-add-item" onclick={addItem}>+ Add item</button>
  {/if}
</section>

<style>
  .bs-block {
    width: 100%;
    max-width: var(--prose-measure);
    margin-inline: auto;
    padding: 0 56px;
    box-sizing: border-box;
  }
  .bs-h2 {
    margin: var(--sp-4) 0 var(--sp-2);
    padding-top: var(--sp-3);
    border-top: 1px solid var(--divider);
    font-family: var(--serif);
    font-size: var(--fs-xl);
    font-weight: 400;
    color: var(--text);
    display: flex;
    align-items: baseline;
    gap: var(--sp-2);
  }
  .bs-h3 {
    margin: var(--sp-3) 0 var(--sp-1);
    font-family: var(--serif);
    font-size: var(--fs-lg);
    font-weight: 400;
    color: var(--text);
  }
  .bs-caption {
    margin-left: var(--sp-2);
    font-family: var(--sans);
    font-size: var(--fs-xs);
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-3);
  }
  .bs-body {
    margin-top: var(--sp-1);
  }
  .bs-add {
    margin-left: auto;
    background: none;
    border: 0;
    color: var(--text-3);
    font-size: var(--fs-md);
    cursor: pointer;
  }
  .bs-add:hover {
    color: var(--accent-emphasis);
  }
  .bs-item-head {
    display: flex;
    align-items: baseline;
    gap: var(--sp-2);
  }
  .bs-ord {
    font-family: var(--mono);
    font-size: var(--fs-xs);
    color: var(--text-3);
    min-width: 1.4em;
  }
  .bs-item-title {
    flex: 1 1 auto;
    min-width: 0;
    background: none;
    border: 0;
    border-bottom: 1px solid transparent;
    font: inherit;
    color: inherit;
    padding: 0;
  }
  .bs-item-title:focus {
    outline: none;
    border-bottom-color: var(--accent-emphasis);
  }
  .bs-item-ops {
    margin-left: auto;
    display: inline-flex;
    gap: var(--sp-1);
    color: var(--text-3);
    opacity: 0;
  }
  .bs-item-head:hover .bs-item-ops,
  .bs-item-head:focus-within .bs-item-ops {
    opacity: 1;
  }
  .bs-drag {
    cursor: grab;
    letter-spacing: -0.1em;
  }
  .bs-remove {
    background: none;
    border: 0;
    color: var(--text-3);
    cursor: pointer;
    font: inherit;
  }
  .bs-remove:hover {
    color: var(--danger);
  }
  .bs-h4 {
    margin: var(--sp-2) 0 var(--sp-1);
    font-family: var(--sans);
    font-size: var(--fs-xs);
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--text-3);
  }
  .bs-item.drop-before {
    box-shadow: inset 0 2px 0 var(--accent-emphasis);
  }
  .bs-item.drop-after {
    box-shadow: inset 0 -2px 0 var(--accent-emphasis);
  }
  .bs-add-item {
    display: block;
    margin: var(--sp-3) 0 0;
    background: none;
    border: 0;
    padding: 0;
    color: var(--text-3);
    font-size: var(--fs-md);
    cursor: pointer;
  }
  .bs-add-item:hover {
    color: var(--text-2);
  }

  /* Compact density (#2043 slice 3): a board node hosts this same section at
     node scale — no outer gutter/measure, smaller heading type. */
  .bs-block.compact {
    padding: 0;
    max-width: none;
    margin: 0;
  }
  .bs-block.compact .bs-h2 {
    margin: var(--sp-2) 0 var(--sp-1);
    padding-top: var(--sp-2);
    font-size: var(--fs-md);
  }
  .bs-block.compact .bs-h3 {
    margin: var(--sp-2) 0 0;
    font-size: var(--fs-sm);
  }
  .bs-block.compact .bs-add,
  .bs-block.compact .bs-add-item {
    font-size: var(--fs-sm);
  }
  .bs-block.compact :global(.metadata-long-text-body) {
    font-size: var(--fs-sm);
    min-height: calc(1.65 * var(--fs-sm));
  }
</style>
