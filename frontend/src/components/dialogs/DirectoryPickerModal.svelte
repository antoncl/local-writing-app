<script lang="ts">
  // Folder picker modal — used by the "Open folder…" + "Override
  // folder…" flows. Lifted out of App.svelte to keep the main pane file
  // tractable. The parent owns navigation state (directoryListing,
  // loading) and the side effects (loadDirectory, useDirectory); this
  // component is presentation + dispatch.
  import type { DirectoryListing } from "@/lib/types";

  export let open: boolean = false;
  export let listing: DirectoryListing | null = null;
  export let loading: boolean = false;
  export let onClose: () => void = () => {};
  // Pass null to go up one level (consumer derives parent_path from
  // the current listing).
  export let onNavigate: (path: string | undefined | null) => void = () => {};
  export let onSelect: (path: string) => void = () => {};
</script>

{#if open}
  <section class="directory-modal-backdrop" aria-label="Choose project folder">
    <div class="directory-modal">
      <header class="directory-modal-header">
        <div>
          <h2>Choose Project Folder</h2>
          <p>{listing?.path ?? "Loading folders..."}</p>
        </div>
        <button type="button" on:click={onClose}>Cancel</button>
      </header>

      <div class="directory-modal-actions">
        <button type="button" disabled={!listing?.parent_path || loading} on:click={() => onNavigate(listing?.parent_path)}>
          Up
        </button>
        <button class="primary" type="button" disabled={!listing || loading} on:click={() => listing && onSelect(listing.path)}>
          Select This Folder
        </button>
      </div>

      <div class="directory-modal-list">
        {#if loading}
          <p class="muted">Loading folders...</p>
        {:else if listing}
          {#each listing.directories as directory}
            <button type="button" class="directory-row" on:click={() => onNavigate(directory.path)} title={directory.path}>
              {directory.name}
            </button>
          {/each}
          {#if listing.directories.length === 0}
            <p class="muted">No folders here.</p>
          {/if}
        {/if}
      </div>
    </div>
  </section>
{/if}

<style>
  .directory-row {
    display: block;
    width: 100%;
    min-height: 32px;
    overflow: hidden;
    text-align: left;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* The directory picker can be opened FROM another modal (the New Project
     modal's "Override folder…" button), so its backdrop must sit ABOVE the
     plain modal backdrop or the parent modal blocks all interaction. */
  .directory-modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 2200;
    display: grid;
    place-items: center;
    padding: 24px;
    background: var(--scrim);
  }

  .directory-modal {
    display: grid;
    grid-template-rows: auto auto minmax(0, 1fr);
    gap: 12px;
    width: min(680px, calc(100vw - 48px));
    height: min(560px, calc(100vh - 48px));
    padding: 16px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    box-shadow: var(--elev-3);
  }

  .directory-modal-header {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 12px;
    align-items: start;
  }

  .directory-modal-header p {
    margin: 4px 0 0;
    overflow: hidden;
    color: var(--text-2);
    font-size: var(--fs-md);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .directory-modal-actions {
    display: flex;
    gap: 8px;
  }

  .directory-modal-list {
    min-height: 0;
    overflow: auto;
    padding: 2px;
    border: 1px solid var(--divider);
    border-radius: 6px;
    background: var(--surface);
  }

  .directory-modal-list .directory-row {
    margin-bottom: 5px;
  }

  .directory-modal-list .directory-row:last-child {
    margin-bottom: 0;
  }
</style>
