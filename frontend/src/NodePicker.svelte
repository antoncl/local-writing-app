<script lang="ts">
  // NodePicker — generalized picker for choosing nodes (scenes, lore,
  // snippets, assistants, presets) constrained by a NodePickerConfig.
  // Used by both prompt context_pick inputs and entity_ref metadata
  // fields via ReferencePicker.
  //
  // Renders a "+ <label>" button. Clicking opens a constrained menu
  // limited to the kinds / sub-types / presets the config declares.
  // Picked items render as chips above the button with × buttons to
  // remove (suppressed when `hideChips` is set — the caller renders
  // them itself, e.g. ReferencePicker's NodeRow cards).
  //
  // Stores only refs (id, kind, title) — bodies are materialized
  // server-side at template render time. See docs/context-picker.md.

  import { createEventDispatcher, tick } from "svelte";
  import { metadataSchemaStore } from "./stores/schema";
  import type {
    NodePickerConfig,
    NodePickerRef,
    LoreEntrySummary,
    MetadataSchema,
    PromptEntrySummary,
    StructureDocument,
    StructureNode,
  } from "./types";
  import { resolveColor } from "./colors";

  // Resolve a ref's color via the full chain: instance (not carried on
  // NodePickerRef today — that's a Phase 4 surface) → entry-type → parent
  // chain → kind-default. Returns an inline CSS custom property string;
  // the chip / monogram CSS reads `--chip-base` and derives the soft tint
  // via color-mix(). Empty string falls back to the neutral chip.
  function colorStyleForRef(ref: { kind: string; entry_type?: string }): string {
    const swatch = resolveColor(null, ref.entry_type, ref.kind, metadataSchema);
    return swatch ? `--chip-base: ${swatch.hex};` : "";
  }

  export let config: NodePickerConfig = {};
  export let value: NodePickerRef[] = [];
  export let label: string = "Context";
  export let structure: StructureDocument | null = null;
  // Research tree, sibling to `structure`. Same shape — used to enumerate
  // research notes (leaves only; topics are organizational containers
  // with no body to inject).
  export let researchStructure: StructureDocument | null = null;
  export let loreEntries: LoreEntrySummary[] = [];
  export let promptEntries: PromptEntrySummary[] = [];
  // metadataSchema is global per-project — read from the store, not a prop (#14 Step 2).
  $: metadataSchema = $metadataSchemaStore;
  // Compact mode trims chrome so the picker fits inside the Inputs
  // dialog's narrow column. Composer-level renders use the default.
  export let compact: boolean = false;
  // Suppress the built-in chip display. Caller renders selected refs
  // themselves (e.g. ReferencePicker hosts NodeRow cards above the
  // picker). The `value` prop still flows in so the dropdown can mark
  // already-picked items as disabled.
  export let hideChips: boolean = false;
  // Ids to drop from the candidate menu — used by ReferencePicker to
  // hide the entry that owns the field (no self-references) without the
  // caller having to filter the in-memory data sources.
  export let excludeIds: string[] = [];

  const dispatch = createEventDispatcher<{ change: { value: NodePickerRef[] } }>();

  type Category = "scene" | "lore" | "snippet" | "assistant" | "research";

  let open = false;
  let search = "";
  let searchInputEl: HTMLInputElement | null = null;

  // Group-default thresholds: groups larger than this collapse by default
  // so a 128-scene project doesn't drown the menu. Compact mode is more
  // aggressive because there's less vertical room.
  const COLLAPSE_THRESHOLD_DEFAULT = 20;
  const COLLAPSE_THRESHOLD_COMPACT = 5;

  // Allowed presets per the author config — empty means no presets shown.
  $: allowedPresets = config.presets ?? [];
  // Allowed kinds per the author config — empty means no browse section.
  $: allowedKinds = (config.kinds ?? []) as Category[];
  $: allowMultiple = config.multiple !== false;

  const PRESET_META: Record<string, { title: string; tooltip: string }> = {
    full_outline: {
      title: "Full Outline",
      tooltip:
        "Include the manuscript outline (acts → chapters → scenes with summaries).",
    },
    full_text: {
      title: "Full Novel Text",
      tooltip: "Include every scene's prose in manuscript order. Can be large.",
    },
  };

  function refKey(ref: NodePickerRef): string {
    return `${ref.kind}:${ref.id}`;
  }

  function isPicked(ref: NodePickerRef): boolean {
    return value.some((existing) => refKey(existing) === refKey(ref));
  }

  function add(ref: NodePickerRef) {
    if (isPicked(ref)) return;
    const next = allowMultiple ? [...value, ref] : [ref];
    dispatch("change", { value: next });
    if (!allowMultiple) close();
  }

  function remove(key: string) {
    dispatch("change", {
      value: value.filter((ref) => refKey(ref) !== key),
    });
  }

  // Author opt-in: ★ target marking only when config flags it. Surface
  // controlled by the prompt author so template code knows whether
  // `scene` is reliably bound.
  $: allowTargetMarking = config.allow_target_marking === true;

  // ★ target marking: one scene per input may be flagged as the template's
  // `scene` binding (NC-style). Clicking ★ on a scene toggles it; clicking
  // ★ on a different scene moves the mark. Non-scene refs ignore the flag.
  function toggleTarget(ref: NodePickerRef) {
    if (ref.kind !== "scene" || !allowTargetMarking) return;
    const targetKey = refKey(ref);
    const willBeTarget = !ref.target;
    const next = value.map((r) => {
      if (r.kind !== "scene") return r;
      if (refKey(r) === targetKey) return { ...r, target: willBeTarget };
      // Single ★ per input — clear any prior target on other scene refs.
      if (r.target) return { ...r, target: false };
      return r;
    });
    dispatch("change", { value: next });
  }

  // Trigger element + menu position state. The menu is rendered with
  // `position: fixed` so it escapes the metadata-panel's overflow:auto
  // (which clipped the dropdown when ReferencePicker hosts this picker
  // inside a scene/lore metadata field). Position is captured from the
  // trigger's getBoundingClientRect at open time and on resize/scroll.
  let triggerEl: HTMLButtonElement | undefined;
  let menuStyle = "";
  const MENU_WIDTH = 344;
  const MENU_MAX_HEIGHT = 420;

  function positionMenu() {
    if (!triggerEl) return;
    const r = triggerEl.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const spaceBelow = vh - r.bottom;
    const spaceAbove = r.top;
    const useAbove = spaceBelow < MENU_MAX_HEIGHT + 12 && spaceAbove > spaceBelow;
    const top = useAbove
      ? Math.max(8, r.top - MENU_MAX_HEIGHT - 4)
      : Math.min(vh - 12, r.bottom + 4);
    let left = r.left;
    if (left + MENU_WIDTH + 8 > vw) left = Math.max(8, vw - MENU_WIDTH - 8);
    menuStyle = `top: ${top}px; left: ${left}px;`;
  }

  async function toggle() {
    open = !open;
    if (open) {
      search = "";
      await tick();
      positionMenu();
      searchInputEl?.focus();
    }
  }

  function close() {
    open = false;
    search = "";
  }

  function handleViewportShift() {
    if (open) positionMenu();
  }

  function handleDocumentClick(event: MouseEvent) {
    const target = event.target as HTMLElement | null;
    if (open && !target?.closest(".ctx-picker-anchor")) close();
  }

  function handleKeydown(event: KeyboardEvent) {
    if (open && event.key === "Escape") {
      event.preventDefault();
      close();
    }
  }

  // Flatten the structure tree's scenes (entries with kind=scene) into a
  // searchable list, respecting the per-input sub-type filter so the
  // editor's checkbox actually does something (was a silent no-op).
  function flattenScenes(node: StructureNode | undefined): Array<{ id: string; title: string; entry_type: string }> {
    if (!node) return [];
    const allowed = new Set(config.entry_types?.scene ?? []);
    const out: Array<{ id: string; title: string; entry_type: string }> = [];
    const walk = (n: StructureNode) => {
      // StructureNode uses `type` ("scene" / "act" / "chapter" / "root").
      // An earlier read used `n.kind`, which is always undefined — so
      // the scene list was silently empty. scene_id is the canonical id
      // for the scene itself (the structure node has its own id for the
      // outline position).
      if (n.type === "scene" && n.scene_id) {
        const sceneType = (n as unknown as { entry_type?: string }).entry_type ?? "scene";
        if (allowed.size === 0 || allowed.has(sceneType)) {
          out.push({ id: n.scene_id, title: n.title, entry_type: sceneType });
        }
      }
      for (const child of n.children ?? []) walk(child);
    };
    walk(node);
    return out;
  }

  $: allScenes = structure ? flattenScenes(structure.root) : [];
  $: filteredScenes = filterByTitle(allScenes, search);

  // Flatten the research tree's notes (leaves) into a searchable list.
  // Topics are organizational containers with no body — only notes are
  // pickable as context. Mirrors flattenScenes but for note_id leaves
  // (the model field is named `scene_id` for both trees; on disk the
  // research tree uses `note_id` — see TreeStructureService).
  function flattenResearchNotes(node: StructureNode | undefined): Array<{ id: string; title: string; entry_type: string }> {
    if (!node) return [];
    const allowed = new Set(config.entry_types?.research ?? []);
    const out: Array<{ id: string; title: string; entry_type: string }> = [];
    const walk = (n: StructureNode) => {
      if (n.type === "note" && n.scene_id) {
        if (allowed.size === 0 || allowed.has(n.type)) {
          out.push({ id: n.scene_id, title: n.title, entry_type: n.type });
        }
      }
      for (const child of n.children ?? []) walk(child);
    };
    walk(node);
    return out;
  }

  $: allResearchNotes = researchStructure ? flattenResearchNotes(researchStructure.root) : [];
  $: filteredResearchNotes = filterByTitle(allResearchNotes, search);

  function filterByTitle<T extends { title: string }>(items: T[], q: string): T[] {
    if (!q.trim()) return items;
    const lower = q.toLowerCase();
    return items.filter((i) => i.title.toLowerCase().includes(lower));
  }

  // Lore grouped by sub-type, respecting `config.entry_types.lore` filter
  // when set. Empty filter = all sub-types allowed.
  $: loreGroups = (() => {
    const allowed = new Set(config.entry_types?.lore ?? []);
    const visible = loreEntries.filter((entry) => {
      // context_policy = "never" hides the entry from every explicit
      // picker. The entry still exists (browsable in the Lore pane);
      // it just can't be selected as context here.
      if (entry.metadata?.context_policy === "never") return false;
      return allowed.size === 0 ? true : allowed.has(entry.entry_type);
    });
    const filtered = filterByTitle(visible, search);
    const byType: Record<string, LoreEntrySummary[]> = {};
    for (const entry of filtered) {
      (byType[entry.entry_type] ||= []).push(entry);
    }
    return Object.entries(byType).map(([typeId, entries]) => ({
      typeId,
      typeName: metadataSchema?.entry_types[typeId]?.name ?? typeId,
      entries,
    }));
  })();

  // Snippets are prompts of sub-types where kind=prompt and not abstract
  // and (loosely) snippet-shaped. App.svelte's snippetEntriesFor() filter
  // is more involved; for v1 we just expose all non-abstract prompt
  // entries that match the search.
  $: snippetEntries = filterByTitle(
    promptEntries.filter((p) => {
      const allowed = new Set(config.entry_types?.snippet ?? []);
      return allowed.size === 0 || allowed.has(p.entry_type);
    }),
    search,
  );

  // Chip text resolution. Show the entry-type's display name from the
  // schema when known; fall back to a sensible singular for the kind.
  // Fixes the inverted-affordance bug where `character` chips read the
  // same as bare `lore` chips because entry_type was missing.
  const KIND_LABEL_SINGULAR: Record<Category | "preset", string> = {
    scene: "Scene",
    lore: "Lore",
    research: "Note",
    snippet: "Snippet",
    assistant: "Assistant",
    preset: "Preset",
  };

  function chipLabel(ref: NodePickerRef): string {
    if (ref.kind === "preset") return KIND_LABEL_SINGULAR.preset;
    const subType = ref.entry_type && ref.entry_type !== ref.kind ? ref.entry_type : null;
    const displayName = subType ? metadataSchema?.entry_types[subType]?.name : null;
    return displayName ?? subType ?? KIND_LABEL_SINGULAR[ref.kind] ?? ref.kind;
  }

  // Compute item tag (the small "Scene" / "Character" / "Preset" label
  // shown alongside a result in the unified menu). Mirrors chipLabel
  // for selected items, but for a tree item we have the full ref-shape
  // info ready at render time.
  function itemTag(kind: NodePickerRef["kind"], entryType?: string): string {
    if (kind === "preset") return KIND_LABEL_SINGULAR.preset;
    const sub = entryType && entryType !== kind ? entryType : null;
    const displayName = sub ? metadataSchema?.entry_types[sub]?.name : null;
    return displayName ?? sub ?? KIND_LABEL_SINGULAR[kind] ?? kind;
  }

  // One-letter monogram for an item row's leading square. Prefers the
  // first letter of the sub-type display name (so "Character" → C,
  // "Location" → L, custom "Faction" → F), falls back to entry_type id,
  // then to the kind initial. Stable + informative for user-defined
  // sub-types without an icon set.
  function itemMonogram(kind: NodePickerRef["kind"], entryType?: string): string {
    if (kind === "preset") return "P";
    const sub = entryType && entryType !== kind ? entryType : null;
    const displayName = sub ? metadataSchema?.entry_types[sub]?.name : null;
    const source = displayName || sub || KIND_LABEL_SINGULAR[kind] || kind;
    return source.charAt(0).toUpperCase();
  }

  // Aggregate visible groups for the unified menu. Each group renders
  // as a collapsible <details> with a header and a flat item list.
  // Groups with no items (after the search filter and config gating)
  // are dropped entirely.
  $: excludeIdSet = new Set(excludeIds);

  $: visibleGroups = (() => {
    type Group = { id: string; label: string; items: Array<{ ref: NodePickerRef; tag: string; monogram: string }> };
    const groups: Group[] = [];
    const dropExcluded = <T extends { ref: NodePickerRef }>(items: T[]): T[] =>
      excludeIdSet.size === 0 ? items : items.filter((i) => !excludeIdSet.has(i.ref.id));

    const matchingPresets = allowedPresets.filter((id) => {
      const meta = PRESET_META[id] ?? { title: id, tooltip: "" };
      if (!search.trim()) return true;
      return meta.title.toLowerCase().includes(search.toLowerCase());
    });
    if (matchingPresets.length > 0) {
      groups.push({
        id: "presets",
        label: "Presets",
        items: matchingPresets.map((presetId) => {
          const meta = PRESET_META[presetId] ?? { title: presetId, tooltip: "" };
          return {
            ref: { id: presetId, kind: "preset" as const, title: meta.title },
            tag: itemTag("preset"),
            monogram: itemMonogram("preset"),
          };
        }),
      });
    }

    if (allowedKinds.includes("scene")) {
      const items = dropExcluded(
        filteredScenes.map((s) => ({
          ref: { id: s.id, kind: "scene" as const, title: s.title, entry_type: s.entry_type },
          tag: itemTag("scene", s.entry_type),
          monogram: itemMonogram("scene", s.entry_type),
        })),
      );
      if (items.length > 0) groups.push({ id: "scenes", label: "Scenes", items });
    }

    if (allowedKinds.includes("lore")) {
      const loreItems = dropExcluded(
        loreGroups.flatMap((g) =>
          g.entries.map((entry) => ({
            ref: { id: entry.id, kind: "lore" as const, title: entry.title, entry_type: entry.entry_type },
            tag: itemTag("lore", entry.entry_type),
            monogram: itemMonogram("lore", entry.entry_type),
          })),
        ),
      );
      if (loreItems.length > 0) {
        groups.push({ id: "lore", label: "Lore", items: loreItems });
      }
    }

    if (allowedKinds.includes("snippet")) {
      const items = dropExcluded(
        snippetEntries.map((s) => ({
          ref: { id: s.id, kind: "snippet" as const, title: s.title, entry_type: s.entry_type },
          tag: itemTag("snippet", s.entry_type),
          monogram: itemMonogram("snippet", s.entry_type),
        })),
      );
      if (items.length > 0) groups.push({ id: "snippets", label: "Snippets", items });
    }

    if (allowedKinds.includes("research")) {
      const items = dropExcluded(
        filteredResearchNotes.map((n) => ({
          ref: { id: n.id, kind: "research" as const, title: n.title, entry_type: n.entry_type },
          tag: itemTag("research", n.entry_type),
          monogram: itemMonogram("research", n.entry_type),
        })),
      );
      if (items.length > 0) groups.push({ id: "research", label: "Research", items });
    }

    return groups;
  })();

  $: hasAnyConfigured =
    allowedPresets.length > 0 || allowedKinds.length > 0;
  $: hasAnyResults = visibleGroups.length > 0;

  // Total result count for the search-bar live counter. Reflects the
  // post-filter, post-gating reality so the user can tell when their
  // search has zeroed out before scrolling.
  $: totalVisibleItems = visibleGroups.reduce((acc, g) => acc + g.items.length, 0);

  $: collapseThreshold = compact ? COLLAPSE_THRESHOLD_COMPACT : COLLAPSE_THRESHOLD_DEFAULT;

  // Search-aware: when the user is searching, expand every surviving
  // group so they can see what matched. When idle, collapse heavy
  // groups by their kind-appropriate threshold.
  function groupOpenByDefault(itemCount: number, isSearching: boolean): boolean {
    if (isSearching) return true;
    return itemCount <= collapseThreshold;
  }

  // Render a title as alternating plain/highlighted spans for the
  // current search term. Empty search → single plain segment.
  function highlightSegments(title: string, query: string): Array<{ text: string; match: boolean }> {
    const q = query.trim();
    if (!q) return [{ text: title, match: false }];
    const lower = title.toLowerCase();
    const needle = q.toLowerCase();
    const out: Array<{ text: string; match: boolean }> = [];
    let i = 0;
    while (i < title.length) {
      const found = lower.indexOf(needle, i);
      if (found < 0) {
        out.push({ text: title.slice(i), match: false });
        break;
      }
      if (found > i) out.push({ text: title.slice(i, found), match: false });
      out.push({ text: title.slice(found, found + needle.length), match: true });
      i = found + needle.length;
    }
    return out;
  }
</script>

<svelte:document on:mousedown={handleDocumentClick} on:keydown={handleKeydown} />
<svelte:window on:scroll={handleViewportShift} on:resize={handleViewportShift} />

<div class="ctx-picker" class:compact>
  <!-- PR 2: chips + trigger live in one bordered "context bar" so the
       relationship reads as a single object instead of a button with
       chips drifting above it. Empty bar persists with just the
       trigger so the affordance is always present. -->
  <div class="ctx-context-bar" class:chips-hidden={hideChips}>
    {#if !hideChips}
    {#each value as ref (refKey(ref))}
      <span
        class="ctx-chip"
        class:ctx-chip-preset={ref.kind === "preset"}
        class:ctx-chip-target={ref.target}
        style={colorStyleForRef(ref)}
      >
        {#if compact}
          <span class="ctx-chip-dot" aria-hidden="true"></span>
        {/if}
        {#if ref.kind === "scene" && allowTargetMarking}
          <button
            type="button"
            class="ctx-chip-star"
            aria-pressed={ref.target ?? false}
            aria-label={ref.target ? `Unmark ${ref.title} as target scene` : `Mark ${ref.title} as target scene`}
            title={ref.target ? "★ Target — binds to `scene` in the template. Click to unmark." : "Mark as target — binds to `scene` in the template."}
            on:click={() => toggleTarget(ref)}
          >{ref.target ? "★" : "☆"}</button>
        {/if}
        {#if !compact}
          <span class="ctx-chip-tag">{chipLabel(ref)}</span>
        {/if}
        <strong class="ctx-chip-title">{ref.title}</strong>
        <button
          type="button"
          class="ctx-chip-remove"
          aria-label="Remove {ref.title}"
          on:click={() => remove(refKey(ref))}
        >×</button>
      </span>
    {/each}
    {/if}

    <div class="ctx-picker-anchor">
      <button
        bind:this={triggerEl}
        type="button"
        class="ctx-add"
        aria-haspopup="menu"
        aria-expanded={open}
        on:click={toggle}
      >
        <span class="ctx-add-plus" aria-hidden="true">+</span>
        <span class="ctx-add-label">{value.length > 0 ? "Add" : label}</span>
      </button>

    {#if open}
      <div class="ctx-menu" role="menu" style={menuStyle}>
        <label class="ctx-search-wrap" class:has-query={search.length > 0}>
          <svg class="ctx-search-icon" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <circle cx="6" cy="6" r="4.2" stroke="currentColor" stroke-width="1.6" />
            <line x1="9.2" y1="9.2" x2="12.5" y2="12.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
          </svg>
          <input
            class="ctx-search"
            type="text"
            placeholder={compact ? "Search…" : "Search scenes, lore, presets…"}
            bind:value={search}
            bind:this={searchInputEl}
          />
          {#if search.length > 0}
            <button
              type="button"
              class="ctx-search-clear"
              aria-label="Clear search"
              on:click={() => (search = "")}
            >×</button>
          {:else if hasAnyResults}
            <span class="ctx-search-count">{totalVisibleItems}{compact ? "" : " items"}</span>
          {/if}
        </label>

        {#if !hasAnyConfigured}
          <div class="ctx-empty">
            <span class="ctx-empty-icon" aria-hidden="true">∅</span>
            <span class="ctx-empty-title">No content sources configured</span>
            <span class="ctx-empty-hint">
              This prompt's author didn't enable any pickable types or presets for this input.
            </span>
          </div>
        {:else if !hasAnyResults}
          {#if search}
            <div class="ctx-empty">
              <svg class="ctx-empty-icon-svg" width="30" height="30" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="10" cy="10" r="6.5" stroke="currentColor" stroke-width="1.4" />
                <line x1="15" y1="15" x2="21" y2="21" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
              </svg>
              <span class="ctx-empty-title">No matches for <strong>"{search}"</strong></span>
              <span class="ctx-empty-hint">Try a different term, or clear the search to browse.</span>
            </div>
          {:else}
            <div class="ctx-empty">
              <span class="ctx-empty-icon" aria-hidden="true">∅</span>
              <span class="ctx-empty-title">No pickable items in this project yet</span>
            </div>
          {/if}
        {:else}
          {#each visibleGroups as group (group.id)}
            {@const isOpen = groupOpenByDefault(group.items.length, search.length > 0)}
            <details class="ctx-group" open={isOpen}>
              <summary class="ctx-group-bar">
                <span class="ctx-group-chevron" aria-hidden="true">▾</span>
                <span class="ctx-group-label">{group.label}</span>
                <span class="ctx-group-count">{group.items.length}</span>
              </summary>
              <div class="ctx-group-items">
                {#each group.items as item (item.ref.id + ":" + item.ref.kind)}
                  {@const picked = isPicked(item.ref)}
                  <button
                    type="button"
                    class="ctx-item"
                    disabled={picked}
                    title={picked ? "Already added" : ""}
                    style={colorStyleForRef(item.ref)}
                    on:click={() => add(item.ref)}
                  >
                    <span class="ctx-item-mono" aria-hidden="true">{item.monogram}</span>
                    <span class="ctx-item-title">
                      {#each highlightSegments(item.ref.title, search) as seg}
                        {#if seg.match}<mark>{seg.text}</mark>{:else}{seg.text}{/if}
                      {/each}
                    </span>
                    {#if picked && !compact}
                      <span class="ctx-item-added">✓ Added</span>
                    {/if}
                  </button>
                {/each}
              </div>
            </details>
          {/each}
        {/if}
      </div>
    {/if}
    </div>
  </div>
</div>

<style>
  .ctx-picker {
    /* Light theme tokens — mirrored to the config editor's set so the
       two surfaces share vocabulary. Adds a kind-color quartet for chip
       and monogram coloring. Dark set lives under [data-theme=dark]. */
    --ctx-surface: #ffffff;
    --ctx-panel: #f7faf8;
    --ctx-panel-2: #eef3f0;
    --ctx-inset: #f3f6f4;
    --ctx-border: #cdd8d3;
    --ctx-border-strong: #b4c2bc;
    --ctx-text: #28332f;
    --ctx-text-2: #4d5753;
    --ctx-text-3: #6c7872;
    --ctx-accent: #3f7d68;
    --ctx-accent-strong: #356b59;
    --ctx-accent-soft: #e2efe9;
    --ctx-star: #b07d1e;
    --ctx-star-soft: #f7eed7;
    --ctx-shadow: rgba(40, 60, 52, 0.08);
    --ctx-shadow-pop: rgba(40, 60, 52, 0.18);
    /* Per-chip colors come from inline `--chip-base` set by the markup
       via resolveColorForKind() — see colors.ts. The soft tint is
       derived in CSS via color-mix so we don't have to ship two values
       per swatch. */

    display: flex;
    flex-direction: column;
    min-width: 0;
    color: var(--ctx-text);
  }

  :global([data-theme="dark"]) .ctx-picker {
    --ctx-surface: #18211d;
    --ctx-panel: #141c18;
    --ctx-panel-2: #1e2823;
    --ctx-inset: #1b2521;
    --ctx-border: #324039;
    --ctx-border-strong: #41534a;
    --ctx-text: #e3e9e5;
    --ctx-text-2: #b4c0ba;
    --ctx-text-3: #869189;
    --ctx-accent: #5ea585;
    --ctx-accent-strong: #7cc0a1;
    --ctx-accent-soft: #22332c;
    --ctx-star: #d6a946;
    --ctx-star-soft: #3a2f17;
    --ctx-shadow: rgba(0, 0, 0, 0.45);
    --ctx-shadow-pop: rgba(0, 0, 0, 0.55);
  }

  /* --- Context bar (PR 2: chips + trigger in one bordered well) ---- */

  .ctx-context-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    padding: 6px;
    border: 1px solid var(--ctx-border);
    border-radius: 10px;
    background: var(--ctx-surface);
    min-width: 0;
  }

  .compact .ctx-context-bar {
    padding: 5px;
    gap: 5px;
    border-radius: 9px;
  }

  /* --- Chip ------------------------------------------------------- */

  .ctx-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 8px;
    background: var(--ctx-surface);
    border: 1px solid var(--ctx-border);
    border-radius: 8px;
    font-size: 12.5px;
    line-height: 1.2;
    color: var(--ctx-text);
    /* --chip-base is set inline per chip by colorStyleForRef() — see the
       script. The tag-pill color uses the base directly; the tag-pill
       background is a soft tint derived via color-mix. When unset, the
       chip falls back to a neutral border-only treatment. */
    --chip-tag-color: var(--chip-base, var(--ctx-text-3));
    --chip-tag-bg: var(--ctx-inset);
  }

  .ctx-chip[style*="--chip-base"] {
    --chip-tag-bg: color-mix(in srgb, var(--chip-base) 12%, white 88%);
  }

  :global([data-theme="dark"]) .ctx-chip[style*="--chip-base"] {
    --chip-tag-color: color-mix(in srgb, var(--chip-base) 75%, white 25%);
    --chip-tag-bg: color-mix(in srgb, var(--chip-base) 18%, black 82%);
  }

  /* Preset chips reverse the polarity — pale base-tint background so the
     whole-document inclusion reads visually distinct from item chips. */
  .ctx-chip-preset {
    background: color-mix(in srgb, var(--chip-base, var(--ctx-text-3)) 12%, white 88%);
    --chip-tag-color: var(--chip-base, var(--ctx-text-3));
    --chip-tag-bg: var(--ctx-surface);
  }

  :global([data-theme="dark"]) .ctx-chip-preset {
    background: color-mix(in srgb, var(--chip-base, var(--ctx-text-3)) 18%, black 82%);
  }

  /* ★-bound scene gets a full gold-tint chip — loudest treatment in the
     strip, because this scene fills the template's `scene` variable. */
  .ctx-chip-target {
    background: var(--ctx-star-soft);
    border-color: var(--ctx-star);
    --chip-tag-color: var(--ctx-star);
    --chip-tag-bg: var(--ctx-surface);
  }

  .ctx-chip-tag {
    font-size: 9.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--chip-tag-color);
    background: var(--chip-tag-bg);
    border-radius: 4px;
    padding: 1px 5px;
    line-height: 1.3;
  }

  .ctx-chip-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--chip-tag-color);
    flex: none;
  }

  .ctx-chip-target .ctx-chip-dot {
    background: var(--ctx-star);
  }

  .ctx-chip-title {
    font-weight: 600;
  }

  .ctx-chip-star {
    appearance: none;
    border: none;
    background: transparent;
    cursor: pointer;
    padding: 0;
    font-size: 13px;
    color: var(--ctx-text-3);
    line-height: 1;
    opacity: 0.55;
    transition: color 80ms linear, opacity 80ms linear;
  }

  .ctx-chip-star:hover {
    color: var(--ctx-star);
    opacity: 1;
  }

  .ctx-chip-star[aria-pressed="true"] {
    color: var(--ctx-star);
    opacity: 1;
  }

  .ctx-chip-target .ctx-chip-star {
    color: var(--ctx-star);
    opacity: 1;
  }

  .ctx-chip-remove {
    appearance: none;
    border: none;
    background: transparent;
    color: var(--ctx-text-3);
    font-size: 14px;
    line-height: 1;
    padding: 0 2px;
    cursor: pointer;
    border-radius: 3px;
  }

  .ctx-chip-remove:hover {
    background: var(--ctx-inset);
    color: var(--ctx-text);
  }

  /* --- Trigger ----------------------------------------------------- */

  .ctx-picker-anchor {
    position: relative;
    /* Flows inline with the chips as the last item in the bar's
       flex-wrap row. No align-self needed — the bar centers items. */
  }

  .ctx-add {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    padding: 4px 11px;
    border: 1px dashed var(--ctx-accent);
    background: var(--ctx-accent-soft);
    color: var(--ctx-accent-strong);
    border-radius: 8px;
    font-size: 12.5px;
    font-weight: 600;
    cursor: pointer;
    font-family: inherit;
    line-height: 1.3;
    transition: background-color 80ms linear;
  }

  .ctx-add:hover {
    background: var(--ctx-surface);
  }

  .ctx-add-plus {
    font-size: 14px;
    line-height: 1;
  }

  .compact .ctx-add {
    font-size: 12px;
    padding: 3px 9px;
  }

  /* --- Popover menu ------------------------------------------------ */

  .ctx-menu {
    /* `fixed` so the popover escapes ancestor overflow:auto/hidden
       containers (notably .metadata-panel's scroll region that was
       clipping it when this picker is hosted by ReferencePicker inside
       a lore/scene metadata field). Coordinates are JS-computed from
       the trigger's getBoundingClientRect — see positionMenu(). */
    position: fixed;
    width: 344px;
    max-width: calc(100vw - 16px);
    max-height: 420px;
    overflow-y: auto;
    background: var(--ctx-surface);
    border: 1px solid var(--ctx-border);
    border-radius: 11px;
    box-shadow: 0 8px 28px var(--ctx-shadow-pop);
    padding: 10px;
    z-index: 100;
    display: flex;
    flex-direction: column;
    gap: 7px;
  }

  .compact .ctx-menu {
    width: 280px;
    padding: 8px;
    gap: 6px;
  }

  /* Search input — pill with leading icon + trailing count/clear. */
  .ctx-search-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 11px;
    border: 1px solid var(--ctx-border-strong);
    border-radius: 9px;
    background: var(--ctx-surface);
    transition: border-color 80ms linear, border-width 0s;
  }

  .ctx-search-wrap:focus-within,
  .ctx-search-wrap.has-query {
    border-color: var(--ctx-accent);
  }

  .ctx-search-icon {
    color: var(--ctx-text-3);
    flex: none;
  }

  .ctx-search-wrap:focus-within .ctx-search-icon,
  .ctx-search-wrap.has-query .ctx-search-icon {
    color: var(--ctx-accent);
  }

  .ctx-search {
    flex: 1;
    min-width: 0;
    appearance: none;
    border: none;
    background: transparent;
    color: var(--ctx-text);
    font-size: 13px;
    padding: 0;
    font-family: inherit;
  }

  .ctx-search:focus {
    outline: none;
  }

  .ctx-search::placeholder {
    color: var(--ctx-text-3);
  }

  .ctx-search-count {
    flex: none;
    font-size: 11px;
    font-weight: 600;
    color: var(--ctx-text-3);
  }

  .ctx-search-clear {
    appearance: none;
    border: none;
    background: transparent;
    color: var(--ctx-text-3);
    font-size: 14px;
    line-height: 1;
    cursor: pointer;
    padding: 0 2px;
    border-radius: 3px;
    flex: none;
  }

  .ctx-search-clear:hover {
    background: var(--ctx-inset);
    color: var(--ctx-text);
  }

  /* --- Groups ------------------------------------------------------ */

  .ctx-group {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .ctx-group-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 9px;
    background: var(--ctx-panel-2);
    border-radius: 7px;
    cursor: pointer;
    list-style: none;
    user-select: none;
  }

  .ctx-group-bar::-webkit-details-marker {
    display: none;
  }

  .ctx-group-chevron {
    color: var(--ctx-text-3);
    font-size: 10px;
    width: 10px;
    display: inline-block;
    transition: transform 0.1s;
  }

  .ctx-group:not([open]) > .ctx-group-bar .ctx-group-chevron {
    transform: rotate(-90deg);
  }

  .ctx-group-label {
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--ctx-text-2);
  }

  .ctx-group-count {
    margin-left: auto;
    font-size: 10.5px;
    font-weight: 600;
    color: var(--ctx-text-3);
    background: var(--ctx-surface);
    border: 1px solid var(--ctx-border);
    border-radius: 999px;
    padding: 1px 8px;
    line-height: 1.3;
  }

  .ctx-group-items {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  /* --- Items ------------------------------------------------------- */

  .ctx-item {
    appearance: none;
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 6px 9px;
    border: none;
    background: transparent;
    border-radius: 7px;
    cursor: pointer;
    text-align: left;
    font-family: inherit;
    color: var(--ctx-text);
    /* --chip-base is set inline by colorStyleForRef() on the item
       button; monogram color/background derive from it. Falls back to
       neutral inset when unset. */
    --mono-color: var(--chip-base, var(--ctx-text-3));
    --mono-bg: var(--ctx-inset);
  }

  .ctx-item[style*="--chip-base"] {
    --mono-bg: color-mix(in srgb, var(--chip-base) 12%, white 88%);
  }

  :global([data-theme="dark"]) .ctx-item[style*="--chip-base"] {
    --mono-color: color-mix(in srgb, var(--chip-base) 75%, white 25%);
    --mono-bg: color-mix(in srgb, var(--chip-base) 18%, black 82%);
  }

  .ctx-item:hover:not(:disabled) {
    background: var(--ctx-panel-2);
  }

  .ctx-item:disabled {
    opacity: 0.55;
    cursor: default;
  }

  .ctx-item-mono {
    width: 20px;
    height: 20px;
    flex: none;
    border-radius: 6px;
    background: var(--mono-bg);
    color: var(--mono-color);
    font-size: 11px;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    line-height: 1;
  }

  .compact .ctx-item-mono {
    width: 19px;
    height: 19px;
    font-size: 10.5px;
  }

  .ctx-item-title {
    flex: 1;
    font-size: 13px;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .ctx-item-title mark {
    background: var(--ctx-accent-soft);
    color: var(--ctx-accent-strong);
    border-radius: 2px;
    padding: 0 1px;
    font-weight: 600;
  }

  .ctx-item-added {
    flex: none;
    font-size: 10.5px;
    font-weight: 600;
    color: var(--ctx-accent-strong);
    background: var(--ctx-accent-soft);
    border-radius: 999px;
    padding: 1px 8px;
    line-height: 1.3;
  }

  /* --- Empty states ------------------------------------------------ */

  .ctx-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 30px 22px;
    text-align: center;
  }

  .ctx-empty-icon {
    width: 38px;
    height: 38px;
    border-radius: 10px;
    background: var(--ctx-inset);
    border: 1px solid var(--ctx-border);
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--ctx-text-3);
    font-size: 18px;
    line-height: 1;
  }

  .ctx-empty-icon-svg {
    color: var(--ctx-text-3);
    opacity: 0.6;
  }

  .ctx-empty-title {
    font-size: 13px;
    color: var(--ctx-text-2);
  }

  .ctx-empty-title strong {
    color: var(--ctx-text);
    font-weight: 600;
  }

  .ctx-empty-hint {
    font-size: 12px;
    color: var(--ctx-text-3);
    line-height: 1.45;
  }
</style>
