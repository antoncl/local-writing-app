<!--
  EntryDraftCard — the "Proposed new entry" review card for a create-mode
  entry-patch brainstorm (ADR-0046 §6.4; generalized to any schema-typed node,
  ADR-0048 §5). A from-scratch draft has no prior state to diff against, so it is
  reviewed WHOLE (title / fields / body), not as a flip: Create runs the kind's
  existing create path, Discard writes nothing. Presentational — the parent
  (ChatBodyView) owns the draft state and the create/discard actions. Extracted
  so ChatBodyView stays under the file-size cap.
-->
<script lang="ts">
  import FieldValue from "@/components/widgets/FieldValue.svelte";
  import type { EntryPatch, MetadataFieldDefinition, MetadataSchema, MetadataValue } from "@/lib/types";

  interface Props {
    draft: EntryPatch;
    dropped: string[];
    metadataSchema: MetadataSchema | null;
    creating: boolean;
    onCreate: () => void;
    onDiscard: () => void;
  }
  let { draft, dropped, metadataSchema, creating, onCreate, onDiscard }: Props = $props();

  // `title` rides in `fields` (the one field the create routes top-level);
  // everything else is metadata shown as a read-only summary.
  let title = $derived(
    typeof draft.fields.title === "string" && draft.fields.title.trim()
      ? draft.fields.title.trim()
      : "(untitled)",
  );
  // Render each proposed value through the canonical FieldValue widget (ADR-0064),
  // so the review reads exactly like the metadata rail — a select as its pill, a
  // boolean as a toggle — never a raw string dump. References are never proposed
  // (ADR-0046), so no ref roster is needed here; a field the schema doesn't define
  // degrades to a plain text display.
  let fieldRows = $derived(
    Object.entries(draft.fields)
      .filter(([id]) => id !== "title")
      .map(([id, value]) => ({
        id,
        label: metadataSchema?.fields?.[id]?.name ?? id,
        field:
          metadataSchema?.fields?.[id] ??
          ({ name: id, type: "text", options: [] } as MetadataFieldDefinition),
        value: value as MetadataValue,
      })),
  );
</script>

<div class="edc-card">
  <header class="edc-head">
    <strong>Proposed new entry</strong>
    <span class="edc-title">{title}</span>
  </header>
  <!-- The head and actions are pinned; only this region scrolls, so a long
       profile can never push "Create entry" off-screen (#1018). -->
  <div class="edc-scroll">
    {#if fieldRows.length > 0}
      <dl class="edc-fields">
        {#each fieldRows as row (row.id)}
          <div class="edc-field">
            <dt>{row.label}</dt>
            <dd><FieldValue field={row.field} value={row.value} ariaLabel={row.label} /></dd>
          </div>
        {/each}
      </dl>
    {/if}
    {#if draft.body}
      <div class="edc-body">{draft.body}</div>
    {/if}
    {#if dropped.length > 0}
      <p class="edc-notice">
        Ignored {dropped.length} field(s) the model couldn't set legally: {dropped.join(", ")}.
      </p>
    {/if}
  </div>
  <div class="edc-actions">
    <button type="button" onclick={onDiscard} disabled={creating}>Discard</button>
    <button type="button" class="primary" onclick={onCreate} disabled={creating}>
      {creating ? "Creating…" : "Create entry"}
    </button>
  </div>
</div>

<style>
  .edc-card {
    display: flex; flex-direction: column; gap: 10px;
    padding: 12px 14px; border-radius: 10px;
    border: 1px solid var(--accent); background: var(--inset);
  }
  /* Only the middle scrolls; head + actions stay pinned so the primary action
     is reachable however long the profile is. The card's min-content is head +
     actions (the scroll collapses to 0), so flex-shrink never clips them. */
  .edc-scroll {
    flex: 1 1 auto; min-height: 0; max-height: 320px; overflow-y: auto;
    display: flex; flex-direction: column; gap: 10px;
  }
  .edc-head { flex: 0 0 auto; display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
  .edc-head strong {
    font-size: var(--fs-xs); font-weight: 600; letter-spacing: 0.07em;
    text-transform: uppercase; color: var(--accent);
  }
  .edc-title { font-size: var(--fs-md); color: var(--text); font-weight: 600; }
  .edc-fields { margin: 0; display: flex; flex-direction: column; gap: 4px; }
  .edc-field { display: flex; gap: 10px; font-size: var(--fs-sm); }
  .edc-field dt {
    flex: 0 0 34%; margin: 0; color: var(--text-3);
    font-size: var(--fs-xs); font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  }
  .edc-field dd { margin: 0; color: var(--text); overflow-wrap: anywhere; }
  .edc-body {
    white-space: pre-wrap;
    font-size: var(--fs-sm); color: var(--text-2);
    padding: 8px 10px; border-radius: 8px; background: var(--surface);
    border: 1px solid var(--divider);
  }
  .edc-notice { margin: 0; font-size: var(--fs-sm); color: var(--text-2); }
  .edc-actions { flex: 0 0 auto; display: flex; justify-content: flex-end; gap: 10px; }
  .edc-actions button {
    padding: 4px 12px; border-radius: var(--r-sm);
    border: 1px solid var(--border); background: var(--surface);
    color: var(--text-2); cursor: pointer; font: inherit; font-size: var(--fs-sm);
  }
  .edc-actions button:hover { background: var(--inset); }
  .edc-actions button[disabled] { opacity: 0.5; cursor: default; }
  .edc-actions button.primary { border-color: var(--accent); color: var(--accent); }
  .edc-actions button.primary:hover {
    background: color-mix(in srgb, var(--accent) 10%, transparent);
  }
</style>
