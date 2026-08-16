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

  The plotline's colour (#863 swatch) tints its header + each beat's dot, applied as
  a CSS var so no hex literal lands in style code. A colourless plotline reads neutral
  (hollow dots), exactly as an Unassigned card does. Drawn by Svelte Flow via the
  `plotPlotline` node type.
-->
<script lang="ts">
  import { getContext } from "svelte";
  import { getSwatch } from "@/lib/utils/colors";
  import { setPlotBeatDrag } from "@/lib/plot/plotDnd";
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import { CARD_DRAG_HANDLE_CLASS, type PlotPlotlineData } from "@/lib/plot/plotBoardLayout";
  import type { MetadataValue, PlotlineEntry } from "@/lib/types";
  import { PLOT_PLOTLINE_ACTIONS, type PlotPlotlineActions } from "./plotPlotlineActions";

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

  // A locally-keyed beat while editing. The backend stamps a stable `id` on save; a
  // just-added beat has none yet, so `key` (a local monotonic id) keys the {#each} and
  // survives reorder/rename where an index or the id would not.
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
  function toBeats(entry: PlotlineEntry): BeatDraft[] {
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

  // The editable draft, loaded on expand. `draft` carries title + metadata (+ the
  // hidden lineage) + the live revision; `beats` is the keyed roster editors bind to.
  let draft = $state<PlotlineEntry | null>(null);
  let beats = $state<BeatDraft[]>([]);
  let detailsOpen = $state<Set<number>>(new Set());
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
      // Keep `draft` / `beats` across a collapse. A field blur queues its save a beat
      // before a pane-background click collapses the node; nulling the draft here would
      // make that queued save a no-op and silently drop the edit. They're invisible
      // while collapsed and overwritten by the next expand's reload — only the transient
      // UI state resets.
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
      const entry = await actions.loadPlotline(id!);
      if (!isExpanded) return; // collapsed while loading — drop the result
      draft = entry;
      beats = toBeats(entry);
    } catch (e) {
      loadError = e instanceof Error ? e.message : String(e);
    }
  }

  // Assemble the entry to save: the draft's title/metadata/lineage, with the keyed
  // beats projected back to the stored shape (local `key` stripped; `id` omitted when
  // absent so the backend mints one rather than storing an empty id).
  function buildEntry(): PlotlineEntry {
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

  // Serialize saves so two quick edits can't race the optimistic revision (the second
  // would 409 against a base the first already advanced). Each save runs after the
  // previous settles, always over the latest draft + revision.
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
      // Only reconcile if we're still editing the SAME loaded draft — a re-expand may
      // have reloaded a fresh one while this save was in flight. Advance the local
      // revision for the next save, and capture the backend-stamped beat ids positionally
      // (same order we sent) so an id-less new beat isn't re-minted on every save.
      if (draft === target) {
        draft.revision = saved.revision;
        const savedBeats = Array.isArray(saved.metadata.instance_beats) ? saved.metadata.instance_beats : [];
        beats.forEach((b, i) => {
          const sid = (savedBeats[i] as { id?: unknown } | undefined)?.id;
          if (typeof sid === "string") b.id = sid;
        });
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

  function addBeat(): void {
    beats.push({ key: keySeq++, title: "New beat", function: "", guidance: "", specifics: "", required: true, id: "" });
    commit();
  }

  function removeBeat(index: number): void {
    const [gone] = beats.splice(index, 1);
    // Reassign (not .delete()) — a plain $state Set doesn't track native mutations,
    // only reassignment, matching toggleDetails.
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
        <i class="ti ti-chevron-{isExpanded ? 'up' : 'down'} plotline-caret" aria-hidden="true"></i>
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
        <div class="beats-editor">
          <div class="beats-head">
            <span class="field-label">Beats</span>
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
                      <i class="ti ti-chevron-{detailsOpen.has(beat.key) ? 'down' : 'right'}" aria-hidden="true"></i>
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
                        <textarea rows="2" bind:value={beat.function} onblur={commit} placeholder="What this beat does for the story"></textarea>
                      </label>
                      <label>
                        <span class="field-label">Guidance</span>
                        <textarea rows="2" bind:value={beat.guidance} onblur={commit} placeholder="Authoring guidance"></textarea>
                      </label>
                      <label>
                        <span class="field-label">Specifics</span>
                        <textarea rows="2" bind:value={beat.specifics} onblur={commit} placeholder="How this beat plays out in this book"></textarea>
                      </label>
                    </div>
                  {/if}
                </li>
              {/each}
            </ul>
          {:else}
            <p class="muted beats-empty">No beats yet — add one.</p>
          {/if}
        </div>
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
  .plotline-caret {
    flex: none;
    font-size: var(--fs-sm);
    color: var(--text-3);
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
  /* In the beat-main flex row the title input must be free to shrink below its content
     width (a long beat title would otherwise push the row past the narrow node). */
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
