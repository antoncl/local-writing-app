<script lang="ts">
  import { createEventDispatcher, onMount } from "svelte";
  import { api } from "./api";
  import NodePickerConfigEditor from "./NodePickerConfigEditor.svelte";
  import type { MetadataSchema, NodePickerConfig, TagUsage } from "./types";

  export let metadataSchema: MetadataSchema | null = null;

  const dispatch = createEventDispatcher<{ changed: void; close: void }>();

  let tags: TagUsage[] = [];
  let filter = "";
  let error = "";
  let busy = false;

  // Merge selection (tag names) + target name.
  let selected = new Set<string>();
  let mergeTarget = "";
  // Scope editor: the tag whose scope is being edited + a working copy.
  let scopeEditing: string | null = null;
  let scopeDraft: NodePickerConfig = { kinds: [], entry_types: {} };

  $: filtered = filter.trim()
    ? tags.filter((tag) => tag.name.toLowerCase().includes(filter.trim().toLowerCase()))
    : tags;
  $: selectedNames = tags.filter((tag) => selected.has(tag.name)).map((tag) => tag.name);

  async function load() {
    busy = true;
    error = "";
    try {
      tags = (await api.getTagsOverview()).tags;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }
  onMount(load);

  function toggleSelect(name: string) {
    const next = new Set(selected);
    if (next.has(name)) next.delete(name);
    else next.add(name);
    selected = next;
  }

  function scopeChips(scope: NodePickerConfig): string[] {
    const kinds = scope.kinds ?? [];
    const entryTypes = scope.entry_types ?? {};
    if (kinds.length === 0 && Object.keys(entryTypes).length === 0) return ["everywhere"];
    const chips: string[] = [];
    for (const kind of kinds) {
      const subs = entryTypes[kind];
      if (subs && subs.length) chips.push(`${kind}: ${subs.join(", ")}`);
      else chips.push(`${kind} · all`);
    }
    return chips;
  }

  function openScope(tag: TagUsage) {
    scopeEditing = tag.name;
    scopeDraft = {
      kinds: [...(tag.scope.kinds ?? [])],
      entry_types: { ...(tag.scope.entry_types ?? {}) },
    };
  }

  async function saveScope(name: string) {
    busy = true;
    error = "";
    try {
      await api.updateTagScope(name, scopeDraft);
      scopeEditing = null;
      await load();
      dispatch("changed");
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }

  async function doMerge() {
    if (selectedNames.length === 0 || !mergeTarget.trim()) return;
    busy = true;
    error = "";
    try {
      await api.mergeTags(selectedNames, mergeTarget.trim());
      selected = new Set();
      mergeTarget = "";
      await load();
      dispatch("changed");
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }
</script>

<div class="gm-backdrop" on:mousedown={() => dispatch("close")}>
  <div class="gm-dialog tm-dialog" role="dialog" aria-label="Tags" on:mousedown|stopPropagation>
    <header class="gm-head">
      <i class="ti ti-tag" aria-hidden="true"></i>
      <h2>Tags</h2>
      <span class="tm-count">{tags.length}</span>
      <input class="tm-filter" placeholder="Filter tags…" bind:value={filter} />
      <button class="gm-close" type="button" on:click={() => dispatch("close")}>Close</button>
    </header>

    {#if error}<p class="gm-error">{error}</p>{/if}

    {#if selectedNames.length >= 1}
      <div class="tm-merge-bar">
        <i class="ti ti-arrow-merge" aria-hidden="true"></i>
        <span class="tm-merge-label">Merge {selectedNames.length} into</span>
        <input class="tm-merge-target" placeholder="new name" bind:value={mergeTarget} />
        <span class="tm-merge-note">uses migrate · scopes union</span>
        <span class="sfi-spacer"></span>
        <button class="sfi-cancel" type="button" on:click={() => (selected = new Set())}>Clear</button>
        <button class="sfi-done" type="button" disabled={busy || !mergeTarget.trim()} on:click={doMerge}>Merge</button>
      </div>
    {/if}

    <div class="gm-body tm-body">
      {#if filtered.length === 0}
        <p class="muted">{busy ? "Loading…" : "No tags."}</p>
      {/if}
      {#each filtered as tag (tag.name)}
        <div class="tm-row" class:sel={selected.has(tag.name)}>
          <button
            class="tm-check"
            class:on={selected.has(tag.name)}
            type="button"
            aria-label={`Select ${tag.name}`}
            on:click={() => toggleSelect(tag.name)}
          >
            {#if selected.has(tag.name)}<i class="ti ti-check" aria-hidden="true"></i>{/if}
          </button>
          <span class="tm-name">{tag.name}</span>
          <span class="tm-uses">{tag.count} use{tag.count === 1 ? "" : "s"}</span>
          <span class="tm-scopes">
            {#each scopeChips(tag.scope) as chip}
              <span class="tm-scope-chip">{chip}</span>
            {/each}
          </span>
          <button class="tm-cog" type="button" aria-label={`Edit scope for ${tag.name}`} on:click={() => openScope(tag)}>
            <i class="ti ti-settings" aria-hidden="true"></i>
          </button>
        </div>
        {#if scopeEditing === tag.name}
          <div class="tm-scope-editor">
            <span class="lbl">Suggest on</span>
            <NodePickerConfigEditor
              mode="field"
              config={scopeDraft}
              metadataSchema={metadataSchema}
              on:change={(event) => (scopeDraft = event.detail.config)}
            />
            <div class="sfi-footer">
              <span class="sfi-spacer"></span>
              <button class="sfi-cancel" type="button" on:click={() => (scopeEditing = null)}>Cancel</button>
              <button class="sfi-done" type="button" disabled={busy} on:click={() => saveScope(tag.name)}>Save scope</button>
            </div>
          </div>
        {/if}
      {/each}
    </div>
  </div>
</div>

<style>
  .gm-backdrop {
    position: fixed;
    inset: 0;
    z-index: 200;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(20, 30, 27, 0.32);
  }
  .gm-dialog {
    width: 560px;
    max-width: calc(100vw - 40px);
    max-height: calc(100vh - 80px);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border: 1px solid var(--border-strong, #b4c2bc);
    border-radius: 14px;
    background: var(--surface, #fff);
    box-shadow: 0 20px 60px rgba(20, 40, 35, 0.28);
  }
  .gm-head {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--divider, #e2e8e5);
    background: var(--panel, #edf3f1);
  }
  .gm-head h2 {
    margin: 0;
    font-family: Newsreader, Georgia, serif;
    font-size: 18px;
    font-weight: 600;
  }
  .tm-count {
    padding: 1px 9px;
    border-radius: 999px;
    border: 1px solid var(--border, #cbd6d2);
    background: var(--surface, #fff);
    font-size: 12px;
    color: var(--text-2, #4d5753);
  }
  .tm-filter {
    margin-left: auto;
    width: 150px;
    padding: 5px 9px;
    border: 1px solid var(--border, #cbd6d2);
    border-radius: 8px;
    font-size: 13px;
  }
  .gm-close {
    padding: 5px 11px;
    border: 1px solid var(--border, #cbd6d2);
    border-radius: 8px;
    background: var(--surface, #fff);
    font-size: 12.5px;
    cursor: pointer;
  }
  .gm-error {
    margin: 0;
    padding: 9px 16px;
    background: #fdeceb;
    color: #b4453a;
    font-size: 12.5px;
  }
  .tm-merge-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 9px 16px;
    background: var(--accent-soft, #edf6f2);
    border-bottom: 1px solid var(--accent-soft2, #dff0ea);
    color: var(--accent-strong, #234e43);
  }
  .tm-merge-label {
    font-size: 12.5px;
    font-weight: 600;
  }
  .tm-merge-target {
    width: 160px;
    padding: 5px 9px;
    border: 1px solid var(--border, #cbd6d2);
    border-radius: 8px;
    font-size: 13px;
  }
  .tm-merge-note {
    font-size: 11px;
    color: var(--text-2, #4d5753);
  }
  .gm-body {
    overflow: auto;
  }
  .tm-row {
    display: flex;
    align-items: center;
    gap: 11px;
    padding: 9px 16px;
    border-bottom: 1px solid var(--divider, #e2e8e5);
  }
  .tm-row.sel {
    background: var(--accent-soft, #edf6f2);
  }
  .tm-check {
    flex: none;
    width: 18px;
    height: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border-strong, #b4c2bc);
    border-radius: 5px;
    background: var(--surface, #fff);
    color: #fff;
    font-size: 12px;
    cursor: pointer;
  }
  .tm-check.on {
    background: var(--accent, #2f6f5e);
    border-color: var(--accent, #2f6f5e);
  }
  .tm-name {
    font-size: 13px;
    font-weight: 600;
    color: var(--text, #242424);
  }
  .tm-uses {
    font-size: 11.5px;
    color: var(--text-3, #74817b);
  }
  .tm-scopes {
    margin-left: auto;
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .tm-scope-chip {
    padding: 1px 8px;
    border-radius: 999px;
    border: 1px solid var(--divider, #e2e8e5);
    background: var(--inset, #f1f5f3);
    font-size: 11px;
    color: var(--text-2, #4d5753);
  }
  .tm-cog {
    flex: none;
    border: 0;
    background: transparent;
    color: var(--text-3, #74817b);
    font-size: 15px;
    cursor: pointer;
  }
  .tm-cog:hover {
    color: var(--accent, #2f6f5e);
  }
  .tm-scope-editor {
    display: flex;
    flex-direction: column;
    gap: 9px;
    padding: 12px 16px 14px 41px;
    background: var(--inset, #f1f5f3);
    border-bottom: 1px solid var(--divider, #e2e8e5);
    box-shadow: inset 3px 0 0 0 var(--accent, #2f6f5e);
  }
  .lbl {
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--text-3, #74817b);
  }
  .sfi-footer {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .sfi-spacer {
    flex: 1;
  }
  .sfi-cancel {
    padding: 6px 12px;
    border: 1px solid var(--border, #cbd6d2);
    border-radius: 8px;
    background: var(--surface, #fff);
    font-size: 12.5px;
    cursor: pointer;
  }
  .sfi-done {
    padding: 6px 14px;
    border: 1px solid var(--accent, #2f6f5e);
    border-radius: 8px;
    background: var(--accent, #2f6f5e);
    color: #fff;
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
  }
  .sfi-done:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .muted {
    padding: 16px;
    font-size: 13px;
    color: var(--text-3, #74817b);
  }
</style>
