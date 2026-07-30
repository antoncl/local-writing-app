<script lang="ts">
  // The govern-from-the-"+" surface (#247, slice 2 PR-1, generalized in PR-3).
  // The + popover is where you browse the roster while tagging, so it *is* the
  // lightweight governance surface: each row adds the tag (click the name) and,
  // one hover away, governs it (the ⋯ opens Suggest-on / Rename / Merge).
  //
  // Origin-agnostic: which vocabulary this governs (project tags — per-layer,
  // scoped — or assistant tags — flat, machine-global, NO scope) is injected as
  // an `adapter`, never branched on here. `adapter.supportsScope` is the one
  // presentation difference — assistant tags hide "Suggest on…" and their scope
  // chips. Rename is a single-source merge to a (new) name; both go through
  // `adapter.merge`.
  //
  // After a rename/merge/scope the backend rewrites tag values across documents
  // on disk, so `adapter.reconcile()` bumps App's one vocabulary-revision signal
  // (roster + entry lists + open-editor baselines) and we reload our use-counts.
  import { onMount } from "svelte";
  import NodePickerConfigEditor from "@/components/schema/NodePickerConfigEditor.svelte";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import { pickerMembership } from "@/lib/utils/pickerSources";
  import type { NodePickerConfig, ScopedTag } from "@/lib/types";
  import type { TagGovernanceAdapter } from "@/lib/utils/tagGovernance";

  interface Props {
    /** The roster to show/govern (already filtered to this context). */
    tags: ScopedTag[];
    /** Tags already on the entity — drives the "already added" affordance. */
    selectedKeys: Set<string>;
    scopeKind: string;
    scopeEntryType: string;
    ariaLabel: string;
    /** The governance operations for this vocabulary (project vs assistant). */
    adapter: TagGovernanceAdapter;
    /** Add a tag to the entity (the primary, most-frequent action). */
    onAdd: (name: string) => void;
  }

  let { tags, selectedKeys, scopeKind, scopeEntryType, ariaLabel, adapter, onAdd }: Props = $props();

  // Per-tag document use-counts, keyed lowercase. Loaded lazily on open (a doc
  // scan) so the fast add-path isn't blocked; counts fill in when it resolves.
  let counts = $state(new Map<string, number>());
  let countsLoaded = $state(false);
  let busy = $state(false);
  let error = $state("");

  let filter = $state("");

  // Row-level governance state. `activeTag` is the tag whose ⋯ was opened;
  // `sub` is which panel is showing for it. `merging` is the global multi-select
  // mode. The `‹` back-nav honours the depth the panel was reached at.
  let activeTag = $state<string | null>(null);
  const activeTagObj = $derived(activeTag ? (tags.find((t) => t.name === activeTag) ?? null) : null);
  let sub = $state<"menu" | "scope" | "rename">("menu");
  let scopeDraft = $state<NodePickerConfig>({ sources: [] });
  let renameDraft = $state("");

  let merging = $state(false);
  let ticked = $state(new Set<string>());
  let survivor = $state(""); // a ticked name, or a new name typed below
  let survivorNew = $state("");
  let confirmingMerge = $state(false);

  const trimmedFilter = $derived(filter.trim().toLowerCase());
  const shown = $derived(
    trimmedFilter ? tags.filter((t) => t.name.toLowerCase().includes(trimmedFilter)) : tags,
  );
  // Offer "Create 'x'" only when the typed filter matches no existing tag exactly.
  const createCandidate = $derived(
    filter.trim() && !tags.some((t) => t.name.toLowerCase() === trimmedFilter) ? filter.trim() : "",
  );

  function count(name: string): number {
    return counts.get(name.toLowerCase()) ?? 0;
  }

  async function loadCounts() {
    try {
      counts = await adapter.loadCounts();
      countsLoaded = true;
    } catch {
      // Counts are advisory; a failed scan just leaves them blank.
    }
  }
  onMount(loadCounts);

  function scopeChips(scope: NodePickerConfig): string[] {
    const { kinds, entryTypes } = pickerMembership(scope);
    if (kinds.length === 0 && Object.keys(entryTypes).length === 0) return ["everywhere"];
    const chips: string[] = [];
    for (const kind of kinds) {
      const subs = entryTypes[kind];
      chips.push(subs && subs.length ? `${kind}: ${subs.join(", ")}` : `${kind} · all`);
    }
    return chips;
  }

  // ---- navigation --------------------------------------------------------
  function openMenu(name: string) {
    activeTag = name;
    sub = "menu";
  }
  function openScope(tag: ScopedTag) {
    activeTag = tag.name;
    sub = "scope";
    scopeDraft = { sources: [...(tag.scope.sources ?? [])] };
  }
  function openRename(name: string) {
    activeTag = name;
    sub = "rename";
    renameDraft = name;
  }
  function backFromSub() {
    // Ops reached via the ⋯ menu back out to the menu; the menu backs out to the
    // list. There's always one obvious way back.
    sub = "menu";
  }
  function closeRow() {
    activeTag = null;
    sub = "menu";
  }

  function startMerge(seed: string) {
    merging = true;
    activeTag = null;
    // Clear any list filter: merge mode shows the tick list with no filter box,
    // so a leftover filter would silently hide (un-tickable) merge candidates.
    filter = "";
    ticked = new Set([seed.toLowerCase()]);
    survivor = seed;
    survivorNew = "";
    confirmingMerge = false;
  }
  function cancelMerge() {
    merging = false;
    ticked = new Set();
    survivor = "";
    survivorNew = "";
    confirmingMerge = false;
  }
  function toggleTick(name: string) {
    const next = new Set(ticked);
    const key = name.toLowerCase();
    if (next.has(key)) next.delete(key);
    else next.add(key);
    ticked = next;
    // If the survivor was un-ticked (and not a new name), drop it.
    if (!survivorNew.trim() && survivor && !next.has(survivor.toLowerCase())) survivor = "";
    confirmingMerge = false;
  }

  const tickedNames = $derived(tags.filter((t) => ticked.has(t.name.toLowerCase())).map((t) => t.name));
  const mergeRewriteUses = $derived(tickedNames.reduce((sum, n) => sum + count(n), 0));
  const chosenSurvivor = $derived(survivorNew.trim() || survivor);
  const canMerge = $derived(ticked.size >= 2 && !!chosenSurvivor && !busy);

  // ---- ops ---------------------------------------------------------------
  async function afterOp() {
    await loadCounts();
    // App reconciles roster + entry lists + open editors off the adapter's bump.
    await adapter.reconcile();
  }

  // Per-tag remount counter (lowercased name → bump count). Incremented for the
  // ONE row whose colour write FAILED, so its SwatchPicker remounts and its
  // optimistic self-mutation reverts to the persisted colour — the `value` prop
  // is one-way, so a same-value prop wouldn't reset it. Keyed per tag so a
  // failure doesn't remount every other row's swatch (#247).
  let swatchResets = $state<Record<string, number>>({});

  async function setColor(name: string, color: string | null) {
    // Colour is a quiet, non-destructive governance choice (the swatch owns it —
    // no ⋯ menu item), so no busy-lock or confirm.
    const key = name.toLowerCase();
    error = "";
    try {
      // Colour changes only the vocabulary's colour — not tag NAMES, use-counts,
      // or any node's content — so the adapter refreshes just its roster (every
      // chip recolours). The full reconcile (entry-list reloads + open-editor
      // baseline refetch) is for renames/merges that rewrite docs.
      await adapter.setColor(name, color);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      swatchResets = { ...swatchResets, [key]: (swatchResets[key] ?? 0) + 1 };
    }
  }

  async function saveScope(name: string) {
    busy = true;
    error = "";
    try {
      await adapter.updateScope(name, scopeDraft);
      closeRow();
      await afterOp();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }

  async function doRename(name: string) {
    const target = renameDraft.trim();
    if (!target || target.toLowerCase() === name.toLowerCase()) {
      closeRow();
      return;
    }
    busy = true;
    error = "";
    try {
      // Rename === fold the one tag into a (new) name; merge migrates every use
      // (and, for project tags, unions scope onto the target).
      await adapter.merge([name], target);
      closeRow();
      await afterOp();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }

  async function doMerge() {
    if (!canMerge) return;
    // The survivor is the merge TARGET, never one of its own sources — folding a
    // tag into itself is a no-op that the backend would reject when the survivor
    // is an inherited tag (`_reject_sources_above_this_layer`) and could drop the
    // target when it drops the sources. So when the survivor is a ticked tag,
    // exclude it; TagManagerDialog keeps target and sources separate the same way.
    const target = chosenSurvivor;
    const sources = tickedNames.filter((n) => n.toLowerCase() !== target.toLowerCase());
    if (sources.length === 0) return;
    busy = true;
    error = "";
    try {
      await adapter.merge(sources, target);
      cancelMerge();
      await afterOp();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busy = false;
    }
  }
</script>

<div class="trp" aria-label={`${ariaLabel} tags`}>
  {#if merging}
    <!-- ---- merge mode: tick two or more, then choose the survivor ---- -->
    <div class="trp-head">
      <button class="trp-back" type="button" aria-label="Cancel merge" onclick={cancelMerge}>‹</button>
      <span class="trp-head-label">Merge — tick two or more</span>
    </div>
    <div class="trp-rows">
      {#each shown as tag (tag.name)}
        <button
          class="trp-row trp-tick"
          class:on={ticked.has(tag.name.toLowerCase())}
          type="button"
          aria-pressed={ticked.has(tag.name.toLowerCase())}
          onclick={() => toggleTick(tag.name)}
        >
          <span class="trp-check" aria-hidden="true">{ticked.has(tag.name.toLowerCase()) ? "✓" : ""}</span>
          <span class="trp-name">{tag.name}</span>
          <span class="trp-uses">{count(tag.name)}</span>
        </button>
      {:else}
        <span class="trp-empty">No tags here.</span>
      {/each}
    </div>
    <div class="trp-mergebar">
      <div class="trp-survivor">
        <span class="trp-sub-label">Keep as</span>
        {#each tickedNames as name (name)}
          <button
            class="trp-surv-opt"
            class:on={!survivorNew.trim() && survivor.toLowerCase() === name.toLowerCase()}
            type="button"
            onclick={() => {
              survivor = name;
              survivorNew = "";
            }}>{name}</button>
        {/each}
        <input
          class="trp-surv-new"
          placeholder="or a new name"
          bind:value={survivorNew}
          aria-label="Merge into a new name"
        />
      </div>
      {#if confirmingMerge}
        <div class="trp-confirm">
          <span class="trp-confirm-msg">{countsLoaded
            ? `Rewrites ${mergeRewriteUses} tag use${mergeRewriteUses === 1 ? "" : "s"} · can't be undone`
            : "Counting uses… · can't be undone"}</span>
          <span class="trp-spacer"></span>
          <button class="trp-cancel" type="button" onclick={() => (confirmingMerge = false)}>Cancel</button>
          <button class="trp-danger" type="button" disabled={!canMerge} onclick={doMerge}>Merge</button>
        </div>
      {:else}
        <div class="trp-confirm">
          <span class="trp-confirm-msg">
            {#if ticked.size < 2}Tick two or more{:else if !chosenSurvivor}Choose a survivor{:else}{ticked.size} → “{chosenSurvivor}”{/if}
          </span>
          <span class="trp-spacer"></span>
          <button class="trp-do" type="button" disabled={!canMerge} onclick={() => (confirmingMerge = true)}>Merge…</button>
        </div>
      {/if}
    </div>
  {:else if activeTag && sub === "scope"}
    <!-- ---- suggest-on (scope) editor ---- -->
    <div class="trp-head">
      <button class="trp-back" type="button" aria-label="Back" onclick={backFromSub}>‹</button>
      <span class="trp-head-label">Suggest “{activeTag}” on</span>
    </div>
    <div class="trp-panel">
      <NodePickerConfigEditor mode="field" config={scopeDraft} onChange={(next) => (scopeDraft = next)} />
      <div class="trp-panel-foot">
        <span class="trp-spacer"></span>
        <button class="trp-cancel" type="button" onclick={backFromSub}>Cancel</button>
        <button class="trp-do" type="button" disabled={busy} onclick={() => saveScope(activeTag!)}>Save</button>
      </div>
    </div>
  {:else if activeTag && sub === "rename"}
    <!-- ---- rename (migrates every use) ---- -->
    <div class="trp-head">
      <button class="trp-back" type="button" aria-label="Back" onclick={backFromSub}>‹</button>
      <span class="trp-head-label">Rename “{activeTag}”</span>
    </div>
    <div class="trp-panel">
      <input class="trp-rename-input" bind:value={renameDraft} aria-label={`Rename ${activeTag}`} />
      <small class="trp-note">Migrates every use across the project.</small>
      <div class="trp-panel-foot">
        <span class="trp-spacer"></span>
        <button class="trp-cancel" type="button" onclick={backFromSub}>Cancel</button>
        <button class="trp-do" type="button" disabled={busy || !renameDraft.trim()} onclick={() => doRename(activeTag!)}>Rename</button>
      </div>
    </div>
  {:else if activeTag}
    <!-- ---- the ⋯ menu for one tag ---- -->
    <div class="trp-head">
      <button class="trp-back" type="button" aria-label="Back" onclick={closeRow}>‹</button>
      <span class="trp-head-label">{activeTag}</span>
    </div>
    <div class="trp-menu">
      {#if adapter.supportsScope}
        <button class="trp-menu-item" type="button" onclick={() => activeTagObj && openScope(activeTagObj)}>
          <i class="ti ti-target" aria-hidden="true"></i> Suggest on…
        </button>
      {/if}
      <button class="trp-menu-item" type="button" onclick={() => openRename(activeTag!)}>
        <i class="ti ti-pencil" aria-hidden="true"></i> Rename…
      </button>
      <button class="trp-menu-item" type="button" onclick={() => startMerge(activeTag!)}>
        <i class="ti ti-arrow-merge" aria-hidden="true"></i> Merge…
      </button>
    </div>
  {:else}
    <!-- ---- the plain roster (add + govern) ---- -->
    <div class="trp-filter-row">
      <input class="trp-filter" placeholder="Filter tags…" bind:value={filter} aria-label={`Filter ${ariaLabel}`} />
    </div>
    <div class="trp-rows" role="list">
      {#each shown as tag (tag.name)}
        <div class="trp-row" role="listitem">
          <span class="trp-swatch">
            {#key `${tag.color ?? ""}#${swatchResets[tag.name.toLowerCase()] ?? 0}`}
              <SwatchPicker value={tag.color ?? null} onChange={(id) => setColor(tag.name, id)} />
            {/key}
          </span>
          <button
            class="trp-add"
            class:active={selectedKeys.has(tag.name.toLowerCase())}
            type="button"
            title={selectedKeys.has(tag.name.toLowerCase()) ? `${tag.name} (already added)` : `Add ${tag.name}`}
            onmousedown={(e) => e.preventDefault()}
            onclick={() => onAdd(tag.name)}
          >
            <span class="trp-name">{tag.name}</span>
            {#if adapter.supportsScope}
              <span class="trp-scope">{scopeChips(tag.scope).join(" · ")}</span>
            {/if}
          </button>
          <span class="trp-uses" title="uses">{count(tag.name)}</span>
          <button
            class="trp-cog"
            type="button"
            aria-label={`Govern ${tag.name}`}
            onclick={() => openMenu(tag.name)}
          >⋯</button>
        </div>
      {:else}
        {#if !createCandidate}<span class="trp-empty">No tags suggested here yet.</span>{/if}
      {/each}
      {#if createCandidate}
        <button class="trp-create" type="button" onmousedown={(e) => e.preventDefault()} onclick={() => onAdd(createCandidate)}>
          <span class="trp-create-plus" aria-hidden="true">+</span> Create “{createCandidate}”
        </button>
      {/if}
    </div>
  {/if}

  {#if error}<p class="trp-error">{error}</p>{/if}
</div>

<style>
  .trp {
    display: flex;
    flex-direction: column;
    width: 100%;
    min-width: 0;
  }
  .trp-head {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px;
    border-bottom: 1px solid var(--divider);
  }
  .trp-back {
    flex: none;
    width: 22px;
    height: 22px;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    color: var(--text-2);
    font-size: var(--fs-md);
    line-height: 1;
    cursor: pointer;
  }
  .trp-back:hover {
    border-color: var(--accent);
    color: var(--accent-strong);
  }
  .trp-head-label {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .trp-filter-row {
    padding: 7px 8px;
    border-bottom: 1px solid var(--divider);
  }
  .trp-filter {
    width: 100%;
    padding: 5px 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    color: var(--text);
    font-size: var(--fs-sm);
  }

  .trp-rows {
    display: flex;
    flex-direction: column;
    max-height: 240px;
    overflow: auto;
    padding: 4px;
    gap: 2px;
  }
  .trp-row {
    display: flex;
    align-items: center;
    gap: 6px;
    border-radius: 7px;
    padding: 0 4px 0 0;
  }
  .trp-row:hover {
    background: var(--inset);
  }
  .trp-swatch {
    flex: none;
    display: inline-flex;
    padding-left: 4px;
  }
  .trp-add {
    flex: 1 1 auto;
    display: flex;
    align-items: baseline;
    gap: 8px;
    min-width: 0;
    padding: 5px 8px;
    border: 0;
    border-radius: 7px;
    background: transparent;
    color: var(--text);
    text-align: left;
    cursor: pointer;
  }
  .trp-add.active .trp-name {
    color: var(--accent-deep);
  }
  .trp-add.active::before {
    content: "✓";
    color: var(--accent);
    font-size: var(--fs-xs);
  }
  .trp-name {
    font-size: var(--fs-sm);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .trp-scope {
    font-size: var(--fs-xs);
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .trp-uses {
    flex: none;
    min-width: 18px;
    text-align: right;
    font-size: var(--fs-xs);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .trp-cog {
    flex: none;
    width: 24px;
    height: 24px;
    padding: 0;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: var(--text-3);
    font-size: var(--fs-lg);
    line-height: 1;
    cursor: pointer;
    opacity: 0;
  }
  .trp-row:hover .trp-cog,
  .trp-cog:focus-visible {
    opacity: 1;
  }
  .trp-cog:hover {
    background: var(--surface);
    color: var(--accent);
  }
  .trp-empty {
    padding: 8px;
    color: var(--text-3);
    font-size: var(--fs-sm);
  }
  .trp-create {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 8px;
    border: 1px dashed var(--accent);
    border-radius: 7px;
    background: transparent;
    color: var(--accent-strong);
    font-size: var(--fs-sm);
    cursor: pointer;
  }
  .trp-create:hover {
    background: var(--accent-soft);
  }

  /* ---- ⋯ menu ---- */
  .trp-menu {
    display: flex;
    flex-direction: column;
    padding: 4px;
    gap: 2px;
  }
  .trp-menu-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 7px 9px;
    border: 0;
    border-radius: 7px;
    background: transparent;
    color: var(--text);
    font-size: var(--fs-sm);
    text-align: left;
    cursor: pointer;
  }
  .trp-menu-item:hover {
    background: var(--inset);
  }

  /* ---- scope / rename panels ---- */
  .trp-panel {
    display: flex;
    flex-direction: column;
    gap: 9px;
    padding: 10px;
  }
  .trp-rename-input {
    width: 100%;
    padding: 6px 9px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    color: var(--text);
    font-size: var(--fs-md);
  }
  .trp-note {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .trp-panel-foot,
  .trp-confirm {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  /* ---- merge bar ---- */
  .trp-mergebar {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 9px 10px;
    border-top: 1px solid var(--divider);
    background: var(--panel);
  }
  .trp-survivor {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
  }
  .trp-sub-label {
    font-size: var(--fs-xs);
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--text-3);
  }
  .trp-surv-opt {
    padding: 3px 9px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--surface);
    color: var(--text-2);
    font-size: var(--fs-sm);
    cursor: pointer;
  }
  .trp-surv-opt.on {
    border-color: var(--accent);
    background: var(--accent-soft);
    color: var(--accent-emphasis);
  }
  .trp-surv-new {
    flex: 1 1 120px;
    min-width: 100px;
    padding: 4px 8px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    color: var(--text);
    font-size: var(--fs-sm);
  }
  .trp-confirm-msg {
    font-size: var(--fs-xs);
    color: var(--text-2);
  }
  .trp-spacer {
    flex: 1;
  }

  /* ---- tick rows (merge mode) ---- */
  .trp-tick {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 8px;
    border: 0;
    border-radius: 7px;
    background: transparent;
    color: var(--text);
    text-align: left;
    cursor: pointer;
  }
  .trp-tick:hover {
    background: var(--inset);
  }
  .trp-tick.on {
    background: var(--accent-soft);
  }
  .trp-check {
    flex: none;
    width: 16px;
    height: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border-strong);
    border-radius: 4px;
    font-size: var(--fs-xs);
    color: var(--accent-deep);
  }
  .trp-tick.on .trp-check {
    border-color: var(--accent);
    background: var(--accent);
    color: #fff;
  }
  .trp-tick .trp-name {
    flex: 1 1 auto;
  }

  /* ---- buttons ---- */
  .trp-do,
  .trp-cancel,
  .trp-danger {
    padding: 5px 12px;
    border-radius: 8px;
    font-size: var(--fs-sm);
    font-weight: 600;
    cursor: pointer;
  }
  .trp-do {
    border: 1px solid var(--accent);
    background: var(--accent);
    color: #fff;
  }
  .trp-cancel {
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-2);
    font-weight: 500;
  }
  .trp-danger {
    border: 1px solid var(--danger);
    background: var(--danger);
    color: #fff;
  }
  .trp-do:disabled,
  .trp-danger:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .trp-error {
    margin: 0;
    padding: 7px 10px;
    color: var(--danger);
    font-size: var(--fs-xs);
  }
</style>
