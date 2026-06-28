<script lang="ts">
  // "New project" modal. Owns the bound inputs (name + optional parent
  // override path) and emits intent via callbacks. The parent still
  // hosts the underlying state so `Cancel` / `Create` flows aren't
  // bound to the modal lifecycle (e.g. opening the directory picker
  // mid-flow keeps the name typed so far).

  export let open: boolean = false;
  export let name: string = "";
  export let overrideFolder: boolean = false;
  export let overridePath: string = "";
  export let resolvedPath: string = "";
  export let defaultProjectsFolder: string = "";
  export let onClose: () => void = () => {};
  export let onSubmit: () => void = () => {};
  export let onOpenOverrideFolderPicker: () => void = () => {};
  // The "(open Settings)" link in the no-default-folder hint.
  export let onOpenSettings: () => void = () => {};
  // Toggle override off (revert to default folder).
  export let onClearOverride: () => void = () => {};

  import Modal from "./Modal.svelte";

  function handleNameKeydown(event: KeyboardEvent) {
    if (event.key === "Enter") void onSubmit();
  }

  $: submitDisabled =
    !name.trim() || (overrideFolder ? !overridePath.trim() : !defaultProjectsFolder);
</script>

{#if open}
  <Modal title="New Project" label="New project">
      <label>
        Project name
        <input
          type="text"
          bind:value={name}
          placeholder="Honor's First Command"
          on:keydown={handleNameKeydown}
        />
      </label>

      {#if !overrideFolder}
        <p class="muted">
          Will be created at:
          <code>{name.trim() ? resolvedPath : (defaultProjectsFolder || "(no default folder set)")}</code>
        </p>
        {#if !defaultProjectsFolder}
          <p class="muted">
            No default projects folder set — open <button type="button" class="inline-link" on:click={() => { onClose(); onOpenSettings(); }}>Settings</button> to set one, or override below.
          </p>
        {/if}
        <div class="button-row">
          <button type="button" on:click={onOpenOverrideFolderPicker}>Override folder…</button>
        </div>
      {:else}
        <label>
          Parent folder
          <div class="path-picker-row">
            <input type="text" bind:value={overridePath} placeholder="C:\path\to\writing" />
            <button type="button" on:click={onOpenOverrideFolderPicker}>Browse…</button>
          </div>
        </label>
        <p class="muted">
          Will be created at: <code>{name.trim() ? resolvedPath : "(enter a name)"}</code>
        </p>
        <div class="button-row">
          <button type="button" on:click={onClearOverride}>Use default folder</button>
        </div>
      {/if}

      {#snippet actions()}
        <button type="button" on:click={onClose}>Cancel</button>
        <button
          class="primary"
          type="button"
          disabled={submitDisabled}
          on:click={onSubmit}
        >Create</button>
      {/snippet}
  </Modal>
{/if}
