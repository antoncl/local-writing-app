<script lang="ts">
  // Folder picker modal — used by the "Open folder…" + "Override
  // folder…" flows. Lifted out of App.svelte to keep the main pane file
  // tractable. The parent owns navigation state (directoryListing,
  // loading) and the side effects (loadDirectory, useDirectory); this
  // component is presentation + dispatch.
  import type { DirectoryListing } from "./types";

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
