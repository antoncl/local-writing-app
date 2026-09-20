<script lang="ts">
  // Body Sections (#2009): every long_text field of the open entry type
  // renders as a headed section stacked directly under the prose body,
  // instead of a rail editor — the rail's own long_text row becomes an index
  // into it (RailFieldRow's `sectionIndex` branch). Rendered by NodeEditor only
  // when `bodyShape === "prose"`. The write path mirrors the rail's own
  // long_text row exactly (MetadataPanel's `writeField`): a plain merge into
  // `metadata` — long_text is never a required select, so there's no
  // key-deletion special case to replicate.
  //
  // #2043: a `list` field whose item shape carries a long_text member is
  // material too — it renders AFTER the long_text sections above, one
  // BodyListSection per field, one sub-section per item.
  import { untrack } from "svelte";
  import MetadataLongTextEditor from "@/components/widgets/MetadataLongTextEditor.svelte";
  import FieldValue from "@/components/widgets/FieldValue.svelte";
  import BodyListSection from "@/components/editor/body/BodyListSection.svelte";
  import { buildBodySections, buildBodyListSections, listItemEditorId, listItemsOf } from "@/lib/editor-core/bodySections";
  import { createSectionEditorRoster } from "@/lib/editor-core/sectionEditorRoster.svelte";
  import type { SectionRegistry } from "@/lib/editor-core/sectionKeyboardBridge";
  import type { CompiledMatcher } from "@/lib/editor-core/implicitContextMatcher";
  import type {
    DocumentKind,
    EntryMetadata,
    LoreEntrySummary,
    MetadataSchema,
    MetadataValue,
    NavigateTarget,
    PromptEntrySummary,
    StructureDocument,
  } from "@/lib/types";

  interface Props {
    schema: MetadataSchema | null;
    entryType: string;
    metadata: EntryMetadata;
    readOnly: boolean;
    onMetadataChange: (next: EntryMetadata) => void;
    implicitContextMatcher?: CompiledMatcher | null;
    // The keyboard-bridge registry NodeEditor owns (#2009 D): every section
    // editor registers into it (document order 1.. — index 0 is the free
    // body, registered by NodeEditor itself) so ArrowUp/Down/Left/Right at a
    // section's edge moves the caret into its neighbour, and the rail's index
    // row can jump straight to one by field id.
    register: SectionRegistry;
    // #2043: context BodyListSection's item rows need — a list item's rows are
    // a node editor in miniature, so they need the same collaborators as any
    // rail row. Defaulted so every call site that predates list sections keeps
    // compiling untouched.
    documentKind?: DocumentKind;
    loreEntries?: LoreEntrySummary[];
    promptEntries?: PromptEntrySummary[];
    structure?: StructureDocument | null;
    researchStructure?: StructureDocument | null;
    excludeId?: string | null;
    createLayerId?: string | null;
    tagTitleById?: ReadonlyMap<string, string>;
    onNavigate?: (payload: NavigateTarget) => void;
  }

  let {
    schema,
    entryType,
    metadata,
    readOnly,
    onMetadataChange,
    implicitContextMatcher = null,
    register,
    documentKind = "lore",
    loreEntries = [],
    promptEntries = [],
    structure = null,
    researchStructure = null,
    excludeId = null,
    createLayerId = null,
    tagTitleById = new Map(),
    onNavigate = () => {},
  }: Props = $props();

  const groups = $derived(buildBodySections(schema, entryType));
  const listSections = $derived(buildBodyListSections(schema, entryType));
  const listItems = (listId: string) => listItemsOf(metadata, listId);
  // Registry indices run in document order across every section (1-based —
  // index 0 is the free body), a flat lookup over the schema-ordered groups
  // followed by every list item's own prose members.
  const orderedIds = $derived([
    ...groups.flatMap((g) => g.fields.map((f) => f.id)),
    ...listSections.flatMap((list) =>
      listItems(list.id).flatMap((_, index) => list.proseMembers.map((member) => listItemEditorId(list.id, index, member.key))),
    ),
  ]);
  // `register` is a prop (never reassigned across the life of this component — the host
  // creates it once), so `untrack` here just documents that this reads its INITIAL value
  // rather than tracking it reactively (`state_referenced_locally`); the roster keeps
  // calling into the same registry instance either way.
  const roster = createSectionEditorRoster(untrack(() => register), () => orderedIds);

  function writeField(fieldId: string, value: string) {
    onMetadataChange({ ...metadata, [fieldId]: value });
  }

  // MetadataLongTextEditor's `value` is a plain string; `metadata[id]` is the
  // wider `MetadataValue` (a long_text field only ever stores a string or is
  // absent, but the type doesn't know that).
  function stringValue(fieldId: string): string {
    const v = metadata[fieldId];
    return typeof v === "string" ? v : "";
  }
</script>

{#each groups as group (group.group ?? group.fields[0].id)}
  {#if group.group === null}
    {@const field = group.fields[0]}
    <section class="bs-block prose-column" data-field-section={field.id} id={`section-${field.id}`}>
      <h2 class="bs-h2">{field.label} <span class="bs-caption">long text</span></h2>
      <div class="bs-body">
        {#if readOnly}
          <!-- `groups` is only non-empty once `buildBodySections` has resolved a
               schema, so `schema` is guaranteed set here. -->
          <FieldValue field={schema!.fields[field.id]} value={metadata[field.id]} ariaLabel={field.label} />
        {:else}
          <MetadataLongTextEditor
            ariaLabel={field.label}
            value={stringValue(field.id)}
            matcher={implicitContextMatcher}
            onChange={(v) => writeField(field.id, v)}
            onEditorReady={(editor, phase) => roster.editorReady(field.id, editor, phase)}
            neighbours={() => register.neighboursFor(roster.sectionIndex(field.id))}
          />
        {/if}
      </div>
    </section>
  {:else}
    <div class="bs-block prose-column">
      <h2 class="bs-h2">{group.label} <span class="bs-caption">group</span></h2>
      {#each group.fields as field (field.id)}
        <section class="bs-field" data-field-section={field.id} id={`section-${field.id}`}>
          <h3 class="bs-h3">{field.label} <span class="bs-caption">long text</span></h3>
          <div class="bs-body">
            {#if readOnly}
              <FieldValue field={schema!.fields[field.id]} value={metadata[field.id]} ariaLabel={field.label} />
            {:else}
              <MetadataLongTextEditor
                ariaLabel={field.label}
                value={stringValue(field.id)}
                matcher={implicitContextMatcher}
                onChange={(v) => writeField(field.id, v)}
                onEditorReady={(editor, phase) => roster.editorReady(field.id, editor, phase)}
                neighbours={() => register.neighboursFor(roster.sectionIndex(field.id))}
              />
            {/if}
          </div>
        </section>
      {/each}
    </div>
  {/if}
{/each}

{#each listSections as list (list.id)}
  <BodyListSection
    model={{ section: list, items: listItems(list.id), readOnly, schema: schema!, entryType, documentKind }}
    deps={{ register, sectionIndex: roster.sectionIndex, implicitContextMatcher, loreEntries, promptEntries, structure, researchStructure, excludeId, createLayerId, tagTitleById }}
    on={{ change: (items) => onMetadataChange({ ...metadata, [list.id]: items }), editorReady: roster.editorReady, navigate: onNavigate }}
  />
{/each}

<style>
  /* Body Sections (#2009): the stack shares the prose body's centred reading
     column, so headed metadata sections read as one continuous page with the
     prose above them — not a second, rail-styled surface. The column itself
     (measure, gutter, prose font so `ch` resolves alike, #2049) is the shared
     `.prose-column` rule in styles.css (#2051); the block adds nothing. */
  .bs-field {
    display: block;
  }
  .bs-h2 {
    margin: var(--sp-4) 0 var(--sp-2);
    padding-top: var(--sp-3);
    border-top: 1px solid var(--divider);
    font-family: var(--serif);
    font-size: var(--fs-xl);
    font-weight: 400;
    color: var(--text);
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
</style>
