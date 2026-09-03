<!--
  PlotArcNode — a character arc on the plot board (ADR-0080 §5 / Amendment 1). A
  character arc is the plotline's SIBLING beat-holder: a named, coloured thread
  bound to a character, holding an ordered CHANGE-beat roster (states of that
  character, realised through the plot's events) rather than a plotline's event
  beats. It is a near-exact mirror of PlotPlotlineNode — same at-rest roster /
  expand-in-place editor / serialised save chain — with three differences: the
  seedling glyph (the arc-vs-plotline discriminator, in place of the plotline's
  coloured dot), a "Whose change?" character-binding row, and no genre/family field.
  It is NEVER a card's primary/colour thread (§4), so it carries no focus toggle —
  its change-beats don't drive any board edge layer this slice (that lands with the
  card pills, 3b-ii).

  Editing loads the FULL arc entry via the actions context on expand (the board
  projection carries only beat titles + the resolved character display fields, not
  the editable character id), edits a local draft, and flushes the whole entry back
  through `actions.save`. When the context is ABSENT (its happy-dom render test), the
  node degrades to the read-only roster and never expands — imports nothing from
  @xyflow/svelte, so it mounts on its own.
-->
<script lang="ts">
  import { getContext } from "svelte";
  import { setPlotBeatDrag } from "@/lib/plot/plotDnd";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import ReferencePicker from "@/components/widgets/ReferencePicker.svelte";
  import { loreEntriesStore } from "@/lib/stores/lore";
  import { CARD_DRAG_HANDLE_CLASS, type PlotArcData } from "@/lib/plot/plotBoardLayout";
  import type { CharacterArcEntry, MetadataFieldDefinition, MetadataValue } from "@/lib/types";
  import { PLOT_ARC_ACTIONS, type PlotArcActions } from "./plotArcActions";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";

  // Svelte Flow passes the node's id/data/selection state as props. `id` is the arc
  // node id (= the arc's id) — the key the actions context expands by.
  let { id, data }: { id?: string; data: PlotArcData; selected?: boolean } = $props();

  // On-node editing actions (rename / recolour / rebind / beats). Absent in the mount
  // test → the node stays read-only (no expand).
  const actions = getContext<PlotArcActions | undefined>(PLOT_ARC_ACTIONS);

  // The already-resolved display colour (own → the bound character's → the lore kind
  // default — Amendment 1 §1), denormalised onto the board node so this never
  // re-resolves it.
  let accent = $derived(data.resolvedColorHex);

  // Expanded iff the board says THIS node is the one open. Never expands without a
  // context.
  let isExpanded = $derived(!!actions && actions.expandedId === id);

  // A beat is a drag source only once the arc exists (has a node id) — the mount-test
  // degrade has none, and there's nothing to link a beat of before it's created.
  let canDrag = $derived(!!id);

  // A locally-keyed beat while editing — same shape + rationale as PlotPlotlineNode's.
  type BeatDraft = {
    key: number;
    title: string;
    function: string;
    guidance: string;
    specifics: string;
    required: boolean;
    id: string;
  };
  let keySeq = 0;
  function toBeats(entry: CharacterArcEntry): BeatDraft[] {
    const raw = Array.isArray(entry.metadata.instance_beats) ? entry.metadata.instance_beats : [];
    return raw.map((r) => {
      const b = (r ?? {}) as Record<string, unknown>;
      return {
        key: keySeq++,
        title: typeof b.title === "string" ? b.title : "",
        function: typeof b.function === "string" ? b.function : "",
        guidance: typeof b.guidance === "string" ? b.guidance : "",
        specifics: typeof b.specifics === "string" ? b.specifics : "",
        required: b.required !== false,
        id: typeof b.id === "string" ? b.id : "",
      };
    });
  }

  // The editable draft, loaded on expand.
  let draft = $state<CharacterArcEntry | null>(null);
  let beats = $state<BeatDraft[]>([]);
  let detailsOpen = $state<Set<number>>(new Set());
  let loadError = $state<string | null>(null);
  let saving = $state(false);

  // Header kebab: Delete without expanding (no "Open in editor" — an arc has no
  // full-pane escape hatch this slice). Only rendered with an actions context.
  let menuOpen = $state(false);
  let rootEl = $state<HTMLElement | null>(null);
  function toggleMenu(): void {
    menuOpen = !menuOpen;
  }
  function closeMenu(): void {
    menuOpen = false;
  }
  function runAction(op: ((id: string) => void) | undefined): void {
    closeMenu();
    if (op && id) op(id);
  }
  $effect(() => {
    if (!menuOpen) return;
    const onDown = (e: PointerEvent) => {
      if (rootEl && !rootEl.contains(e.target as Node)) closeMenu();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeMenu();
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("pointerdown", onDown, true);
      window.removeEventListener("keydown", onKey, true);
    };
  });

  let colorId = $derived(typeof draft?.metadata.color === "string" ? (draft.metadata.color as string) : null);
  let characterId = $derived(typeof draft?.metadata.character === "string" ? (draft.metadata.character as string) : null);

  // The character-binding field: a synthetic entity_ref targeting lore:character
  // (mirrors the schema's own `character`/`pov` field definition — default_schema.py).
  const characterField = {
    name: "Character",
    type: "entity_ref",
    options: [],
    picker_config: { sources: [{ kind: "lore", expr: { type: "lore:character" } }] },
  } as MetadataFieldDefinition;

  // Load the full entry when the node expands; reset when it collapses so a re-open
  // picks up any external change. Mirrors PlotPlotlineNode's reload effect.
  $effect(() => {
    if (!actions || !isExpanded) {
      detailsOpen = new Set();
      loadError = null;
      return;
    }
    void reload();
  });

  async function reload(): Promise<void> {
    if (!actions) return;
    loadError = null;
    try {
      const entry = await actions.loadArc(id!);
      if (!isExpanded) return; // collapsed while loading — drop the result
      draft = entry;
      beats = toBeats(entry);
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e);
    }
  }

  function buildEntry(): CharacterArcEntry {
    const d = draft!;
    return {
      ...d,
      metadata: {
        ...d.metadata,
        instance_beats: beats.map((b) => {
          const beat: Record<string, MetadataValue> = {
            title: b.title,
            function: b.function,
            guidance: b.guidance,
            specifics: b.specifics,
            required: b.required,
          };
          if (b.id) beat.id = b.id;
          return beat;
        }),
      },
    };
  }

  // Serialize saves so two quick edits can't race the optimistic revision — the
  // PlotPlotlineNode pattern.
  let commitChain: Promise<void> = Promise.resolve();
  function commit(): void {
    commitChain = commitChain.then(doCommit);
  }
  async function doCommit(): Promise<void> {
    if (!draft || !actions) return;
    const target = draft;
    const entry = buildEntry();
    saving = true;
    try {
      const saved = await actions.save(entry);
      if (draft === target) {
        draft.revision = saved.revision;
        const savedBeats = Array.isArray(saved.metadata.instance_beats) ? saved.metadata.instance_beats : [];
        beats.forEach((b, i) => {
          const sid = (savedBeats[i] as { id?: unknown } | undefined)?.id;
          if (typeof sid === "string") b.id = sid;
        });
      }
    } catch {
      await reload();
    } finally {
      saving = false;
    }
  }

  // --- Edit handlers -------------------------------------------------------------

  function commitTitle(): void {
    if (!draft) return;
    if (!draft.title.trim()) draft.title = data.title;
    else commit();
  }

  function setColor(colorValue: string | null): void {
    if (!draft) return;
    if (colorValue) draft.metadata.color = colorValue;
    else delete draft.metadata.color;
    commit();
  }

  // Bind/clear the character through the DEDICATED setCharacter action (not the
  // generic draft/commit chain — the ReferencePicker commits the instant a reference
  // is picked, unlike a text field's blur-to-commit). Resync the local draft from the
  // returned saved entry so a subsequent colour/beat edit doesn't race the revision
  // this just advanced; a failure resyncs from the server instead.
  async function handleSetCharacter(value: string | string[]): Promise<void> {
    if (!draft || !actions || !id) return;
    const nextId = Array.isArray(value) ? (value[0] ?? "") : value;
    try {
      const saved = await actions.setCharacter(id, nextId);
      if (draft) {
        draft.metadata.character = saved.metadata.character;
        draft.revision = saved.revision;
      }
    } catch {
      await reload();
    }
  }

  function addBeat(): void {
    beats.push({ key: keySeq++, title: "New beat", function: "", guidance: "", specifics: "", required: true, id: "" });
    commit();
  }

  function removeBeat(index: number): void {
    const [gone] = beats.splice(index, 1);
    if (gone && detailsOpen.has(gone.key)) {
      const next = new Set(detailsOpen);
      next.delete(gone.key);
      detailsOpen = next;
    }
    commit();
  }

  function moveBeat(index: number, delta: number): void {
    const next = index + delta;
    if (next < 0 || next >= beats.length) return;
    const [moved] = beats.splice(index, 1);
    beats.splice(next, 0, moved);
    commit();
  }

  function toggleDetails(key: number): void {
    const next = new Set(detailsOpen);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    detailsOpen = next;
  }

  function onTitleKeydown(e: KeyboardEvent): void {
    if (e.key === "Enter") (e.currentTarget as HTMLInputElement).blur();
  }

  function stopPointerdown(node: HTMLElement) {
    const stop = (e: Event) => e.stopPropagation();
    node.addEventListener("pointerdown", stop);
    return { destroy: () => node.removeEventListener("pointerdown", stop) };
  }
</script>

<div
  class="plot-arc"
  class:coloured={accent}
  class:expanded={isExpanded}
  style={accent ? `--arc-accent: ${accent}` : undefined}
  bind:this={rootEl}
>
  {#if actions}
    <div class="arc-head">
      <span class="arc-drag-handle {CARD_DRAG_HANDLE_CLASS}" title="Drag to move" aria-hidden="true">
        <i class="ti ti-grip-vertical"></i>
      </span>
      <button class="arc-head-main as-toggle" aria-expanded={isExpanded} onclick={() => actions.toggleExpanded(id!)}>
        <!-- The seedling glyph (Amendment 1 §2): the arc-vs-plotline discriminator, in
             place of the plotline's coloured dot. Tinted by the resolved colour so it
             still carries the thread's identity. -->
        <span class="arc-glyph" aria-hidden="true"><i class="ti ti-seedling"></i></span>
        <span class="arc-title" title={data.title}>{data.title || "Untitled character arc"}</span>
        <span class="arc-count" title="Beats">{data.beats.length}</span>
        <GroupCaret size="xs" collapsed={!isExpanded} />
      </button>
      <button
        class="arc-kebab nodrag nopan"
        class:open={menuOpen}
        aria-label="Character arc actions"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onclick={toggleMenu}
      >
        <i class="ti ti-dots-vertical" aria-hidden="true"></i>
      </button>
    </div>
  {:else}
    <div class="arc-head">
      <span class="arc-glyph" aria-hidden="true"><i class="ti ti-seedling"></i></span>
      <span class="arc-title" title={data.title}>{data.title}</span>
      <span class="arc-count" title="Beats">{data.beats.length}</span>
    </div>
  {/if}

  <!-- The bound character, at rest (Amendment 1 §4): a single-letter avatar + name,
       read straight off the board data so it shows whether or not the node is
       expanded. An unbound arc reads as such rather than hiding the row. -->
  {#if data.characterName}
    <div class="arc-character" title={data.characterName}>
      <span class="arc-avatar" aria-hidden="true">{data.characterInitial || data.characterName.charAt(0)}</span>
      <span class="arc-character-name">{data.characterName}</span>
    </div>
  {:else}
    <p class="arc-character arc-character-empty muted">No character bound</p>
  {/if}

  {#if menuOpen && actions}
    <div class="arc-menu nodrag nopan" role="menu" aria-label="Character arc actions">
      <button role="menuitem" class="menu-item menu-danger" onclick={() => runAction(actions.onDelete)}>
        <i class="ti ti-trash" aria-hidden="true"></i> Delete character arc
      </button>
    </div>
  {/if}

  {#if isExpanded}
    <div class="arc-editor nodrag nopan nowheel" use:stopPointerdown>
      {#if loadError}
        <p class="editor-error" role="alert">Couldn't load this character arc. <button class="link-btn" onclick={() => void reload()}>Retry</button></p>
      {:else if !draft}
        <p class="muted editor-loading">Loading…</p>
      {:else}
        <label class="field">
          <span class="field-label">Name</span>
          <input
            class="name-input"
            bind:value={draft.title}
            onblur={commitTitle}
            onkeydown={onTitleKeydown}
            placeholder="Arc name"
          />
        </label>
        <div class="field character-field">
          <span class="field-label">Whose change?</span>
          <ReferencePicker
            field={characterField}
            value={characterId}
            ariaLabel="Character"
            embedded
            loreEntries={$loreEntriesStore}
            onChange={(v) => void handleSetCharacter(v)}
          />
        </div>
        <div class="field colour-field">
          <span class="field-label">Colour</span>
          <SwatchPicker value={colorId} onChange={setColor} placeholderHex={data.resolvedColorHex} />
        </div>
        <div class="beats-editor">
          <div class="beats-head">
            <span class="field-label">Change beats</span>
            <button class="mini-btn" onclick={addBeat}>
              <i class="ti ti-plus" aria-hidden="true"></i> Add beat
            </button>
          </div>
          {#if beats.length}
            <ul class="beat-rows">
              {#each beats as beat, i (beat.key)}
                <li class="beat-row">
                  <div class="beat-main">
                    <button
                      class="beat-disclose"
                      aria-expanded={detailsOpen.has(beat.key)}
                      aria-label={detailsOpen.has(beat.key) ? "Hide beat details" : "Show beat details"}
                      onclick={() => toggleDetails(beat.key)}
                    >
                      <GroupCaret collapsed={!detailsOpen.has(beat.key)} />
                    </button>
                    <input
                      class="beat-title-input"
                      bind:value={beat.title}
                      onblur={commit}
                      onkeydown={onTitleKeydown}
                      placeholder="Beat title"
                    />
                    <div class="beat-ctl">
                      <button aria-label="Move beat up" disabled={i === 0} onclick={() => moveBeat(i, -1)}>
                        <i class="ti ti-chevron-up" aria-hidden="true"></i>
                      </button>
                      <button aria-label="Move beat down" disabled={i === beats.length - 1} onclick={() => moveBeat(i, 1)}>
                        <i class="ti ti-chevron-down" aria-hidden="true"></i>
                      </button>
                      <button class="beat-remove" aria-label="Remove beat" onclick={() => removeBeat(i)}>
                        <i class="ti ti-trash" aria-hidden="true"></i>
                      </button>
                    </div>
                  </div>
                  {#if detailsOpen.has(beat.key)}
                    <div class="beat-details">
                      <label>
                        <span class="field-label">Function</span>
                        <textarea rows="2" bind:value={beat.function} onblur={commit} placeholder="What this change does for the story"></textarea>
                      </label>
                      <label>
                        <span class="field-label">Guidance</span>
                        <textarea rows="2" bind:value={beat.guidance} onblur={commit} placeholder="Authoring guidance"></textarea>
                      </label>
                      <label>
                        <span class="field-label">Specifics</span>
                        <textarea rows="2" bind:value={beat.specifics} onblur={commit} placeholder="How this change plays out in this book"></textarea>
                      </label>
                    </div>
                  {/if}
                </li>
              {/each}
            </ul>
          {:else}
            <p class="muted beats-empty">No change beats yet — add one.</p>
          {/if}
        </div>
        <div class="editor-foot">
          <p class="saving-hint muted" class:visible={saving} aria-live="polite">{saving ? "Saving…" : ""}</p>
          <div class="foot-actions">
            <button class="delete-arc" onclick={() => actions?.onDelete(id!)}>
              <i class="ti ti-trash" aria-hidden="true"></i> Delete character arc
            </button>
          </div>
        </div>
      {/if}
    </div>
  {:else if data.beats.length}
    <!-- The at-rest roster is the drag SOURCE, same gesture as a plotline's beats
         (ADR-0053 §4) — a change-beat dropped on a card links it, holder-kind
         "plot:character_arc" (ADR-0080 §4: never adopts the card's primary). -->
    <ul class="arc-beats">
      {#each data.beats as beat, i (beat.beat_id)}
        <li
          class="arc-beat nodrag nopan"
          class:draggable={canDrag}
          draggable={canDrag}
          ondragstart={(e) => id && setPlotBeatDrag(e, id, beat.beat_id, undefined, "plot:character_arc")}
        >
          {#if canDrag}
            <span class="beat-grip" aria-hidden="true">⋮⋮</span>
          {/if}
          <span class="beat-dot" class:hollow={!accent}></span>
          <span class="beat-num" aria-hidden="true">{i + 1}</span>
          <span class="beat-title" title={beat.title}>{beat.title}</span>
          <span
            class="beat-use"
            class:gap={beat.use_count === 0}
            title={beat.use_count === 1 ? "1 card fulfils this beat" : `${beat.use_count} cards fulfil this beat`}
          >{beat.use_count}</span>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="arc-empty muted">No change beats yet</p>
  {/if}
</div>

<style>
  .plot-arc {
    box-sizing: border-box;
    position: relative;
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: var(--r-lg);
    background: var(--panel);
    /* Left band echoes the arc's resolved colour, mirroring a plotline's stripe. */
    box-shadow: inset 4px 0 0 0 var(--border);
  }
  .plot-arc.coloured {
    box-shadow: inset 4px 0 0 0 var(--arc-accent);
    background: color-mix(in srgb, var(--arc-accent) 6%, var(--panel));
  }
  .plot-arc.expanded {
    border-color: var(--accent);
  }
  .arc-head {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  .arc-drag-handle {
    flex: none;
    align-self: stretch;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-left: -4px;
    padding: 0 4px;
    color: var(--text-3);
    font-size: var(--fs-lg);
    line-height: 1;
    cursor: grab;
    transition: color 120ms ease;
  }
  .plot-arc:hover .arc-drag-handle {
    color: var(--text);
  }
  .arc-drag-handle:active {
    cursor: grabbing;
  }
  .arc-head-main.as-toggle {
    appearance: none;
    display: flex;
    align-items: center;
    gap: 8px;
    flex: 1;
    min-width: 0;
    background: transparent;
    border: none;
    padding: 0;
    font: inherit;
    color: inherit;
    text-align: left;
    cursor: pointer;
  }
  .arc-glyph {
    flex: none;
    display: inline-flex;
    color: var(--arc-accent, var(--text-3));
    font-size: var(--fs-md);
    line-height: 1;
  }
  .arc-title {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .arc-count {
    flex: none;
    font-size: var(--fs-xs);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  .arc-kebab {
    appearance: none;
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 2px 4px;
    border: none;
    background: transparent;
    color: var(--text-3);
    border-radius: var(--r-sm);
    cursor: pointer;
    opacity: 0;
    transition: opacity 120ms ease;
  }
  .plot-arc:hover .arc-kebab,
  .arc-kebab:focus-visible,
  .arc-kebab.open {
    opacity: 1;
  }
  .arc-kebab:hover {
    background: var(--surface);
    color: var(--text);
  }
  .arc-menu {
    position: absolute;
    top: 36px;
    right: 8px;
    z-index: 5;
    min-width: 160px;
    display: flex;
    flex-direction: column;
    padding: 4px;
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-md);
    box-shadow: var(--elev-2);
  }
  .arc-menu .menu-item {
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
  .arc-menu .menu-item:hover {
    background: var(--surface);
  }
  .arc-menu .menu-danger {
    color: var(--danger);
  }
  .arc-menu .menu-danger:hover {
    background: var(--danger-soft);
  }
  .arc-menu .menu-danger i {
    color: var(--danger);
  }
  /* The bound character, at rest (Amendment 1 §4): a small monogram avatar + name. */
  .arc-character {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .arc-character-empty {
    margin: 0;
    font-size: var(--fs-xs);
    font-style: italic;
  }
  .arc-avatar {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--arc-accent, var(--text-3)) 70%, transparent);
    color: var(--panel);
    font-size: var(--fs-xs);
    font-weight: 600;
    line-height: 1;
    text-transform: uppercase;
  }
  .arc-character-name {
    min-width: 0;
    font-size: var(--fs-xs);
    color: var(--text-2);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .arc-beats {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .arc-beat {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  .arc-beat.draggable {
    cursor: grab;
    padding: 2px 4px;
    border-radius: var(--r-sm);
  }
  .arc-beat.draggable:hover {
    background: var(--inset);
  }
  .arc-beat.draggable:active {
    cursor: grabbing;
  }
  .beat-grip {
    flex: none;
    color: var(--text-3);
    font-size: var(--fs-xs);
    line-height: 1;
    letter-spacing: -3px;
    cursor: grab;
  }
  .arc-beat.draggable:hover .beat-grip {
    color: var(--text-2);
  }
  .beat-dot {
    flex: none;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--arc-accent, var(--text-3)) 70%, transparent);
  }
  .beat-dot.hollow {
    background: transparent;
    border: 1px solid var(--border-strong);
  }
  .beat-num {
    flex: none;
    min-width: 1.1em;
    font-size: var(--fs-xs);
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    color: var(--text-3);
  }
  .beat-title {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-sm);
    color: var(--text-2);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .beat-use {
    flex: none;
    min-width: 1.4em;
    padding: 0 4px;
    text-align: center;
    font-size: var(--fs-xs);
    font-variant-numeric: tabular-nums;
    color: var(--text-3);
    border: 1px solid transparent;
    border-radius: var(--r-sm);
  }
  .beat-use.gap {
    border-color: var(--border-strong);
  }
  .arc-empty {
    margin: 0;
    font-size: var(--fs-xs);
    font-style: italic;
  }

  /* --- Editor -------------------------------------------------------------- */
  .arc-editor {
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-height: 360px;
    overflow-y: auto;
    cursor: default;
  }
  .editor-loading,
  .editor-error {
    margin: 0;
    font-size: var(--fs-xs);
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .colour-field {
    flex-direction: row;
    align-items: center;
    gap: 8px;
  }
  .character-field {
    gap: 4px;
  }
  .field-label {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .name-input,
  .beat-title-input,
  .beat-details textarea {
    width: 100%;
    box-sizing: border-box;
    font: inherit;
    font-size: var(--fs-sm);
    color: var(--text);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    padding: 4px 6px;
  }
  .beat-details textarea {
    resize: vertical;
  }
  .beat-title-input {
    flex: 1;
    min-width: 0;
  }
  .name-input:focus,
  .beat-title-input:focus,
  .beat-details textarea:focus {
    outline: none;
    border-color: var(--accent);
  }
  .beats-editor {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .beats-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .mini-btn {
    appearance: none;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    padding: 2px 8px;
    font-size: var(--fs-xs);
    color: var(--text-2);
    cursor: pointer;
  }
  .mini-btn:hover {
    border-color: var(--accent);
    color: var(--text);
  }
  .beat-rows {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .beat-row {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .beat-main {
    display: flex;
    align-items: center;
    gap: 4px;
  }
  .beat-disclose,
  .beat-ctl button {
    appearance: none;
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--r-sm);
    color: var(--text-3);
    cursor: pointer;
    font-size: var(--fs-sm);
  }
  .beat-disclose:hover,
  .beat-ctl button:hover:not(:disabled) {
    color: var(--text);
    border-color: var(--border);
  }
  .beat-ctl {
    flex: none;
    display: flex;
    gap: 2px;
  }
  .beat-ctl button:disabled {
    opacity: 0.35;
    cursor: default;
  }
  .beat-remove:hover:not(:disabled) {
    color: var(--danger, var(--text));
    border-color: var(--danger, var(--border));
  }
  .beat-details {
    display: flex;
    flex-direction: column;
    gap: 5px;
    padding: 4px 0 4px 26px;
  }
  .beat-details label {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .editor-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    flex-wrap: wrap;
  }
  .saving-hint {
    margin: 0;
    min-height: 1em;
    font-size: var(--fs-xs);
    font-style: italic;
    opacity: 0;
    transition: opacity 120ms linear;
  }
  .saving-hint.visible {
    opacity: 1;
  }
  .foot-actions {
    display: inline-flex;
    align-items: center;
    justify-content: flex-end;
    gap: 4px;
    flex-wrap: wrap;
  }
  .delete-arc {
    appearance: none;
    flex: none;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--r-sm);
    padding: 3px 8px;
    font-size: var(--fs-xs);
    color: var(--text-3);
    cursor: pointer;
  }
  .delete-arc:hover {
    color: var(--danger, var(--text));
    border-color: var(--danger, var(--border));
  }
  .link-btn {
    appearance: none;
    background: transparent;
    border: none;
    padding: 0;
    font: inherit;
    font-size: var(--fs-xs);
    color: var(--accent);
    cursor: pointer;
    text-decoration: underline;
  }
  .muted {
    color: var(--text-3);
    font-size: var(--fs-xs);
  }
</style>
