<script lang="ts">
  // The one folder picker (#530, slice P). Shared by the open-project flow (via
  // projectChooser, mounted in App), the create wizard (its own instance), and
  // Machine Settings' projects-root field. Unlike the old click-walker, it is
  // self-contained: it owns its transient *browse* state (the listing, the
  // drive/home roots, the typed path) and talks to the backend itself, then
  // hands the host a chosen path via `onSelect`. Domain state — what to DO with
  // that path — stays with the caller.
  //
  // It keeps its own high-z backdrop rather than the shared Modal, because it
  // opens FROM other modals (New Project, Machine Settings) and must sit above
  // them.
  import { api } from "@/lib/api";
  import type { DirectoryListing, DirectoryRoot, PathProbe } from "@/lib/types";

  export let open: boolean = false;
  export let initialPath: string = "";
  export let title: string = "Choose Folder";
  export let selectLabel: string = "Select This Folder";
  export let onClose: () => void = () => {};
  export let onSelect: (path: string) => void = () => {};
  // Open-project only (#441): refuse a folder outside the machine projects
  // root — books must live under it. Left false by the create and choose-root
  // pickers, which legitimately browse anywhere. The backend decides
  // membership (`listing.within_root`); this just governs the gesture.
  export let enforceWithinRoot: boolean = false;

  let listing: DirectoryListing | null = null;
  let roots: DirectoryRoot[] = [];
  let loading = false;
  let error: string | null = null;

  // The editable path field, kept in sync with the shown folder on navigate.
  let typedPath = "";
  let probe: PathProbe | null = null;
  let probeTimer: ReturnType<typeof setTimeout> | null = null;

  let showCreate = false;
  let newFolderName = "";
  let createError: string | null = null;

  // Load roots + the start folder on the closed→open transition only.
  let wasOpen = false;
  $: if (open && !wasOpen) {
    wasOpen = true;
    void handleOpen();
  } else if (!open && wasOpen) {
    wasOpen = false;
  }

  async function handleOpen() {
    error = null;
    showCreate = false;
    newFolderName = "";
    createError = null;
    probe = null;
    if (roots.length === 0) {
      try {
        roots = await api.listDirectoryRoots();
      } catch {
        roots = [];
      }
    }
    await navigate(initialPath.trim() || undefined);
  }

  async function navigate(path?: string) {
    loading = true;
    error = null;
    createError = null;
    try {
      listing = await api.listDirectories(path);
      typedPath = listing.path;
      probe = null;
    } catch (err) {
      error = err instanceof Error ? err.message : "That folder could not be opened.";
    } finally {
      loading = false;
    }
  }

  function onTypedInput() {
    if (probeTimer) clearTimeout(probeTimer);
    const value = typedPath.trim();
    if (!value) {
      probe = null;
      return;
    }
    probeTimer = setTimeout(async () => {
      try {
        probe = await api.probeDirectory(value);
      } catch {
        probe = null;
      }
    }, 250);
  }

  function goToTyped() {
    const value = typedPath.trim();
    if (value) void navigate(value);
  }

  function toggleCreate() {
    showCreate = !showCreate;
    createError = null;
    newFolderName = "";
  }

  async function submitCreate() {
    const name = newFolderName.trim();
    createError = null;
    if (!name || !listing) return;
    try {
      const entry = await api.createDirectory(listing.path, name);
      showCreate = false;
      newFolderName = "";
      await navigate(entry.path);
    } catch (err) {
      createError = err instanceof Error ? err.message : "That folder could not be created.";
    }
  }

  // Outside the machine projects root, in a picker that enforces it: the shown
  // folder can't be opened (#441). Drives the message + the dimmed Select.
  $: outOfRoot = enforceWithinRoot && listing !== null && !listing.within_root;

  function select() {
    if (listing && !outOfRoot) onSelect(listing.path);
  }

  // Split an absolute path into clickable breadcrumb segments, handling
  // Windows drives (`C:\a\b`), UNC shares (`\\server\share\a`), and POSIX
  // (`/a/b`) roots. Every crumb's `path` must be a real navigable location.
  type Crumb = { label: string; path: string };
  function crumbsFor(path: string): Crumb[] {
    if (!path) return [];
    const isWindows = /^[A-Za-z]:/.test(path) || path.includes("\\");
    if (isWindows) {
      const win = path.replace(/\//g, "\\");
      // UNC: the root crumb is the whole `\\server\share`, not `server`.
      if (win.startsWith("\\\\")) {
        const segs = win.slice(2).split("\\").filter((p) => p.length > 0);
        if (segs.length >= 2) {
          let acc = `\\\\${segs[0]}\\${segs[1]}`;
          const out: Crumb[] = [{ label: acc, path: acc }];
          segs.slice(2).forEach((part) => {
            acc = `${acc}\\${part}`;
            out.push({ label: part, path: acc });
          });
          return out;
        }
      }
      const parts = win.split("\\").filter((p) => p.length > 0);
      const out: Crumb[] = [];
      let acc = "";
      parts.forEach((part, i) => {
        acc = i === 0 ? `${part}\\` : `${acc.replace(/\\+$/, "")}\\${part}`;
        out.push({ label: part, path: acc });
      });
      return out;
    }
    const parts = path.split("/").filter((p) => p.length > 0);
    const out: Crumb[] = [{ label: "/", path: "/" }];
    let acc = "";
    parts.forEach((part) => {
      acc = `${acc}/${part}`;
      out.push({ label: part, path: acc });
    });
    return out;
  }

  $: crumbs = listing ? crumbsFor(listing.path) : [];

  // Only trust the probe hint when it describes the path currently in the
  // field — a debounced reply for a superseded keystroke is ignored.
  $: probeMatches = probe !== null && probe.input === typedPath.trim();

  // Focus the create-folder field when it appears, without the `autofocus`
  // attribute (which svelte-check flags for a11y).
  function focusOnMount(node: HTMLElement) {
    node.focus();
  }
</script>

{#if open}
  <section class="directory-modal-backdrop" aria-label={title}>
    <div class="directory-modal">
      <header class="directory-modal-header">
        <h2>{title}</h2>
        <button type="button" on:click={onClose}>Cancel</button>
      </header>

      {#if roots.length > 0}
        <div class="directory-roots" role="group" aria-label="Jump to">
          {#each roots as root}
            <button
              type="button"
              class="root-chip"
              title={root.path}
              on:click={() => navigate(root.path)}
            >{root.label}</button>
          {/each}
        </div>
      {/if}

      <nav class="directory-crumbs" aria-label="Current path">
        {#each crumbs as crumb, i}
          <button type="button" class="crumb" title={crumb.path} on:click={() => navigate(crumb.path)}
            >{crumb.label}</button>
          {#if i < crumbs.length - 1}<span class="crumb-sep" aria-hidden="true">›</span>{/if}
        {/each}
      </nav>

      <div class="path-picker-row directory-path-row">
        <input
          type="text"
          aria-label="Folder path"
          spellcheck="false"
          bind:value={typedPath}
          on:input={onTypedInput}
          on:keydown={(e) => e.key === "Enter" && goToTyped()}
          placeholder="Type or paste a folder path"
        />
        <button type="button" on:click={toggleCreate}>New Folder…</button>
      </div>

      {#if typedPath.trim() && probeMatches && !probe?.is_dir}
        <p class="directory-hint danger">Not a folder on disk.</p>
      {:else if probeMatches && probe?.is_project}
        <p class="directory-hint">This folder already holds a project.</p>
      {/if}

      {#if showCreate}
        <div class="path-picker-row directory-create-row">
          <input
            type="text"
            aria-label="New folder name"
            spellcheck="false"
            bind:value={newFolderName}
            use:focusOnMount
            on:keydown={(e) => e.key === "Enter" && submitCreate()}
            placeholder="New folder name"
          />
          <button class="primary" type="button" disabled={!newFolderName.trim()} on:click={submitCreate}>Create</button>
        </div>
        {#if createError}<p class="directory-hint danger">{createError}</p>{/if}
      {/if}

      <div class="directory-modal-list">
        {#if loading}
          <p class="muted">Loading folders…</p>
        {:else if error}
          <p class="directory-hint danger">{error}</p>
        {:else if listing}
          {#each listing.directories as directory}
            <button type="button" class="directory-row" on:click={() => navigate(directory.path)} title={directory.path}>
              <span class="directory-row-name">{directory.name}</span>
              {#if directory.is_project}
                <span class="directory-tag is-project">project</span>
              {:else if directory.is_empty}
                <span class="directory-tag is-empty">empty</span>
              {/if}
            </button>
          {/each}
          {#if listing.directories.length === 0}
            <p class="muted">No folders here.</p>
          {/if}
        {/if}
      </div>

      <footer class="directory-modal-actions">
        <button type="button" disabled={!listing?.parent_path || loading} on:click={() => navigate(listing?.parent_path ?? undefined)}>
          Up
        </button>
        {#if outOfRoot}
          <span class="directory-hint inline danger">Outside your projects folder — books must live inside it.</span>
        {:else if listing?.is_project}
          <span class="directory-hint inline">Already a project</span>
        {/if}
        <span class="directory-actions-spacer"></span>
        <button class="primary" type="button" disabled={!listing || loading || outOfRoot} on:click={select}>
          {selectLabel}
        </button>
      </footer>
    </div>
  </section>
{/if}

<style>
  .directory-row {
    display: flex;
    gap: 8px;
    align-items: center;
    width: 100%;
    min-height: 32px;
    text-align: left;
  }

  .directory-row-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .directory-tag {
    flex: none;
    padding: 1px 7px;
    border-radius: 999px;
    font-size: var(--fs-xs);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .directory-tag.is-project {
    color: var(--accent-deep);
    background: color-mix(in oklab, var(--accent-deep) 12%, transparent);
  }

  .directory-tag.is-empty {
    color: var(--text-3);
    background: color-mix(in oklab, var(--text-3) 10%, transparent);
  }

  /* The directory picker can be opened FROM another modal (New Project's
     "Override folder…" button, Machine Settings' "Browse…"), so its backdrop
     must sit ABOVE the plain modal backdrop or the parent modal blocks all
     interaction. */
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
    grid-template-rows: auto auto auto auto auto minmax(0, 1fr) auto;
    gap: 10px;
    width: min(680px, calc(100vw - 48px));
    height: min(600px, calc(100vh - 48px));
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
    align-items: center;
  }

  .directory-modal-header h2 {
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .directory-roots {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .root-chip {
    padding: 2px 10px;
    border: 1px solid var(--border);
    border-radius: 999px;
    font-size: var(--fs-sm);
    color: var(--text-2);
  }

  .directory-crumbs {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 2px;
    min-height: 24px;
  }

  .crumb {
    padding: 1px 6px;
    border: none;
    border-radius: 4px;
    background: transparent;
    font-size: var(--fs-sm);
    color: var(--accent-deep);
    cursor: pointer;
  }

  .crumb:hover {
    background: color-mix(in oklab, var(--accent-deep) 10%, transparent);
  }

  .crumb-sep {
    color: var(--text-3);
    font-size: var(--fs-sm);
  }

  .directory-hint {
    margin: 0;
    font-size: var(--fs-sm);
    color: var(--text-2);
  }

  .directory-hint.danger {
    color: var(--danger);
  }

  .directory-hint.inline {
    align-self: center;
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

  .directory-modal-actions {
    display: flex;
    gap: 8px;
    align-items: center;
  }

  .directory-actions-spacer {
    flex: 1;
  }
</style>
