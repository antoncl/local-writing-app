<!--
  PlotPlotlineNode — a plotline on the plot board (ADR-0053 §3). A plotline IS a
  plot-template instance: a named, coloured thread holding an ordered beat roster.
  It renders READ-ONLY at rest (title + colour + beats), and — when its header is
  clicked — EXPANDS IN PLACE into an editor (ADR-0038 §A): rename, recolour, and
  add / remove / reorder / edit its beats. There is no separate editor pane (S2b
  retires it); the plotline is authored here on the board.

  Editing needs more than the board projection carries (that has only beat titles):
  on expand the node loads the FULL plotline entry via the actions context — the
  editable source of truth (title + metadata.color + metadata.instance_beats + the
  hidden lineage fields a save must preserve) — edits a local draft, and flushes the
  whole entry back through `actions.save`. When the context is ABSENT (its happy-dom
  render test), the node degrades to the read-only roster and never expands, exactly
  as in S2a — so it imports nothing from @xyflow/svelte and stays mountable.

  Beats are edited through the same repeating body section the NodeEditor's own body
  renders for a `list` field with prose members (#2043 slice 3, PlotBeatSections /
  BodyListSection) — not a bespoke beat editor. The node still loads the full entry
  as the draft and flushes the whole entry back; a section write lands on the draft
  immediately but the SAVE is debounced (scheduleCommit), since text sections write
  per keystroke.

  The plotline's colour (#863 swatch) tints its header + each beat's dot, applied as
  a CSS var so no hex literal lands in style code. A colourless plotline reads neutral
  (hollow dots), exactly as an Unassigned card does. Drawn by Svelte Flow via the
  `plotPlotline` node type.
-->
<script lang="ts">
  import { getContext, onDestroy } from "svelte";
  import { getSwatch } from "@/lib/utils/colors";
  import { setPlotBeatDrag } from "@/lib/plot/plotDnd";
  import { withStampedBeatIds } from "@/lib/plot/beatRoster";
  import { createDebouncedCommit } from "@/lib/plot/debouncedCommit";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import PlotBeatSections from "./PlotBeatSections.svelte";
  import { CARD_DRAG_HANDLE_CLASS, type PlotPlotlineData } from "@/lib/plot/plotBoardLayout";
  import type { EntryMetadata, PlotlineEntry } from "@/lib/types";
  import { PLOT_PLOTLINE_ACTIONS, type PlotPlotlineActions } from "./plotPlotlineActions";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";

  // Svelte Flow passes the node's id/data/selection state as props. `id` is the
  // plotline node id (= the plotline's id) — the key the actions context expands by.
  let { id, data }: { id?: string; data: PlotPlotlineData; selected?: boolean } = $props();

  // On-node editing actions (rename / recolour / beats). Absent in the mount test →
  // the node stays read-only (no expand), the S2a behaviour.
  const actions = getContext<PlotPlotlineActions | undefined>(PLOT_PLOTLINE_ACTIONS);

  // The thread colour (#863). Null for a colourless plotline → a neutral header + dots.
  let accent = $derived(getSwatch(data.color)?.hex ?? null);

  // Expanded iff the board says THIS node is the one open (independent of Svelte Flow
  // selection — plotline nodes are not selectable). Never expands without a context.
  let isExpanded = $derived(!!actions && actions.expandedId === id);

  // Focused iff this is the thread lit across the board (ADR-0053 §6). The focus toggle
  // (the eye) reflects it; the actual edge emphasis + card dimming happen in the edge
  // builder / card node. Never focused without a context (the read-only mount case).
  let isFocused = $derived(!!actions && actions.focusedId === id);

  // A beat is a drag source only once the plotline exists (has a node id): the mount-
  // test degrade has none, and there's nothing to link a beat of before it's created.
  let canDrag = $derived(!!id);

  // The editable draft, loaded on expand — carries title + metadata (+ the hidden
  // lineage) + the live revision. The draft IS the entry: PlotBeatSections edits
  // `draft.metadata` directly, no separate keyed roster to project back.
  let draft = $state<PlotlineEntry | null>(null);
  let loadError = $state<string | null>(null);
  let saving = $state(false);

  // Header kebab (#1096): surfaces Open-in-editor / Delete on the collapsed node, so
  // they no longer need the expand-and-scroll the foot-actions require. Mirrors the plot
  // card's kebab; only rendered with an actions context (never in the read-only mount).
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
  // Close on an outside pointerdown / Escape. Capture phase so a click that lands on the
  // canvas (which reselects / pans) still closes the menu first. The node is lifted above
  // its siblings while open by a pure-CSS `:has()` rule on the board (#1100), so there's no
  // elevation signal to fire here.
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

  // Load the full entry when the node expands; reset when it collapses so a re-open
  // picks up any external change. A load that resolves after a collapse is dropped.
  $effect(() => {
    if (!actions || !isExpanded) {
      // Keep `draft` across a collapse. A field blur queues its save a beat before a
      // pane-background click collapses the node; nulling the draft here would make
      // that queued save a no-op and silently drop the edit. It's invisible while
      // collapsed and overwritten by the next expand's reload.
      loadError = null;
      // The editor is going away: a section save still waiting on its debounce runs
      // now (nothing left to coalesce), so the next expand's reload reads it back.
      sectionCommit.flush();
      return;
    }
    void reload(true);
  });

  // `afterPendingSaves` (the expand path): a re-expand inside the debounce window — a
  // double-click on the header right after a keystroke — must not GET the entry before
  // the save the collapse just flushed has landed, or the stale copy would replace the
  // draft that save was made from. The failed-save resync calls it plain: it runs
  // INSIDE the chain, and waiting on the chain from there would wait on itself.
  async function reload(afterPendingSaves = false): Promise<void> {
    if (!actions) return;
    loadError = null;
    if (afterPendingSaves) await commitChain;
    try {
      const entry = await actions.loadPlotline(id!);
      if (!isExpanded) return; // collapsed while loading — drop the result
      draft = entry;
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e);
    }
  }

  // Serialize saves so two quick edits can't race the optimistic revision (the second
  // would 409 against a base the first already advanced). Each save runs after the
  // previous settles, always over the latest draft + revision.
  let commitChain: Promise<void> = Promise.resolve();
  function commit(): void {
    commitChain = commitChain.then(doCommit);
  }
  // Beat-section writes arrive per keystroke from the TipTap editors (MetadataLongTextEditor's
  // `onChange`); saving on every one would flood `actions.save`, so those writes land on
  // `draft` immediately but the SAVE is debounced. Name/colour keep their own immediate
  // commit (blur-triggered, so already infrequent).
  const SECTION_SAVE_DEBOUNCE_MS = 600;
  const sectionCommit = createDebouncedCommit(commit, SECTION_SAVE_DEBOUNCE_MS);
  onDestroy(sectionCommit.flush);
  async function doCommit(): Promise<void> {
    if (!draft || !actions) return;
    const target = draft;
    saving = true;
    try {
      // A snapshot, not the live proxy: the save carries the draft as it was when the
      // commit ran (the old buildEntry did the same); keystrokes during the flight are
      // their own debounced commit.
      const saved = await actions.save($state.snapshot(target as unknown) as PlotlineEntry);
      // Only reconcile if we're still editing the SAME loaded draft — a re-expand may
      // have reloaded a fresh one while this save was in flight. Advance the local
      // revision for the next save, and stamp the backend-minted beat ids positionally
      // (same order we sent) so an id-less new beat isn't re-minted on every save.
      if (draft === target) {
        draft.revision = saved.revision;
        const stamped = withStampedBeatIds(draft.metadata.instance_beats, saved.metadata.instance_beats);
        if (stamped) draft.metadata.instance_beats = stamped;
      }
    } catch {
      // The save failed (the provider surfaces it). Resync from the server so the next
      // edit starts from a valid revision instead of looping 409s — this reverts the
      // just-failed edit to the server's truth. Best-effort.
      await reload();
    } finally {
      saving = false;
    }
  }

  // --- Edit handlers -------------------------------------------------------------

  function commitTitle(): void {
    if (!draft) return;
    // The backend requires a non-empty title; an emptied field reverts rather than 400s.
    if (!draft.title.trim()) draft.title = data.title;
    else commit();
  }

  function setColor(id: string | null): void {
    if (!draft) return;
    if (id) draft.metadata.color = id;
    else delete draft.metadata.color;
    commit();
  }

  function applySectionMetadata(metadata: EntryMetadata): void {
    if (!draft) return;
    draft.metadata = metadata;
    sectionCommit.schedule();
  }

  function onTitleKeydown(e: KeyboardEvent): void {
    if (e.key === "Enter") (e.currentTarget as HTMLInputElement).blur();
  }

  // Stop pointerdown NATIVELY (Svelte's delegated onpointerdown fires at the root —
  // too late to beat Svelte Flow's node-select/drag listener on an ancestor). Applied
  // to the editor so typing / clicking a control never drags or reselects the node.
  function stopPointerdown(node: HTMLElement) {
    const stop = (e: Event) => e.stopPropagation();
    node.addEventListener("pointerdown", stop);
    return { destroy: () => node.removeEventListener("pointerdown", stop) };
  }
</script>

<div
  class="plot-plotline"
  class:coloured={accent}
  class:expanded={isExpanded}
  style={accent ? `--plotline-accent: ${accent}` : undefined}
  bind:this={rootEl}
>
  {#if actions}
    <!-- The header row: a leading drag grip, then an eye toggle that FOCUSES this thread
         across the board (ADR-0053 §6), then the expand toggle (dot + title + beat count +
         caret). The node drags ONLY by the grip (#876, `dragHandle`), so the eye + expand
         buttons are pure clicks; they keep `nodrag nopan` as belt-and-suspenders. -->
    <div class="plotline-head">
      <!-- The drag handle (#876): the same leading grip a card uses, so every card-like
           node drags the same way. Here it also DISENTANGLES drag from the header — the
           title row is a click-to-expand button, so a whole-body drag surface would have
           made a grab and an expand fight over it. SvelteFlow's `dragHandle` targets this grip. -->
      <span class="plotline-drag-handle {CARD_DRAG_HANDLE_CLASS}" title="Drag to move" aria-hidden="true">
        <i class="ti ti-grip-vertical"></i>
      </span>
      <button
        class="plotline-focus nodrag nopan"
        class:active={isFocused}
        aria-pressed={isFocused}
        title={isFocused ? "Clear focus — show all threads" : "Focus this thread across the board"}
        aria-label={isFocused ? "Clear focus" : "Focus this thread"}
        onclick={() => actions.toggleFocus(id!)}
      >
        <i class="ti ti-eye" aria-hidden="true"></i>
      </button>
      <button class="plotline-head-main as-toggle" aria-expanded={isExpanded} onclick={() => actions.toggleExpanded(id!)}>
        <span class="plotline-dot" class:hollow={!accent}></span>
        <span class="plotline-title" title={data.title}>{data.title || "Untitled plotline"}</span>
        <span class="plotline-count" title="Beats">{data.beats.length}</span>
        <GroupCaret size="xs" collapsed={!isExpanded} />
      </button>
      <!-- Actions kebab (#1096): Open-in-editor / Delete without expanding, mirroring the
           plot card's kebab. Quiet until node hover / focus / open (the card idiom). -->
      <button
        class="plotline-kebab nodrag nopan"
        class:open={menuOpen}
        aria-label="Plotline actions"
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onclick={toggleMenu}
      >
        <i class="ti ti-dots-vertical" aria-hidden="true"></i>
      </button>
    </div>
  {:else}
    <div class="plotline-head">
      <span class="plotline-dot" class:hollow={!accent}></span>
      <span class="plotline-title" title={data.title}>{data.title}</span>
      <span class="plotline-count" title="Beats">{data.beats.length}</span>
    </div>
  {/if}

  {#if menuOpen && actions}
    <!-- Rendered as a direct child (not inside the scrolling editor) so the node's
         overflow can't clip it; the board lifts this node's z-index while it's open. -->
    <div class="plotline-menu nodrag nopan" role="menu" aria-label="Plotline actions">
      {#if actions.onOpenInEditor}
        <button role="menuitem" class="menu-item" onclick={() => runAction(actions.onOpenInEditor)}>
          <i class="ti ti-pencil" aria-hidden="true"></i> Open in editor
        </button>
      {/if}
      <div class="menu-sep" role="separator"></div>
      <button role="menuitem" class="menu-item menu-danger" onclick={() => runAction(actions.onDelete)}>
        <i class="ti ti-trash" aria-hidden="true"></i> Delete plotline
      </button>
    </div>
  {/if}

  {#if isExpanded}
    <!-- The editor. `nodrag nopan nowheel` + a native pointerdown stop keep Svelte
         Flow from dragging / panning / zooming the board while editing. -->
    <div class="plotline-editor nodrag nopan nowheel" use:stopPointerdown>
      {#if loadError}
        <p class="editor-error" role="alert">Couldn't load this plotline. <button class="link-btn" onclick={() => void reload()}>Retry</button></p>
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
            placeholder="Plotline name"
          />
        </label>
        <div class="field colour-field">
          <span class="field-label">Colour</span>
          <SwatchPicker value={colorId} onChange={setColor} />
        </div>
        <PlotBeatSections entry={draft} onChange={applySectionMetadata} />
        <div class="editor-foot">
          <p class="saving-hint muted" class:visible={saving} aria-live="polite">{saving ? "Saving…" : ""}</p>
          <div class="foot-actions">
            {#if actions?.onOpenInEditor}
              <!-- Escape hatch (ADR-0053 §3): the roomier full-pane editor for beat work
                   that is crowded on the card. On-node editing stays the default. -->
              <button class="open-in-editor" onclick={() => actions?.onOpenInEditor?.(id!)}>
                <i class="ti ti-pencil" aria-hidden="true"></i> Open in editor
              </button>
            {/if}
            <!-- Delete moved off the retired Plotlines rail onto the node (ADR-0053 §3). -->
            <button class="delete-plotline" onclick={() => actions?.onDelete(id!)}>
              <i class="ti ti-trash" aria-hidden="true"></i> Delete plotline
            </button>
          </div>
        </div>
      {/if}
    </div>
  {:else if data.beats.length}
    <!-- The at-rest roster is the drag SOURCE (ADR-0053 §4): drag a beat onto a story
         card to link it (#824, re-homed from the retired Arcs rail). `nodrag nopan`
         (the board's interactive-control convention) keeps grabbing a beat from moving
         the node or panning the canvas; the drag writes the (plotline id, beat id)
         payload. Draggable only once the plotline exists (canDrag). -->
    <ul class="plotline-beats">
      {#each data.beats as beat, i (beat.beat_id)}
        <li
          class="plotline-beat nodrag nopan"
          class:draggable={canDrag}
          draggable={canDrag}
          ondragstart={(e) => id && setPlotBeatDrag(e, id, beat.beat_id)}
        >
          <!-- Drag handle (#911): the grip signals "drag me onto a card" the way the
               mockup does; shown only when the beat is actually draggable. Decorative. -->
          {#if canDrag}
            <span class="beat-grip" aria-hidden="true">⋮⋮</span>
          {/if}
          <span class="beat-dot" class:hollow={!accent}></span>
          <!-- The beat's roster number (#941), matching the badge shown on cards. -->
          <span class="beat-num" aria-hidden="true">{i + 1}</span>
          <span class="beat-title" title={beat.title}>{beat.title}</span>
          <!-- Use-count (ADR-0053 §6 / S5a): how many cards fulfil this beat. A 0 reads
               as a gap the structure exposes. -->
          <span
            class="beat-use"
            class:gap={beat.use_count === 0}
            title={beat.use_count === 1 ? "1 card fulfils this beat" : `${beat.use_count} cards fulfil this beat`}
          >{beat.use_count}</span>
        </li>
      {/each}
    </ul>
  {:else}
    <p class="plotline-empty muted">No beats yet</p>
  {/if}
</div>

<style>
  .plot-plotline {
    box-sizing: border-box;
    /* Positioning context for the absolutely-placed actions menu (#1096). */
    position: relative;
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: var(--r-lg);
    background: var(--panel);
    /* Left band echoes the plotline colour (the #863 card-stripe signature), so a
       plotline reads as the same thread its cards are tinted by. Neutral when
       colourless. */
    box-shadow: inset 4px 0 0 0 var(--border);
  }
  .plot-plotline.coloured {
    box-shadow: inset 4px 0 0 0 var(--plotline-accent);
    background: color-mix(in srgb, var(--plotline-accent) 6%, var(--panel));
  }
  .plot-plotline.expanded {
    border-color: var(--accent);
  }
  .plotline-head {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }
  /* The drag handle (#876): the app's standard grip icon a card also carries, so every
     card-like node drags identically. `align-self: stretch` + side padding make a
     GENEROUS hit target (full header height, ~16px wide), not a sliver. Quiet at rest,
     brightening on node hover; `grab`/`grabbing` cursor. */
  .plotline-drag-handle {
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
  .plot-plotline:hover .plotline-drag-handle {
    color: var(--text);
  }
  .plotline-drag-handle:active {
    cursor: grabbing;
  }
  /* The title area doubles as the expand toggle — reset button chrome to look like the
     read-only header, with a pointer cue. Takes the row's remaining width beside the
     eye. */
  .plotline-head-main.as-toggle {
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
  /* The focus (eye) toggle: a quiet icon button that lights this thread across the
     board. Reads muted at rest, accent when this thread is the focused one. */
  .plotline-focus {
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
  .plotline-focus:hover {
    color: var(--text);
    border-color: var(--border);
  }
  .plotline-focus.active {
    color: var(--accent);
    border-color: var(--accent);
  }
  .plotline-dot {
    flex: none;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--plotline-accent, var(--text-3));
  }
  .plotline-dot.hollow {
    background: transparent;
    border: 1.5px solid var(--border-strong);
  }
  .plotline-title {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .plotline-count {
    flex: none;
    font-size: var(--fs-xs);
    color: var(--text-3);
    font-variant-numeric: tabular-nums;
  }
  /* Actions kebab (#1096): quiet until node hover / focus / menu-open. Sized identically to
     the plot card's kebab (#1100) — icon-plus-padding, not a fixed box — so the dots read the
     same on both node kinds. */
  .plotline-kebab {
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
  .plot-plotline:hover .plotline-kebab,
  .plotline-kebab:focus-visible,
  .plotline-kebab.open {
    opacity: 1;
  }
  .plotline-kebab:hover {
    background: var(--surface);
    color: var(--text);
  }
  /* The actions menu, rendered outside the node's flow so overflow can't clip it; the
     board lifts the node's z-index while it's open (#1095). Mirrors the plot card menu. */
  .plotline-menu {
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
  .plotline-menu .menu-item {
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
  .plotline-menu .menu-item:hover {
    background: var(--surface);
  }
  .plotline-menu .menu-item i {
    color: var(--text-3);
  }
  .plotline-menu .menu-sep {
    height: 1px;
    margin: 4px 2px;
    background: var(--divider);
  }
  .plotline-menu .menu-danger {
    color: var(--danger);
  }
  .plotline-menu .menu-danger:hover {
    background: var(--danger-soft);
  }
  .plotline-menu .menu-danger i {
    color: var(--danger);
  }
  .plotline-beats {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 3px;
  }
  .plotline-beat {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }
  /* A draggable beat grabs onto a card (ADR-0053 §4). A chip-ish hover + a leading
     grip (#911) telegraph "grab me onto a card" the way the mockup does. The padding
     insets the row content (never widens the li), so the hover fill can't overflow the
     node's rounded box. */
  .plotline-beat.draggable {
    cursor: grab;
    padding: 2px 4px;
    border-radius: var(--r-sm);
  }
  .plotline-beat.draggable:hover {
    background: var(--inset);
  }
  .plotline-beat.draggable:active {
    cursor: grabbing;
  }
  /* The drag handle — a quiet grip, the two glyphs tightened so they read as one
     6-dot grip. Only rendered on a draggable beat. */
  .beat-grip {
    flex: none;
    color: var(--text-3);
    font-size: var(--fs-xs);
    line-height: 1;
    letter-spacing: -3px;
    cursor: grab;
  }
  .plotline-beat.draggable:hover .beat-grip {
    color: var(--text-2);
  }
  .beat-dot {
    flex: none;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--plotline-accent, var(--text-3)) 70%, transparent);
  }
  .beat-dot.hollow {
    background: transparent;
    border: 1px solid var(--border-strong);
  }
  /* The beat's roster number (#941), matching the card badge; tabular so a column of
     rows aligns, quiet so the title still leads. */
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
  /* Per-beat use-count (S5a): a quiet number at the row's end. A 0 is a gap, flagged
     with a hollow outline (echoing the hollow beat-dot) rather than a loud colour. */
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
  .plotline-empty {
    margin: 0;
    font-size: var(--fs-xs);
    font-style: italic;
  }

  /* --- Editor -------------------------------------------------------------- */
  .plotline-editor {
    display: flex;
    flex-direction: column;
    gap: 8px;
    /* A tall roster scrolls inside the node (nowheel keeps the board from zooming). */
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
  .field-label {
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .name-input {
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
  .name-input:focus {
    outline: none;
    border-color: var(--accent);
  }
  .editor-foot {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    /* The node is a fixed, narrow PLOTLINE_WIDTH; the saving hint + two labelled action
       buttons don't fit on one line, so let the actions wrap below rather than push a
       horizontal scrollbar into the node (#945 — expanded-plotline overflow). */
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
    /* Stack the two buttons if even alone they exceed the narrow node width. */
    flex-wrap: wrap;
  }
  .open-in-editor,
  .delete-plotline {
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
  .open-in-editor:hover {
    color: var(--text);
    border-color: var(--border);
  }
  .delete-plotline:hover {
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
</style>
