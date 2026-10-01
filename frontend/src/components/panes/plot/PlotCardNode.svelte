<!--
  PlotCardNode — a card on the plot board (ADR-0048 S7b read-only → S7d interactive).
  Still imports NOTHING from @xyflow/svelte (a card has no connection ports of its own —
  the causal handles live on the PlotCardNodeFlow wrapper), so it stays mountable in
  happy-dom for its render test ([[reference_component_test_harness]]). Interactivity
  arrives via a Svelte context (PlotEditor provides the handlers); when it is absent —
  the S7b read-only case and the mount test — the card renders read-only, no actions.

  Beat links are authored by DRAGGING a beat from the Arcs palette onto the card (#824):
  the card is an HTML5 drop target and each beat badge carries an × to unlink. Causal
  edges are drawn card-to-card via the wrapper's handles (SvelteFlow), not here.

  Interactive controls carry `nodrag nopan` so a click/type inside them never starts a
  canvas drag or pan (the xyflow convention). The action menu renders OUTSIDE the
  clipped `.plot-card` so it isn't cut off by the card's fixed height / overflow.
-->
<script lang="ts">
  import { getContext, tick } from "svelte";
  import { getSwatch } from "@/lib/utils/colors";
  import { findNodeBySceneId, isLeafNode } from "@/lib/utils/treeHelpers";
  import { CARD_DRAG_HANDLE_CLASS, type PlotCardData } from "@/lib/plot/plotBoardLayout";
  import type { PlotCardBeat } from "@/lib/types";
  import type { StoryAnchor } from "@/lib/api/plot";
  import { lateCauseTitle } from "@/lib/plot/storyTime";
  import type { NodePickerConfig, NodePickerRef } from "@/lib/pickerTypes";
  import { PLOT_CARD_ACTIONS, type PlotCardActions } from "./plotCardActions";
  import { hasPlotBeatDrag, readPlotBeatDrag, setPlotBeatDrag } from "@/lib/plot/plotDnd";
  import GroupCaret from "@/components/widgets/GroupCaret.svelte";
  import NodePicker from "@/components/widgets/NodePicker.svelte";

  // Svelte Flow passes the node's id/data/selection state as props.
  let { id, data }: { id?: string; data: PlotCardData; selected?: boolean } = $props();

  // Absent in the read-only board (S7b) and in the happy-dom mount test → the card
  // shows no kebab / edit / drop affordance, unchanged from S7b.
  const actions = getContext<PlotCardActions | undefined>(PLOT_CARD_ACTIONS);

  // The owning plotline's colour, as a left stripe. Null for a colourless plotline
  // or the Unassigned lane. Applied as a CSS var, so no hex literal lands in style code.
  let accent = $derived(getSwatch(data.color)?.hex ?? null);

  // Per-plotline FOCUS (ADR-0053 §6, S5b; #911): when a thread is focused, its cards
  // are LIT (outlined so they pop) and every other card recedes (dimmed) — the mockup's
  // focus treatment. A card is ON the thread when the focused plotline is its primary OR
  // one of the beats it fulfils. Reads the focus through the actions getter, so it tracks
  // reactively and stays inert with no context (mount test → never lit/dimmed).
  let onFocusedThread = $derived.by(() => {
    const focus = actions?.focusedPlotlineId ?? null;
    if (!focus) return false;
    return data.plotlineId === focus || data.beats.some((b) => b.plotline_id === focus);
  });
  let focusActive = $derived((actions?.focusedPlotlineId ?? null) !== null);
  // A selected diagnostic finding (ADR-0048 S7) lights its own cards and dims the rest
  // — the same treatment as thread focus, keyed on a card-id set. It takes precedence
  // (the two are never active together). Null/empty ⇒ fall back to plotline focus.
  let highlightSet = $derived(actions?.highlightedCardIds ?? null);
  let highlightActive = $derived((highlightSet?.size ?? 0) > 0);
  let lit = $derived(
    highlightActive ? !!id && highlightSet!.has(id) : focusActive && onFocusedThread,
  );
  let dimmed = $derived(
    highlightActive ? !(!!id && highlightSet!.has(id)) : focusActive && !onFocusedThread,
  );

  // The 3-state page marker (Slice 5b): on_page (scene attached) / off_page / unwritten.
  // The layout resolves the value, its label and its swatch from the schema's
  // `page_status` options (#1907); the dot colour is applied as a CSS var (no hex in style).
  let pageStatus = $derived(data.pageStatus);
  let statusColor = $derived(data.pageStatusSwatch ? (getSwatch(data.pageStatusSwatch)?.hex ?? null) : null);

  // Two pill kinds (ADR-0080 slice 3b-ii) share one foot row: event-pills (plotline
  // beats) first, then change-pills (character-arc beats, avatar + seedling glyph), so
  // "who changes" stays distinguishable from "what happens" without section labels.
  let orderedBeats = $derived([
    ...data.beats.filter((b) => b.holder_kind !== "plot:character_arc"),
    ...data.beats.filter((b) => b.holder_kind === "plot:character_arc"),
  ]);

  // Read-only: show the first few pills, then a "+N" chip for the rest — so a card
  // with many beats never silently hides them (the chip's tooltip names the overflow).
  // An interactive card shows every beat.
  const BEAT_BADGE_CAP = 4;
  let visibleBeats = $derived<PlotCardBeat[]>(actions ? orderedBeats : orderedBeats.slice(0, BEAT_BADGE_CAP));
  let hiddenBeats = $derived<PlotCardBeat[]>(actions ? [] : orderedBeats.slice(BEAT_BADGE_CAP));

  // The Attach picker browses the manuscript's scenes (ADR-0097 §4).
  const ATTACH_PICKER: NodePickerConfig = { sources: [{ kind: "manuscript", expr: { type: "manuscript:scene" } }] };

  let menuOpen = $state(false);
  // Five pages: the actions, the "Set plotline" lane list, the "Write as scene"
  // location list (#879), and "Place after…" — the story-time anchor list (ADR-0097 §8).
  // Beats + causal are no longer menu pages — they're drag gestures now (#824).
  let menuView = $state<"main" | "plotline" | "location" | "place" | "leads">("main");

  let editing = $state(false);
  let draft = $state("");
  let textarea = $state<HTMLTextAreaElement | null>(null);
  let rootEl = $state<HTMLElement | null>(null);

  // Close the menu on an outside pointerdown or Escape — NOT on focusout, which would
  // fire (and wrongly close) the moment the two-page menu swaps pages and removes the
  // focused button. Only while open, cleaned up on close / unmount.
  $effect(() => {
    if (!menuOpen) return;
    const onDown = (e: PointerEvent) => {
      // The Attach picker's popover is portaled to <body> (outside the card), so a press
      // inside it is not an outside press.
      if ((e.target as Element | null)?.closest?.(".ctx-menu")) return;
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

  function toggleMenu() {
    if (menuOpen) {
      closeMenu();
    } else {
      menuView = "main";
      menuOpen = true;
    }
  }
  function closeMenu() {
    menuOpen = false;
    menuView = "main";
    placeFilter = "";
  }
  // Story time (ADR-0097 §8): Earlier / Later swap with a neighbour; "Place after…"
  // lists the other cards (filterable), the picked one becoming the anchor.
  let placeFilter = $state("");
  let placeChoices = $derived(
    (actions?.storyAnchors ?? []).filter(
      (c) => c.id !== id && c.title.toLowerCase().includes(placeFilter.trim().toLowerCase()),
    ),
  );
  function storyMove(anchor: StoryAnchor) {
    closeMenu();
    if (actions && id) actions.onStoryMove(id, anchor);
  }
  function run(op: ((cardId: string) => void) | undefined) {
    closeMenu();
    if (op && id) op(id);
  }
  // Remove one outgoing causal link (#2402). Stays on the page so several can go; an
  // emptied list drops back to the main page (the item hides with no links left).
  function unlinkCausal(targetId: string) {
    if (actions && id) actions.onUnlinkCausal(id, targetId);
    if (data.leadsTo.length <= 1) menuView = "main";
  }
  function setPlotline(plotlineId: string) {
    closeMenu();
    if (actions && id) actions.onSetPlotline(id, plotlineId);
  }
  // Realize into a chosen manuscript container (#879). null defers to the backend's
  // first-container default — used when the project has no containers to pick from.
  function realizeAt(parentId: string | null) {
    closeMenu();
    if (actions && id) actions.onRealize(id, parentId);
  }
  // A pick in the Attach picker. The tree also lets a container be checked; only a
  // scene is attachable, so a container pick is ignored (the picker stays open).
  function attachPicked(detail: { value: NodePickerRef[] }) {
    if (!actions || !id) return;
    const root = actions.structure?.root;
    const scene = detail.value.find((r) => {
      const node = root ? findNodeBySceneId(root, r.id) : null; // a container ref carries the node id, so misses
      return r.kind === "manuscript" && !!node && isLeafNode(node);
    });
    if (!scene) return;
    closeMenu();
    actions.onAttach(id, scene.id);
  }
  function setPageStatus(status: "off_page" | "unwritten") {
    closeMenu();
    if (actions && id) actions.onSetPageStatus(id, status);
  }

  // --- Beat linking by drag (#824). The card accepts a beat dragged from the Arcs
  // palette; dropping links it. `dragOver` drives the accept-highlight. Only an
  // interactive card (actions present) accepts drops.
  let dragOver = $state(false);
  function onCardDragOver(e: DragEvent) {
    if (!actions || !hasPlotBeatDrag(e)) return;
    e.preventDefault(); // allow the drop
    // A badge drag carries effectAllowed="move" (from another card); a plotline-node
    // drag is "copy" (a fresh link). Mirror it so the cursor reads move vs copy.
    if (e.dataTransfer) e.dataTransfer.dropEffect = e.dataTransfer.effectAllowed === "move" ? "move" : "copy";
    dragOver = true;
  }
  function onCardDragLeave(e: DragEvent) {
    // dragleave fires when crossing into a child too — ignore those so the highlight
    // doesn't flicker; only a leave that exits the card clears it.
    if ((e.currentTarget as Node).contains(e.relatedTarget as Node | null)) return;
    dragOver = false;
  }
  function onCardDrop(e: DragEvent) {
    dragOver = false;
    if (!actions || !id) return;
    const payload = readPlotBeatDrag(e);
    if (!payload) return;
    e.preventDefault();
    // A badge dragged from ANOTHER card (`from`) MOVES the link here (#941); a drag from
    // the plotline node (no `from`), or a badge dropped back on its own card, just links.
    if (payload.from && payload.from !== id) {
      actions.onMoveBeat(payload.from, id, payload.plotline, payload.beat_id);
    } else if (payload.holder_kind) {
      // A change-beat (ADR-0080 §4): thread the holder kind through so the link path
      // skips primary-adoption. Omitted for the (still far more common) plotline drag,
      // whose payload carries no `holder_kind` at all (plotDnd's wire economy).
      actions.onLinkBeat(id, payload.plotline, payload.beat_id, payload.holder_kind);
    } else {
      actions.onLinkBeat(id, payload.plotline, payload.beat_id);
    }
  }
  function unlinkBeat(instanceId: string, beatId: string) {
    if (actions && id) actions.onUnlinkBeat(id, instanceId, beatId);
  }
  // Start dragging a beat badge OFF this card (#941): carry the source card id so the
  // drop target moves the link rather than duplicating it. Only on an interactive card.
  // `holderKind` (ADR-0080 §4) rides along so a re-dragged CHANGE-beat badge (an arc
  // holder) still skips primary-adoption on the target card — without it, the move would
  // adopt the arc as the target's primary and the backend would 422 the save.
  function onBeatDragStart(e: DragEvent, plotline: string, beatId: string, holderKind: string) {
    if (actions && id) {
      setPlotBeatDrag(e, plotline, beatId, id, holderKind === "plot:character_arc" ? "plot:character_arc" : "plot:plotline");
    }
  }

  async function startEdit() {
    if (!actions) return;
    draft = data.synopsis;
    editing = true;
    await tick();
    textarea?.focus();
  }
  function commitEdit() {
    editing = false;
    const next = draft.trim();
    // Compare against the TRIMMED body: the projection's synopsis is the raw card
    // body, which the backend stores with a trailing newline, so a plain `!==` would
    // treat every no-op open/close as a change and re-save forever.
    if (actions && id && next !== data.synopsis.trim()) actions.onEditSynopsis(id, next);
  }
  // Escape cancels: reset the draft to the saved body, so the blur that fires when
  // the textarea unmounts commits nothing (next === the saved value).
  function cancelEdit() {
    draft = data.synopsis;
    editing = false;
  }

  // Inline title (name) editing (#798) — the same click-to-edit pattern as the
  // synopsis, so a card can be named on the board without opening the editor.
  let titleEditing = $state(false);
  let titleDraft = $state("");
  let titleInput = $state<HTMLInputElement | null>(null);

  async function startTitleEdit() {
    if (!actions) return;
    titleDraft = data.title;
    titleEditing = true;
    await tick();
    titleInput?.select();
  }
  function commitTitle() {
    titleEditing = false;
    const next = titleDraft.trim();
    // A card title must be non-empty (the backend rejects ""), so an emptied name
    // reverts to the saved title; otherwise save only a real change.
    if (actions && id && next && next !== data.title) actions.onEditTitle(id, next);
  }
  // Escape cancels: reset the draft so the unmount blur commits nothing.
  function cancelTitle() {
    titleDraft = data.title;
    titleEditing = false;
  }
</script>

<div class="card-root" bind:this={rootEl}>
  <!-- svelte-ignore a11y_no_static_element_interactions -- the card is an HTML5 drop
       target for beats; the keyboard path to link is the Arcs editor, not this drop. -->
  <article
    class="plot-card"
    class:accented={accent}
    class:planned={data.planned}
    class:drag-over={dragOver}
    class:lit={lit}
    class:dimmed={dimmed && !dragOver}
    class:raised={!!id && actions?.raisedCardId === id}
    style={accent ? `--card-accent: ${accent}` : undefined}
    onpointerdowncapture={() => {
      // Any press on the card — its grip, title, synopsis, pills — brings it to the
      // front (#2363). Capture phase, so a control that stops propagation still raises.
      if (actions && id && actions.raisedCardId !== id) actions.onRaise(id);
    }}
    ondragover={onCardDragOver}
    ondragleave={onCardDragLeave}
    ondrop={onCardDrop}
  >
    <div class="card-head">
      {#if actions}
        <!-- The drag handle (#876): the card drags ONLY by this grip (SvelteFlow's
             `dragHandle` targets it), leaving the whole body free for its inline-edit
             controls. Present only on an interactive board (actions) — the read-only
             mount case never drags. The app's standard grip icon (as SchemaFieldRow's
             "Drag to reorder"); decorative + pointer-only, like every board drag. -->
        <span class="card-drag-handle {CARD_DRAG_HANDLE_CLASS}" title="Drag to move" aria-hidden="true">
          <i class="ti ti-grip-vertical"></i>
        </span>
      {/if}
      {#if titleEditing}
        <input
          bind:this={titleInput}
          bind:value={titleDraft}
          class="card-title-edit nodrag nopan"
          placeholder="Card name"
          onblur={commitTitle}
          onkeydown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              e.currentTarget.blur();
            } else if (e.key === "Escape") {
              cancelTitle();
            }
          }}
        />
      {:else if actions}
        <button class="card-title card-title-btn nodrag nopan" title="Click to rename" onclick={startTitleEdit}>
          <span class="card-title-text">{data.title || "Untitled card"}</span>
        </button>
      {:else}
        <h4 class="card-title" title={data.title}><span class="card-title-text">{data.title || "Untitled card"}</span></h4>
      {/if}
      {#if actions}
        <button
          class="card-kebab nodrag nopan"
          class:open={menuOpen}
          aria-label="Card actions"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onclick={toggleMenu}
        >
          <i class="ti ti-dots-vertical" aria-hidden="true"></i>
        </button>
      {/if}
    </div>

    {#if editing}
      <textarea
        bind:this={textarea}
        bind:value={draft}
        class="card-synopsis-edit nodrag nopan"
        placeholder={data.attached ? "No summary yet" : "Add a synopsis…"}
        onblur={commitEdit}
        onkeydown={(e) => {
          if (e.key === "Escape") cancelEdit();
        }}
      ></textarea>
    {:else if actions}
      <button
        class="card-synopsis card-synopsis-btn nodrag nopan nowheel"
        class:empty={!data.synopsis}
        title="Click to edit the synopsis"
        onclick={startEdit}
      >
        {data.synopsis || (data.attached ? "No summary yet" : "Add a synopsis…")}
      </button>
    {:else if data.synopsis}
      <p class="card-synopsis">{data.synopsis}</p>
    {/if}

    <!-- ONE compact foot row (#2354): the beat pills (event pills, then change pills)
         wrap on the left, the plotline + page-status dots sit right-aligned. Interactive:
         show EVERY beat, each with its × — the row is a wheel-safe (`nowheel`, so the
         canvas doesn't zoom) bounded scroll so even a heavily-beated card can unlink any
         of them. Read-only keeps the compact cap + "+N". -->
    <div class="card-foot">
      {#if orderedBeats.length}
        <div class="card-beats" class:editable={actions} class:nowheel={actions} aria-label="Beats">
          {#each visibleBeats as beat (beat.plotline_id + ":" + beat.beat_id)}
            {#if beat.holder_kind === "plot:character_arc"}
              <!-- Change-pill (ADR-0080 §5 / Amendment 1): a character-arc beat — a seedling
                   glyph + the bound character's single-letter avatar in the arc's resolved
                   colour, distinguishing "who changes" from "what happens". -->
              <span
                class="beat-badge change"
                class:coloured={beat.resolvedColorHex}
                class:draggable={actions}
                style={beat.resolvedColorHex ? `--beat-accent: ${beat.resolvedColorHex}` : undefined}
                title={`${beat.character_name ?? "Unbound"} · ${beat.title}`}
                class:nodrag={actions}
                class:nopan={actions}
                draggable={!!actions}
                ondragstart={(e) => onBeatDragStart(e, beat.plotline_id, beat.beat_id, beat.holder_kind)}
              >
                {#if actions}
                  <span class="beat-badge-grip" aria-hidden="true"><i class="ti ti-grip-vertical"></i></span>
                {/if}
                <span class="avatar" aria-hidden="true"
                  >{beat.character_initial || (beat.character_name ? beat.character_name.charAt(0) : "?")}</span
                >
                <span class="seed" aria-hidden="true"><i class="ti ti-seedling"></i></span>
                <span class="beat-badge-label">{beat.title}</span>
                <span class="beat-badge-num" aria-hidden="true">{beat.number}</span>
                {#if actions}
                  <button
                    class="beat-badge-x nodrag nopan"
                    aria-label={`Unlink beat ${beat.title}`}
                    onclick={() => unlinkBeat(beat.plotline_id, beat.beat_id)}
                  >
                    <i class="ti ti-x" aria-hidden="true"></i>
                  </button>
                {/if}
              </span>
            {:else}
              <span
                class="beat-badge"
                class:coloured={beat.resolvedColorHex}
                class:draggable={actions}
                style={beat.resolvedColorHex ? `--beat-accent: ${beat.resolvedColorHex}` : undefined}
                title={`${beat.plotline_title} · ${beat.number}. ${beat.title}`}
                class:nodrag={actions}
                class:nopan={actions}
                draggable={!!actions}
                ondragstart={(e) => onBeatDragStart(e, beat.plotline_id, beat.beat_id, beat.holder_kind)}
              >
                {#if actions}
                  <!-- A leading grip signals the badge drags card→card (#941 follow-up), the
                       same affordance the plotline roster + card grip use. Only interactive. -->
                  <span class="beat-badge-grip" aria-hidden="true"><i class="ti ti-grip-vertical"></i></span>
                {/if}
                <span class="beat-badge-label">{beat.title}</span>
                <!-- The beat's roster number (#941), POSTFIXED so the title leads, so two
                     same-titled beats are still tellable apart. -->
                <span class="beat-badge-num" aria-hidden="true">{beat.number}</span>
                {#if actions}
                  <button
                    class="beat-badge-x nodrag nopan"
                    aria-label={`Unlink beat ${beat.title}`}
                    onclick={() => unlinkBeat(beat.plotline_id, beat.beat_id)}
                  >
                    <i class="ti ti-x" aria-hidden="true"></i>
                  </button>
                {/if}
              </span>
            {/if}
          {/each}
          {#if hiddenBeats.length}
            <span class="beat-badge beat-more" title={hiddenBeats.map((b) => b.title).join(", ")}
              >+{hiddenBeats.length}</span
            >
          {/if}
        </div>
      {/if}
      <div class="card-marks">
        {#if data.planned}
          <!-- Planned in a chapter, no scene yet (ADR-0097 §6): the card is dashed too. -->
          <span class="planned-pill">Planned</span>
        {/if}
        {#if data.lateCauses.length}
          <!-- The late-cause flag (ADR-0097 §8): a cause that happens after this card in
               story time. The title names the cause card(s); the pill carries the words. -->
          <span class="late-cause" title={lateCauseTitle(data.lateCauses)}>Cause is later</span>
        {/if}
        {#if data.plotlineName}
          <!-- The plotline is just its dot (hollow when uncoloured); the name rides in the
               tooltip + aria-label, so it stays legible by more than colour (#863) without
               spending card width. -->
          <span
            class="card-plotline"
            class:uncoloured={!accent}
            role="img"
            title={data.plotlineName}
            aria-label={data.plotlineName}
          >
            <span class="plotline-dot" aria-hidden="true"></span>
          </span>
        {/if}
        <!-- The status dot always; its label only when the status is NOT the default —
             the exceptional states ("On the page", "Off the page") earn the words. -->
        <span
          class="card-status"
          class:hollow={pageStatus === "unwritten"}
          style={statusColor ? `--status-color: ${statusColor}` : undefined}
          title={data.pageStatusLabel}
          aria-label={data.pageStatusLabel}
        >
          <span class="status-dot" aria-hidden="true"></span>
          {#if !data.pageStatusIsDefault}{data.pageStatusLabel}{/if}
        </span>
      </div>
    </div>
  </article>

  {#if menuOpen && actions}
    <div class="card-menu nodrag nopan" role="menu" aria-label="Card actions">
      {#if menuView === "main"}
        <button role="menuitem" class="menu-item" onclick={() => run(actions.onOpen)}>
          <i class="ti ti-pencil" aria-hidden="true"></i> Open card
        </button>
        {#if data.attached}
          <button role="menuitem" class="menu-item" onclick={() => run(actions.onDetach)}>
            <i class="ti ti-unlink" aria-hidden="true"></i> Detach scene
          </button>
        {:else if actions.locations.length && !data.planned}
          <!-- Write into a chosen act/chapter (#879): the location list is a submenu,
               mirroring "Set plotline". A PLANNED card skips it — it is written where it
               is planned (ADR-0097 §6) — and without containers to offer we fall through
               to a direct write (the backend's first-container default). -->
          <button role="menuitem" class="menu-item" onclick={() => (menuView = "location")}>
            <i class="ti ti-wand" aria-hidden="true"></i> Write as scene
            <span class="chevron" aria-hidden="true"><GroupCaret size="xs" collapsed /></span>
          </button>
        {:else}
          <button role="menuitem" class="menu-item" onclick={() => realizeAt(null)}>
            <i class="ti ti-wand" aria-hidden="true"></i> Write as scene
          </button>
        {/if}
        {#if !data.attached}
          <!-- Attach an existing scene (ADR-0097 §4): the NodePicker's own trigger is the
               item (it opens a body-portaled popover), offering only scenes no card holds. -->
          <div class="menu-picker">
            <NodePicker
              hideChips
              compact
              config={ATTACH_PICKER}
              value={[]}
              label="Attach scene…"
              structure={actions.structure}
              excludeIds={actions.heldSceneIds}
              onChange={attachPicked}
            />
          </div>
        {/if}
        {#if data.storyMovable}
          <!-- Story time (ADR-0097 §8): drag is never the only way to set an order. An
               item hides at an end of story time, where there is no neighbour to swap with. -->
          {#if data.storyEarlier}
            <button role="menuitem" class="menu-item" onclick={() => storyMove(data.storyEarlier!)}>
              <i class="ti ti-chevron-up" aria-hidden="true"></i> Earlier in story time
            </button>
          {/if}
          {#if data.storyLater}
            <button role="menuitem" class="menu-item" onclick={() => storyMove(data.storyLater!)}>
              <i class="ti ti-chevron-down" aria-hidden="true"></i> Later in story time
            </button>
          {/if}
          {#if (actions.storyAnchors ?? []).some((c) => c.id !== id)}
            <button role="menuitem" class="menu-item" onclick={() => (menuView = "place")}>
              <i class="ti ti-clock" aria-hidden="true"></i> Place after…
              <span class="chevron" aria-hidden="true"><GroupCaret size="xs" collapsed /></span>
            </button>
          {/if}
        {/if}
        {#if data.leadsTo.length}
          <!-- The causal links' removal fallback (#2402): the edge's × can sit under a card. -->
          <button role="menuitem" class="menu-item" onclick={() => (menuView = "leads")}>
            <i class="ti ti-arrow-forward-up" aria-hidden="true"></i> Leads to…
            <span class="chevron" aria-hidden="true"><GroupCaret size="xs" collapsed /></span>
          </button>
        {/if}
        <button role="menuitem" class="menu-item" onclick={() => (menuView = "plotline")}>
          <i class="ti ti-route" aria-hidden="true"></i> Set plotline
          <span class="chevron" aria-hidden="true"><GroupCaret size="xs" collapsed /></span>
        </button>
        <!-- on_page is derived from the scene; only an unattached card authors
             off_page (deliberate backstory) vs unwritten (a placeholder to promote). -->
        {#if !data.attached}
          <button
            role="menuitem"
            class="menu-item"
            onclick={() => setPageStatus(pageStatus === "off_page" ? "unwritten" : "off_page")}
          >
            <i class="ti ti-eye-off" aria-hidden="true"></i>
            {pageStatus === "off_page" ? "Mark unwritten" : "Mark off-page"}
          </button>
        {/if}
        <div class="menu-sep" role="separator"></div>
        <button role="menuitem" class="menu-item menu-danger" onclick={() => run(actions.onDelete)}>
          <i class="ti ti-trash" aria-hidden="true"></i> Delete card
        </button>
      {:else if menuView === "place"}
        <button class="menu-item menu-back" onclick={() => (menuView = "main")}>
          <i class="ti ti-chevron-left" aria-hidden="true"></i> Place after…
        </button>
        <input
          class="menu-filter"
          placeholder="Filter cards"
          aria-label="Filter cards"
          bind:value={placeFilter}
        />
        <div class="menu-scroll" role="group" aria-label="Cards in story time">
          {#each placeChoices as choice (choice.id)}
            <button role="menuitem" class="menu-item" onclick={() => storyMove({ after_id: choice.id })}>
              {choice.title || "Untitled card"}
            </button>
          {:else}
            <span class="menu-empty">No matching cards</span>
          {/each}
        </div>
      {:else if menuView === "leads"}
        <button class="menu-item menu-back" onclick={() => (menuView = "main")}>
          <i class="ti ti-chevron-left" aria-hidden="true"></i> Leads to…
        </button>
        <div class="menu-scroll" role="group" aria-label="Causal links">
          {#each data.leadsTo as link (link.id)}
            <div class="menu-link-row">
              <span class="menu-link-title">{link.title || "Untitled card"}</span>
              <button
                class="menu-link-remove"
                aria-label={`Remove link to ${link.title || "Untitled card"}`}
                onclick={() => unlinkCausal(link.id)}
              >
                <i class="ti ti-x" aria-hidden="true"></i>
              </button>
            </div>
          {:else}
            <span class="menu-empty">No links</span>
          {/each}
        </div>
      {:else if menuView === "location"}
        <button class="menu-item menu-back" onclick={() => (menuView = "main")}>
          <i class="ti ti-chevron-left" aria-hidden="true"></i> Write into…
        </button>
        <div class="menu-scroll" role="group" aria-label="Realize location">
          {#each actions.locations as loc (loc.id)}
            <button
              role="menuitem"
              class="menu-item menu-location"
              style={`--menu-depth: ${loc.depth}`}
              onclick={() => realizeAt(loc.id)}
            >
              <i class="ti ti-book" aria-hidden="true"></i>
              {loc.title || "Untitled"}
            </button>
          {/each}
        </div>
      {:else}
        <button class="menu-item menu-back" onclick={() => (menuView = "main")}>
          <i class="ti ti-chevron-left" aria-hidden="true"></i> Set plotline
        </button>
        <div class="menu-scroll" role="group" aria-label="Plotlines">
          {#each actions.plotlines as line (line.id)}
            <button
              role="menuitem"
              class="menu-item"
              class:current={line.id === data.plotlineId}
              aria-current={line.id === data.plotlineId || undefined}
              onclick={() => setPlotline(line.id)}
            >
              <i class="ti ti-check menu-check" aria-hidden="true"></i>
              {line.title}
            </button>
          {/each}
          <button
            role="menuitem"
            class="menu-item menu-unassigned"
            class:current={!data.plotlineId}
            aria-current={!data.plotlineId || undefined}
            onclick={() => setPlotline("")}
          >
            <i class="ti ti-check menu-check" aria-hidden="true"></i>
            Unassigned
          </button>
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .card-root {
    position: relative;
    width: 100%;
    height: 100%;
  }
  .plot-card {
    box-sizing: border-box;
    /* Size comes from the node box (set in plotBoardLayout from the geometry
       constants); fill it so positions and rendered size share one source. */
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 8px 10px 8px 12px;
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-lg);
    box-shadow: var(--elev-1);
    color: var(--text);
    overflow: hidden;
  }
  /* The plotline stripe down the left edge — an inset shadow so it hugs the
     rounded corners, the same signature NodeRow / ViewFlowNode use for kind. Plus a
     soft plotline tint over the whole card (#863): ~8% of the plotline colour mixed
     into the panel token, so groupings read by colour while staying calm + theme-
     aware. The tint is the card's one colour system; status/beats stay neutral. */
  .plot-card.accented {
    box-shadow: inset 4px 0 0 0 var(--card-accent), var(--elev-1);
    background: color-mix(in srgb, var(--card-accent) 8%, var(--panel));
  }
  /* A planned card (ADR-0097 §6): a place in a chapter, not yet a scene — dashed. */
  .plot-card.planned {
    border-style: dashed;
  }
  /* Accept-highlight while a beat is dragged over the card (#824). */
  .plot-card.drag-over {
    border-color: var(--accent);
    background: var(--accent-soft);
  }
  /* Per-plotline FOCUS (ADR-0053 §6, S5b; #911): the focused thread's cards are LIT —
     an accent outline so they pop (the mockup's treatment; drawn as an outline, not a
     border, so it sits outside the card and isn't clipped by overflow:hidden) — and
     every other card recedes (dimmed: a quiet fade + desaturate, still legible +
     clickable). No token colours change on the dim (opacity/filter only). */
  .plot-card.lit {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
  .plot-card.dimmed {
    opacity: 0.4;
    filter: saturate(0.6);
  }
  .card-head {
    display: flex;
    align-items: flex-start;
    gap: 4px;
  }
  /* The drag handle (#876): the app's standard grip icon (matching SchemaFieldRow's
     "Drag to reorder"). `align-self: stretch` + side padding make a GENEROUS hit target
     — the full header height and ~16px wide, not a fiddly sliver (an earlier ⋮⋮ glyph
     collapsed to 3px, near-ungrabbable). Quiet at rest, brightening on card hover;
     `grab`/`grabbing` cursor advertises the gesture. */
  .card-drag-handle {
    flex: none;
    align-self: stretch;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    margin-left: -3px;
    padding: 0 4px;
    color: var(--text-3);
    font-size: var(--fs-lg);
    line-height: 1;
    cursor: grab;
    transition: color 120ms ease;
  }
  .card-root:hover .card-drag-handle {
    color: var(--text);
  }
  .card-drag-handle:active {
    cursor: grabbing;
  }
  .card-title {
    flex: 1;
    min-width: 0;
    margin: 0;
    font-size: var(--fs-sm);
    font-weight: 600;
    line-height: 1.3;
  }
  /* The title wraps up to two lines; the clamp sits on this inner block, not on the
     button (line-clamp doesn't work on a <button>). */
  .card-title-text {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    overflow-wrap: anywhere;
  }
  /* Click-to-rename affordance — the title look, but a real button (size/weight
     come from .card-title; reset button chrome and inherit the font family). */
  .card-title-btn {
    display: block;
    text-align: left;
    border: none;
    background: transparent;
    padding: 0;
    cursor: text;
    font-family: inherit;
    color: var(--text);
  }
  .card-title-edit {
    flex: 1;
    min-width: 0;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text);
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-sm);
    padding: 1px 4px;
  }
  /* Quiet until the card is hovered or the button is focused / the menu is open. */
  .card-kebab {
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
  .card-root:hover .card-kebab,
  .card-kebab:focus-visible,
  .card-kebab.open {
    opacity: 1;
  }
  .card-kebab:hover {
    background: var(--surface);
    color: var(--text);
  }
  /* The synopsis IS the card (#2354): full size, primary colour, no clamp. The
     estimate in plotBoardLayout sizes the card to it; an under-estimate (or a very
     long synopsis) scrolls here instead of clipping. */
  .card-synopsis {
    margin: 0;
    flex: 1;
    min-height: 0;
    font-size: var(--fs-md);
    line-height: 1.45;
    color: var(--text);
    white-space: pre-line;
    overflow-wrap: anywhere;
    overflow-y: auto;
  }
  /* The click-to-edit affordance reuses the synopsis look but is a real button: reset
     only the chrome + family/weight (NOT `font`, which would clobber the size above). */
  .card-synopsis-btn {
    display: block;
    width: 100%;
    text-align: left;
    border: none;
    background: transparent;
    padding: 0;
    cursor: text;
    font-family: inherit;
    font-weight: inherit;
  }
  .card-synopsis-btn.empty {
    color: var(--text-3);
    font-style: italic;
  }
  .card-synopsis-edit {
    flex: 1;
    min-height: 0;
    resize: none;
    font-family: inherit;
    font-size: var(--fs-md);
    line-height: 1.45;
    color: var(--text);
    background: var(--panel);
    border: 1px solid var(--border-strong);
    border-radius: var(--r-sm);
    padding: 3px 5px;
  }
  /* Beat badges (Slice 5b): the beats this card fulfils, a wrapping chip row.
     A badge is tinted by its OWNING ARC's colour (usability pass), a colour axis
     distinct from the plotline tint (the card's left stripe + soft ground): beats of
     one arc share a tint, so same-named beats of different arcs never collide. An arc
     with no colour keeps the neutral chip. The arc name rides in the tooltip; each
     badge carries an × to unlink (#824), revealed on hover. */
  .card-beats {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
    /* An interactive card lists every beat; a heavily-beated one scrolls here
       (`nowheel` keeps the wheel off the canvas) rather than outgrowing its box. */
    max-height: 100%;
    overflow-y: auto;
  }
  .beat-badge {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    max-width: 100%;
    padding: 0 3px 0 5px;
    font-size: var(--fs-xs);
    line-height: 1.4;
    color: var(--text-2);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-pill);
  }
  /* Arc-coloured badge: a soft tint of the arc's swatch over the surface, with a
     stronger border in the same hue so the grouping reads at a glance without
     shouting (the "quiet writing desk" — kept low like the card's plotline tint). */
  .beat-badge.coloured {
    color: var(--text);
    background: color-mix(in srgb, var(--beat-accent) 14%, var(--surface));
    border-color: color-mix(in srgb, var(--beat-accent) 45%, var(--border));
  }
  .beat-badge-label {
    min-width: 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  /* The beat's roster number (#941): a quiet leading ordinal, tabular so widths line
     up down a column of badges. Never shrinks — the title ellipsises, the number stays. */
  /* The number now trails the title (#941 follow-up); tabular so a column of badges
     lines up, and never shrinks — the title ellipsises, the number holds. */
  .beat-badge-num {
    flex: 0 0 auto;
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    color: var(--text-3);
  }
  .beat-badge.coloured .beat-badge-num {
    color: color-mix(in srgb, var(--beat-accent) 70%, var(--text-3));
  }
  /* A change-pill (ADR-0080 §5 / Amendment 1, slice 3b-ii): a character-arc beat,
     led by the bound character's avatar + the seedling glyph — the same
     `.coloured`/`--beat-accent` ground as an event badge, so the two pill kinds read
     as one family tinted by two different colour sources. */
  .beat-badge.change .avatar {
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 13px;
    height: 13px;
    margin-left: -2px;
    border-radius: 50%;
    background: color-mix(in srgb, var(--beat-accent, var(--text-3)) 70%, transparent);
    color: var(--panel);
    font-size: var(--fs-xs);
    font-weight: 600;
    line-height: 1;
    text-transform: uppercase;
  }
  .beat-badge.change .seed {
    flex: none;
    display: inline-flex;
    color: var(--beat-accent, var(--text-3));
    font-size: var(--fs-xs);
    line-height: 1;
  }
  /* A leading grip that advertises the card→card drag (#941 follow-up), matching the
     plotline roster's beat grip; quiet at rest, brighter on hover, and it never shrinks. */
  .beat-badge-grip {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    margin-left: -2px;
    color: var(--text-3);
    font-size: var(--fs-sm);
    line-height: 1;
  }
  .beat-badge:hover .beat-badge-grip {
    color: var(--text-2);
  }
  /* An interactive badge drags (card→card move, #941): a grab cursor advertises it. */
  .beat-badge.draggable {
    cursor: grab;
  }
  .beat-badge.draggable:active {
    cursor: grabbing;
  }
  .beat-badge-x {
    flex: 0 0 auto;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0;
    border: none;
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
    border-radius: var(--r-pill);
    opacity: 0;
    transition: opacity 120ms ease;
  }
  .beat-badge:hover .beat-badge-x,
  .beat-badge-x:focus-visible {
    opacity: 1;
  }
  .beat-badge-x:hover {
    color: var(--danger);
  }
  /* The overflow chip — quieter than a real beat, and never shrinks. */
  .beat-badge.beat-more {
    flex: 0 0 auto;
    padding: 0 6px;
    color: var(--text-3);
  }
  /* The 3-state page marker (Slice 5b): on_page (moss) / off_page (graphite) /
     unwritten (stone, hollow). The dot colour is the page_status option swatch,
     passed in as --status-color; unwritten draws an outline dot (nothing yet). */
  .card-status {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    flex: none;
    font-size: var(--fs-xs);
    color: var(--text-2);
  }
  .card-status.hollow {
    color: var(--text-3);
  }
  .status-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--status-color, var(--text-3));
    border: 1px solid var(--status-color, var(--text-3));
  }
  .card-status.hollow .status-dot {
    background: transparent;
    border-color: var(--text-3);
  }
  /* Foot row (#2354): the beat pills wrap on the left, the plotline + status marks
     sit right-aligned, pinned to the card's bottom edge. */
  .card-foot {
    display: flex;
    align-items: flex-end;
    gap: 8px;
    margin-top: auto;
    min-height: 22px;
  }
  .card-marks {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    flex: none;
    margin-left: auto;
    min-height: 22px;
  }
  /* The late-cause flag (ADR-0097 §8): a warn pill — the --warn tokens are the
     board's one "layers disagree" colour (the amber causal edge uses it too). */
  .late-cause {
    flex: none;
    padding: 0 7px;
    font-size: var(--fs-xs);
    color: var(--warn);
    background: var(--warn-soft);
    border: 1px solid var(--warn-border);
    border-radius: 999px;
  }
  .planned-pill {
    flex: none;
    padding: 0 7px;
    font-size: var(--fs-xs);
    color: var(--text-2);
    border: 1px solid var(--border-strong);
    border-radius: 999px;
  }
  .card-plotline {
    display: inline-flex;
    align-items: center;
  }
  .plotline-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex: none;
    background: var(--card-accent, var(--text-3));
  }
  .card-plotline.uncoloured .plotline-dot {
    background: transparent;
    border: 1px solid var(--text-3);
  }
  /* Rendered outside .plot-card so the card's overflow:hidden can't clip it. */
  .card-menu {
    position: absolute;
    top: 28px;
    right: 6px;
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
  .menu-picker {
    padding: 2px 4px;
  }
  .menu-item i {
    color: var(--text-3);
  }
  /* Current-plotline marker (#863): a check that keeps its slot when hidden, so the
     labels stay aligned whether or not a row is the selected one. */
  .menu-check {
    visibility: hidden;
    font-size: var(--fs-sm);
  }
  .menu-item.current {
    font-weight: 600;
  }
  .menu-item.current .menu-check {
    visibility: visible;
    color: var(--accent);
  }
  .chevron {
    margin-left: auto;
    display: inline-flex;
    align-items: center;
  }
  .menu-back {
    color: var(--text-2);
    font-weight: 600;
  }
  .menu-sep {
    height: 1px;
    margin: 4px 2px;
    background: var(--divider);
  }
  /* Destructive item (Delete card, #860): danger text + a danger-tinted hover. */
  .menu-danger {
    color: var(--danger);
  }
  .menu-danger:hover {
    background: var(--danger-soft);
  }
  .menu-danger i {
    color: var(--danger);
  }
  .menu-scroll {
    display: flex;
    flex-direction: column;
    max-height: 180px;
    overflow-y: auto;
  }
  /* "Place after…" (ADR-0097 §8): a filter above the anchor list. */
  .menu-filter {
    margin: 2px 4px 4px;
    padding: 4px 6px;
    font-size: var(--fs-sm);
    color: var(--text);
    background: var(--inset);
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
  }
  /* "Leads to…" rows (#2402): the target's title, then a quiet remove button. */
  .menu-link-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 2px 8px;
    font-size: var(--fs-sm);
  }
  .menu-link-title {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .menu-link-remove {
    padding: 2px 4px;
    border: none;
    border-radius: var(--r-sm);
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
  }
  .menu-link-remove:hover {
    background: var(--surface);
    color: var(--danger);
  }
  .menu-empty {
    padding: 6px 8px;
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
  .menu-unassigned {
    color: var(--text-2);
    font-style: italic;
  }
  /* Realize location rows (#879): indent by manuscript depth so the act/chapter
     nesting reads as a tree, not a flat list. --menu-depth is the node's depth. */
  .menu-location {
    padding-left: calc(8px + var(--menu-depth, 0) * 14px);
  }
</style>
