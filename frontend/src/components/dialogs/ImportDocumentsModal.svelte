<script lang="ts">
  // "Import documents" (#635). The home for adopting loose scene files — Markdown
  // dropped into the project's scenes/ folder that no manuscript node references.
  // Split out of the Validate result panel: rare (≈once per project start), so it
  // lives behind an app-menu action, not on the daily surface. Controlled — the
  // host supplies the loose list and owns the import call; this owns only the
  // per-item selection.
  import type { LooseScene } from "@/lib/types";
  import Modal from "@/components/dialogs/Modal.svelte";

  let {
    open = false,
    looseScenes = [],
    busy = false,
    onClose = () => {},
    onImport = () => {},
  }: {
    open?: boolean;
    looseScenes?: LooseScene[];
    busy?: boolean;
    onClose?: () => void;
    onImport?: (sceneIds: string[]) => void;
  } = $props();

  const allLooseIds = $derived(looseScenes.map((doc) => doc.id));

  // Selection is local, everything ticked by default (the common case is "take
  // them all"). Seed only on the open TRANSITION — a legacy `$:` reruns on every
  // dependency change, so gating on `if (open)` alone would re-seed whenever
  // `looseScenes` is reassigned (the post-import refresh), silently re-selecting
  // what the user deselected (#639). `seededFor` makes it fire once per open.
  let selected = $state<Set<string>>(new Set());
  let seededFor = $state(false);
  $effect(() => {
    if (!open) seededFor = false;
  });
  $effect(() => {
    if (open && !seededFor) {
      selected = new Set(allLooseIds);
      seededFor = true;
    }
  });

  // Keep the selection scoped to what's still loose: after a partial import the
  // imported ids leave `looseScenes`, so drop them. This only REMOVES ids, never
  // adds, so it can't undo a deselection (unlike a reseed) — and it keeps
  // `selected` authoritative, so the count and payload read straight off it.
  $effect(() => {
    if ([...selected].some((id) => !allLooseIds.includes(id))) {
      const stillLoose = new Set(allLooseIds);
      selected = new Set([...selected].filter((id) => stillLoose.has(id)));
    }
  });

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selected = next;
  }

  const allSelected = $derived(looseScenes.length > 0 && selected.size === looseScenes.length);

  function toggleAll() {
    selected = allSelected ? new Set() : new Set(allLooseIds);
  }
</script>

{#if open}
  <Modal
    title="Import documents"
    label="Import documents"
    frameClass="import-documents-modal"
    frameStyle="--modal-width: min(520px, calc(100vw - 48px)); --modal-max-height: calc(100vh - 120px); --modal-overflow-y: auto;"
  >
    {#if looseScenes.length === 0}
      <p class="muted">
        No documents to import. Drop Markdown (<code>.md</code>) files into this
        project's <code>scenes/</code> folder, then reopen this.
      </p>
    {:else}
      <p class="muted">
        {looseScenes.length === 1
          ? "1 document in scenes/ isn't in the manuscript yet."
          : `${looseScenes.length} documents in scenes/ aren't in the manuscript yet.`}
        Pick which to add.
      </p>
      <label class="select-all">
        <input type="checkbox" checked={allSelected} onchange={toggleAll} />
        Select all
      </label>
      <ul class="doc-list">
        {#each looseScenes as doc (doc.id)}
          <li>
            <label class="doc-row">
              <input type="checkbox" checked={selected.has(doc.id)} onchange={() => toggle(doc.id)} />
              <span class="doc-title">{doc.title}</span>
              <span class="doc-file">{doc.filename}</span>
            </label>
          </li>
        {/each}
      </ul>
    {/if}

    {#snippet actions()}
      <button type="button" onclick={onClose}>{looseScenes.length === 0 ? "Close" : "Cancel"}</button>
      {#if looseScenes.length > 0}
        <button
          class="primary"
          type="button"
          disabled={busy || selected.size === 0}
          onclick={() => onImport([...selected])}
        >{busy ? "Importing…" : `Add ${selected.size} to manuscript`}</button>
      {/if}
    {/snippet}
  </Modal>
{/if}

<style>
  .select-all {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: var(--fs-sm);
    color: var(--text-2);
  }

  .select-all input,
  .doc-row input {
    width: auto;
    flex: none;
    margin: 0;
  }

  .doc-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 2px;
    border: 1px solid var(--border);
    border-radius: 6px;
  }

  .doc-list li + li {
    border-top: 1px solid var(--divider);
  }

  .doc-row {
    display: flex;
    align-items: baseline;
    gap: 8px;
    padding: 6px 10px;
    cursor: pointer;
    font-size: var(--fs-md);
  }

  .doc-title {
    color: var(--text);
  }

  .doc-file {
    margin-left: auto;
    color: var(--text-3);
    font-family: var(--mono);
    font-size: var(--fs-sm);
  }

  /* The frame class sits on Modal's own element (child scope), so the anchor
     must be :global; the `code` it styles is this dialog's slotted content. */
  :global(.import-documents-modal) code {
    font-family: var(--mono);
    font-size: var(--fs-sm);
    background: var(--inset);
    padding: 1px 5px;
    border-radius: 3px;
  }
</style>
