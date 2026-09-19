<script lang="ts">
  // Body Sections (#2009): every long_text field of the open entry type
  // renders as a headed section stacked directly under the prose body,
  // instead of a rail editor — the rail's own long_text row becomes an index
  // into it (RailFieldRow's `sectionIndex` branch). Rendered by NodeEditor only
  // when `bodyShape === "prose"`. The write path mirrors the rail's own
  // long_text row exactly (MetadataPanel's `writeField`): a plain merge into
  // `metadata` — long_text is never a required select, so there's no
  // key-deletion special case to replicate.
  import type { Editor } from "@tiptap/core";
  import MetadataLongTextEditor from "@/components/widgets/MetadataLongTextEditor.svelte";
  import FieldValue from "@/components/widgets/FieldValue.svelte";
  import { buildBodySections } from "@/lib/editor-core/bodySections";
  import type { SectionRegistry } from "@/lib/editor-core/sectionKeyboardBridge";
  import type { CompiledMatcher } from "@/lib/editor-core/implicitContextMatcher";
  import type { EntryMetadata, MetadataSchema } from "@/lib/types";

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
  }

  let { schema, entryType, metadata, readOnly, onMetadataChange, implicitContextMatcher = null, register }: Props = $props();

  const groups = $derived(buildBodySections(schema, entryType));
  // Registry indices run in document order across every section (1-based —
  // index 0 is the free body), a flat lookup over the schema-ordered groups.
  const orderedIds = $derived(groups.flatMap((g) => g.fields.map((f) => f.id)));
  function sectionIndex(fieldId: string): number {
    return orderedIds.indexOf(fieldId) + 1;
  }

  function writeField(fieldId: string, value: string) {
    onMetadataChange({ ...metadata, [fieldId]: value });
  }

  // "ready" registers by index/fieldId; "destroy" unregisters by the editor's
  // own IDENTITY (never by index/fieldId) — a fast remount can register the
  // NEW instance at the same slot before the OLD one's cleanup runs, and an
  // index-keyed delete there would evict the live registration (#2009 follow-up).
  const mounted = new Map<string, Editor>();
  function handleEditorReady(fieldId: string, editor: Editor, phase: "ready" | "destroy") {
    if (phase === "ready") {
      mounted.set(fieldId, editor);
      register.register(sectionIndex(fieldId), fieldId, editor);
    } else {
      mounted.delete(fieldId);
      register.unregister(editor);
    }
  }
  // A section's document index is not fixed for the life of its editor: a
  // schema edit while the node is open (a long_text field added, reordered
  // or hidden) reshuffles `orderedIds`, so every mounted editor re-registers
  // under its current index — otherwise the bridge would still walk the
  // order the sections had when they mounted.
  $effect(() => {
    void orderedIds;
    for (const [fieldId, editor] of mounted) {
      register.unregister(editor);
      register.register(sectionIndex(fieldId), fieldId, editor);
    }
  });

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
    <section class="bs-block" data-field-section={field.id} id={`section-${field.id}`}>
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
            onEditorReady={(editor, phase) => handleEditorReady(field.id, editor, phase)}
            neighbours={() => register.neighboursFor(sectionIndex(field.id))}
          />
        {/if}
      </div>
    </section>
  {:else}
    <div class="bs-block">
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
                onEditorReady={(editor, phase) => handleEditorReady(field.id, editor, phase)}
                neighbours={() => register.neighboursFor(sectionIndex(field.id))}
              />
            {/if}
          </div>
        </section>
      {/each}
    </div>
  {/if}
{/each}

<style>
  /* Body Sections (#2009): the stack shares the prose body's centred reading
     column, so headed metadata sections read as one continuous page with the
     prose above them — not a second, rail-styled surface. */
  .bs-block {
    max-width: var(--prose-measure);
    margin-inline: auto;
    padding: 0 56px;
  }
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
