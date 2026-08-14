<!--
  OfferOnPicker — the "Show in ＋New on…" authoring control for a chat_panel
  prompt (ADR-0054 §4 / S4b, reworked in #903). Writes the instance-level
  `offer_on` allow-list: the subject entry_types on which this prompt is offered
  as a ＋New conversation in a node's Conversations panel (read back by
  `promptEntriesOfferedOn`).

  A thin shell over the shared schema→is-a-tree traversal (`buildTree`, via
  `offerOnTree.ts`) — the same engine the context picker uses — but with offer_on's
  own model: it stores EXACT ids and matches is-a at read time, so checking a
  parent (e.g. lore's root) covers its descendants, which then render disabled as
  "covered." Only conversation-host subjects are offered (all lore; the scene and
  plot-card subtrees), so no dead targets. Mounted by CodeBodyView ONLY for a
  chat_panel prompt (the gate lives in the host).

  `offer_on` is bind:'d to the parent (NodeEditor's offerOnDraft) so the parent's
  save logic owns serialization; `onChange` fires the pane's emitChange.
-->
<script lang="ts">
  import type { MetadataSchema } from "@/lib/types";
  import { offerOnRows, selectTarget, deselectTarget, type OfferOnRow } from "./offerOnTree";

  interface Props {
    metadataSchema: MetadataSchema | null;
    // Persisted shape (bind:'d by the parent) — exact entry_type ids.
    offerOn?: string[];
    // Locked for a built-in Library prompt (the host also wraps us in `inert`).
    readOnly?: boolean;
    // Outbound: the allow-list changed → parent emits its change/save.
    onChange?: () => void;
  }

  let {
    metadataSchema = null,
    offerOn = $bindable([]),
    readOnly = false,
    onChange,
  }: Props = $props();

  const rows = $derived(offerOnRows(metadataSchema, offerOn));
  // Count the directly-chosen host targets, not the raw array — so a stale
  // non-host id left by an older picker (which renders no row) can't inflate the
  // badge, and a parent "all" target counts as one, not once per covered child.
  const selectedCount = $derived(rows.filter((row) => row.state === "checked").length);

  // Native checkboxes have no `indeterminate` attribute — set it imperatively.
  // Mirrors NodePickerConfigEditor's action so the tri-state parent reads right.
  function indeterminateBinding(node: HTMLInputElement, value: boolean) {
    node.indeterminate = value;
    return {
      update(next: boolean) {
        node.indeterminate = next;
      },
    };
  }

  function toggle(row: OfferOnRow): void {
    // "covered" rows are offered via an ancestor — not independently editable.
    if (readOnly || row.state === "covered") return;
    offerOn =
      row.state === "checked"
        ? deselectTarget(offerOn, row.id)
        : selectTarget(offerOn, metadataSchema, row.id);
    onChange?.();
  }
</script>

<details class="offer-on-editor">
  <summary>
    Show in ＋New <small>{selectedCount}</small>
    <small class="offer-on-hint">the subjects this conversation is offered on · checking a group covers its types</small>
  </summary>
  {#if rows.length === 0}
    <p class="muted offer-on-empty">No subject types defined yet.</p>
  {:else}
    <div class="offer-on-tree" role="group" aria-label="Show in ＋New on">
      {#each rows as row (row.id)}
        <label
          class="offer-on-row"
          class:covered={row.state === "covered"}
          style="--depth: {row.depth}"
          title={row.id}
        >
          <input
            type="checkbox"
            checked={row.state === "checked" || row.state === "covered"}
            use:indeterminateBinding={row.state === "indeterminate"}
            disabled={readOnly || row.state === "covered"}
            onchange={() => toggle(row)}
          />
          <span class="offer-on-row-name" class:root={row.depth === 0}>{row.name}</span>
        </label>
      {/each}
    </div>
  {/if}
</details>

<style>
  /* Mirrors EntryInputsEditor's disclosure chrome so the two prompt sidecars
     read as a set (same inset panel, summary weight, hint colour). */
  .offer-on-editor {
    padding: 6px 12px;
    background: var(--inset);
    border-top: 1px solid var(--border);
    font-size: var(--fs-md);
  }
  .offer-on-editor[open] {
    max-height: 40vh;
    overflow-y: auto;
  }
  .offer-on-editor > summary {
    cursor: pointer;
    user-select: none;
    font-weight: 600;
    color: var(--text);
    display: flex;
    align-items: baseline;
    gap: 6px;
  }
  .offer-on-editor > summary > small {
    color: var(--text-3);
    font-weight: 400;
  }
  .offer-on-hint {
    margin-left: auto;
    font-size: var(--fs-xs);
    text-align: right;
  }
  .offer-on-empty {
    margin: 6px 0;
    font-size: var(--fs-sm);
  }
  .offer-on-tree {
    margin: 6px 0 2px;
  }
  /* Left-aligned, scannable rows; hierarchy shown by indent (depth). The raw
     entry_type id lives in the row `title`, not a chip — the human name carries
     the row. */
  .offer-on-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 6px;
    padding-left: calc(6px + var(--depth) * 18px);
    border-radius: 4px;
    cursor: pointer;
    font-size: var(--fs-sm);
    color: var(--text);
  }
  .offer-on-row:hover {
    background: var(--surface);
  }
  /* The global `input, select { width: 100% }` (styles.css) would blow a bare
     checkbox out to full width and shove the label off the right edge — reset it
     to a natural-size native control. */
  .offer-on-row > input[type="checkbox"] {
    flex: none;
    width: auto;
    min-width: 0;
    margin: 0;
    padding: 0;
    border: none;
    background: none;
    box-shadow: none;
    accent-color: var(--accent);
  }
  .offer-on-row-name.root {
    font-weight: 600;
  }
  /* A type covered by a checked ancestor: on, but not independently editable. */
  .offer-on-row.covered {
    cursor: default;
    color: var(--text-3);
  }
  .offer-on-row.covered:hover {
    background: transparent;
  }
</style>
