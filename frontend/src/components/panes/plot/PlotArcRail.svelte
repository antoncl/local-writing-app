<!--
  PlotArcRail — the plot board's arc palette (ADR-0048 S7 Slice 5a). A collapsible
  rail on PlotEditor where the writer assembles the book's plot *arcs* (template
  instances): add one from a shipped template (snapshotting its beat roster) or a
  blank ad-hoc arc, see each arc's beats, open one to specialize them, or remove it.

  Purely presentational — it imports NOTHING from @xyflow/svelte, so it mounts in
  happy-dom for its render test ([[reference_component_test_harness]]). All data +
  actions arrive as props; PlotEditor wires them to the templateInstances store and
  editorPanes (open / instantiate / create-blank / remove).
-->
<script lang="ts">
  import type { TemplateInstanceSummary, PlotTemplateSummary } from "@/lib/types";
  import { instanceBeats } from "@/lib/plot/instanceBeats";

  let {
    instances,
    templates,
    onOpen,
    onInstantiate,
    onCreateBlank,
    onRemove,
  }: {
    instances: TemplateInstanceSummary[];
    templates: PlotTemplateSummary[];
    onOpen: (id: string) => void;
    onInstantiate: (templateId: string) => void;
    onCreateBlank: () => void;
    onRemove: (id: string) => void;
  } = $props();

  // One arc's beats expand at a time — a glance-first rail; the full editor is a click away.
  let expandedId = $state<string | null>(null);
  function toggleExpand(id: string) {
    expandedId = expandedId === id ? null : id;
  }

  // The "add" menu (blank arc + one entry per shipped template). Closed on an outside
  // pointerdown or Escape while open (the PlotCardNode pattern).
  let addOpen = $state(false);
  let rootEl = $state<HTMLElement | null>(null);
  $effect(() => {
    if (!addOpen) return;
    const onDown = (e: PointerEvent) => {
      if (rootEl && !rootEl.contains(e.target as Node)) addOpen = false;
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") addOpen = false;
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey, true);
    };
  });

  function pickBlank() {
    addOpen = false;
    onCreateBlank();
  }
  function pickTemplate(templateId: string) {
    addOpen = false;
    onInstantiate(templateId);
  }
</script>

<aside class="arc-rail" aria-label="Plot arcs" bind:this={rootEl}>
  <header class="rail-head">
    <span class="rail-title">Arcs</span>
    <div class="add-wrap">
      <button
        class="add-btn"
        aria-label="Add an arc"
        aria-haspopup="menu"
        aria-expanded={addOpen}
        onclick={() => (addOpen = !addOpen)}
      >
        <i class="ti ti-plus" aria-hidden="true"></i>
      </button>
      {#if addOpen}
        <div class="add-menu" role="menu" aria-label="Add an arc">
          <button role="menuitem" class="menu-item" onclick={pickBlank}>
            <i class="ti ti-plus" aria-hidden="true"></i> Blank arc
          </button>
          {#if templates.length}
            <p class="menu-label">From template</p>
            <div class="menu-scroll" role="group" aria-label="Templates">
              {#each templates as template (template.id)}
                <button role="menuitem" class="menu-item" onclick={() => pickTemplate(template.id)}>
                  {template.title}
                </button>
              {/each}
            </div>
          {/if}
        </div>
      {/if}
    </div>
  </header>

  {#if instances.length === 0}
    <p class="rail-empty muted">No arcs yet. Add one from a template, or a blank arc, to start structuring beats.</p>
  {:else}
    <ul class="arc-list">
      {#each instances as instance (instance.id)}
        {@const beats = instanceBeats(instance)}
        {@const isOpen = expandedId === instance.id}
        <li class="arc" class:expanded={isOpen}>
          <div class="arc-row">
            <button
              class="arc-caret"
              aria-label={isOpen ? "Collapse beats" : "Expand beats"}
              aria-expanded={isOpen}
              disabled={beats.length === 0}
              onclick={() => toggleExpand(instance.id)}
            >
              <i class="ti {isOpen ? 'ti-chevron-down' : 'ti-chevron-right'}" aria-hidden="true"></i>
            </button>
            <button class="arc-name" title="Open this arc" onclick={() => onOpen(instance.id)}>
              {instance.title || "Untitled arc"}
            </button>
            <span class="arc-count" title="{beats.length} beats">{beats.length}</span>
            <button class="arc-remove" aria-label="Remove this arc" onclick={() => onRemove(instance.id)}>
              <i class="ti ti-x" aria-hidden="true"></i>
            </button>
          </div>
          {#if isOpen && beats.length}
            <ol class="beat-list">
              {#each beats as beat, i (beat.id ?? i)}
                <li class="beat">{beat.title || "Untitled beat"}</li>
              {/each}
            </ol>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}
</aside>

<style>
  .arc-rail {
    display: flex;
    flex-direction: column;
    width: 240px;
    min-width: 240px;
    height: 100%;
    min-height: 0;
    border-right: 1px solid var(--border-strong);
    background: var(--panel);
    overflow: hidden;
  }
  .rail-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--sp-2);
    padding: var(--sp-1) var(--sp-2);
    border-bottom: 1px solid var(--border);
  }
  .rail-title {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
  }
  .add-wrap {
    position: relative;
  }
  .add-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 2px 6px;
    border: 1px solid var(--border-strong);
    border-radius: var(--r-sm);
    background: var(--surface);
    color: var(--text-2);
    cursor: pointer;
  }
  .add-btn:hover {
    color: var(--text);
  }
  .add-menu {
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    z-index: 5;
    min-width: 200px;
    display: flex;
    flex-direction: column;
    padding: 4px;
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-md);
    box-shadow: var(--elev-2);
  }
  .menu-label {
    margin: 4px 8px 2px;
    font-size: var(--fs-xs);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-3);
  }
  .menu-scroll {
    display: flex;
    flex-direction: column;
    max-height: 220px;
    overflow-y: auto;
  }
  .menu-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px;
    border: none;
    background: transparent;
    color: var(--text);
    font-size: var(--fs-sm);
    text-align: left;
    border-radius: var(--r-sm);
    cursor: pointer;
  }
  .menu-item:hover {
    background: var(--surface);
  }
  .menu-item i {
    color: var(--text-3);
  }
  .rail-empty {
    padding: var(--sp-2);
    line-height: 1.4;
  }
  .muted {
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
  .arc-list {
    list-style: none;
    margin: 0;
    padding: 4px;
    overflow-y: auto;
    min-height: 0;
  }
  .arc {
    border-radius: var(--r-sm);
  }
  .arc-row {
    display: flex;
    align-items: center;
    gap: 2px;
    padding: 2px;
  }
  .arc-caret {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 2px;
    border: none;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
  }
  .arc-caret:disabled {
    opacity: 0.3;
    cursor: default;
  }
  .arc-name {
    flex: 1;
    min-width: 0;
    text-align: left;
    border: none;
    background: transparent;
    color: var(--text);
    font-size: var(--fs-sm);
    padding: 2px 0;
    cursor: pointer;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .arc-name:hover {
    text-decoration: underline;
  }
  .arc-count {
    flex: 0 0 auto;
    min-width: 18px;
    text-align: center;
    font-size: var(--fs-xs);
    color: var(--text-3);
    background: var(--surface);
    border-radius: var(--r-pill);
    padding: 0 5px;
  }
  .arc-remove {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 2px;
    border: none;
    background: transparent;
    color: var(--text-3);
    border-radius: var(--r-sm);
    cursor: pointer;
    opacity: 0;
  }
  .arc-row:hover .arc-remove,
  .arc-remove:focus-visible {
    opacity: 1;
  }
  .arc-remove:hover {
    color: var(--text);
    background: var(--surface);
  }
  .beat-list {
    list-style: none;
    margin: 0 0 4px;
    padding: 0 4px 0 26px;
  }
  .beat {
    font-size: var(--fs-xs);
    color: var(--text-2);
    padding: 2px 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
</style>
