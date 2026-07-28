<!--
  LoreDraftCard — the "Proposed new entry" review card for a create-mode lore
  brainstorm (ADR-0046 §6.4). A from-scratch draft has no prior state to diff
  against, so it is reviewed WHOLE (title / fields / body), not as a flip:
  Create runs the existing create path, Discard writes nothing. Presentational
  — the parent (ChatBodyView) owns the draft state and the create/discard
  actions. Extracted so ChatBodyView stays under the file-size cap.
-->
<script lang="ts">
  import type { EntryPatch, MetadataSchema } from "@/lib/types";

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
  let fieldRows = $derived(
    Object.entries(draft.fields)
      .filter(([id]) => id !== "title")
      .map(([id, value]) => ({
        id,
        label: metadataSchema?.fields?.[id]?.name ?? id,
        value: Array.isArray(value) ? value.join(", ") : String(value ?? ""),
      })),
  );
</script>

<div class="ldc-card">
  <header class="ldc-head">
    <strong>Proposed new entry</strong>
    <span class="ldc-title">{title}</span>
  </header>
  {#if fieldRows.length > 0}
    <dl class="ldc-fields">
      {#each fieldRows as row (row.id)}
        <div class="ldc-field">
          <dt>{row.label}</dt>
          <dd>{row.value || "—"}</dd>
        </div>
      {/each}
    </dl>
  {/if}
  {#if draft.body}
    <div class="ldc-body">{draft.body}</div>
  {/if}
  {#if dropped.length > 0}
    <p class="ldc-notice">
      Ignored {dropped.length} field(s) the model couldn't set legally: {dropped.join(", ")}.
    </p>
  {/if}
  <div class="ldc-actions">
    <button type="button" onclick={onDiscard} disabled={creating}>Discard</button>
    <button type="button" class="primary" onclick={onCreate} disabled={creating}>
      {creating ? "Creating…" : "Create entry"}
    </button>
  </div>
</div>

<style>
  .ldc-card {
    display: flex; flex-direction: column; gap: 10px;
    padding: 12px 14px; border-radius: 10px;
    border: 1px solid var(--accent); background: var(--inset);
  }
  .ldc-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
  .ldc-head strong {
    font-size: var(--fs-xs); font-weight: 800; letter-spacing: 0.07em;
    text-transform: uppercase; color: var(--accent);
  }
  .ldc-title { font-size: var(--fs-md); color: var(--text); font-weight: 600; }
  .ldc-fields { margin: 0; display: flex; flex-direction: column; gap: 4px; }
  .ldc-field { display: flex; gap: 10px; font-size: var(--fs-sm); }
  .ldc-field dt {
    flex: 0 0 34%; margin: 0; color: var(--text-3);
    font-size: var(--fs-xs); font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  }
  .ldc-field dd { margin: 0; color: var(--text); overflow-wrap: anywhere; }
  .ldc-body {
    max-height: 200px; overflow-y: auto; white-space: pre-wrap;
    font-size: var(--fs-sm); color: var(--text-2);
    padding: 8px 10px; border-radius: 8px; background: var(--surface);
    border: 1px solid var(--divider);
  }
  .ldc-notice { margin: 0; font-size: var(--fs-sm); color: var(--text-2); }
  .ldc-actions { display: flex; justify-content: flex-end; gap: 10px; }
  .ldc-actions button {
    padding: 4px 12px; border-radius: var(--r-sm);
    border: 1px solid var(--border); background: var(--surface);
    color: var(--text-2); cursor: pointer; font: inherit; font-size: var(--fs-sm);
  }
  .ldc-actions button:hover { background: var(--inset); }
  .ldc-actions button[disabled] { opacity: 0.5; cursor: default; }
  .ldc-actions button.primary { border-color: var(--accent); color: var(--accent); }
  .ldc-actions button.primary:hover {
    background: color-mix(in srgb, var(--accent) 10%, transparent);
  }
</style>
