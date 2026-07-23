<script lang="ts">
  // The snapshot strip, foot-docked on a scene card (ADR-0044 §A–§E, #401).
  //
  // The scrubber's third axis: layer (ADR-0042) and story time (ADR-0013)
  // already solve "this document has an ordered set of states; pick one;
  // position is the mode", so snapshots — the same problem on REAL time — get
  // the same gesture rather than a new one. The slot is free: the mutation
  // scrubber renders only for lore, and scenes carry no layer axis.
  //
  // Live sits at the RIGHT, deliberately not the scrubber's home-at-left.
  // There, base is earliest, so home and origin coincide. Here the rest
  // position is the PRESENT and time reads rightward; copying the scrubber's
  // home position would make the two look alike while reading backwards.
  //
  // Compact at rest: while writing this is a quiet ruled line — small notches,
  // camera only, no labels. Parking is what earns the taller strip, the scale
  // ticks and the actions row (ADR-0038 §A's shape, applied to size).
  import type { SnapshotStripController } from "@/lib/stores/snapshotStrip.svelte";
  import { relativeTime } from "@/lib/utils/relativeTime";
  import { LIVE_LEFT, TICKS, ageMinutes, agePosition, notchPositions, trackSpanMinutes } from "@/lib/utils/snapshotTrack";

  let { strip }: { strip: SnapshotStripController } = $props();

  // Ages are read once per render against a single `now`, so every notch and
  // tick on one paint shares a clock. Recomputed whenever the list changes.
  let ages = $derived.by(() => {
    const now = new Date();
    return strip.snapshots.map((snapshot) => ageMinutes(snapshot.captured_at, now));
  });
  let positions = $derived(notchPositions(ages));
  let span = $derived(trackSpanMinutes(ages));
  let visibleTicks = $derived(TICKS.filter((tick) => tick.minutes <= span));
  let parked = $derived(strip.parked !== null);

  function tooltip(index: number): string {
    const snapshot = strip.snapshots[index];
    // Most snapshots have no description — every automatic one, and every
    // explicit one taken in flow — so slice 1's tooltip is the date line alone
    // (§L: the absent case is the COMMON case and must read well on its own).
    // A description is an enrichment on top of it, and arrives with slice 4.
    const when = relativeTime(snapshot.captured_at);
    return snapshot.retention === "kept" ? `Snapshot · ${when} · kept` : `Snapshot · ${when}`;
  }

  // ← → move through time; Esc returns to Live. No held modifier: repeatedly
  // holding Shift trips Windows FilterKeys and five presses fire Sticky Keys,
  // and this is a Windows-first app. It is not needed anyway — the compare view
  // is read-only, so the whole unmodified keyboard is free here (§I).
  //
  // **When the keys are live**: while parked, or while focus is inside the
  // strip. At Live with focus in the prose the arrows belong to the caret —
  // taking them would break typing, which is the one thing this feature must
  // never do. But a keyboard author who has tabbed to a notch has to be able to
  // walk the timeline from there, and at Live that means ← is their way in.
  //
  // A/S/B are the compare axis (#409): Active · Snapshot · Both. Left hand on
  // the letters, right hand on the arrows, so *when* and *which* are driven at
  // once. Not ↑↓, which fight page scroll on a long scene.
  let stripEl: HTMLDivElement | null = $state(null);

  // The three compare states, as a list so the buttons and the key map cannot
  // drift apart.
  const VIEWS = [
    { id: "now", key: "A", label: "Active", hint: "the scene as it is now" },
    { id: "was", key: "S", label: "Snapshot", hint: "the scene as it was" },
    { id: "both", key: "B", label: "Both", hint: "both versions, adjacent" },
  ] as const;

  /**
   * Whether this strip is the one the keypress is for.
   *
   * Every strip installs its own `svelte:window` handler, and the workspace
   * keeps every tab MOUNTED — "only the active one is shown" — so gating on
   * `parked` alone let one press drive every parked strip in the workspace, and
   * a hidden pane swallow plain letters anywhere focus was not an input. Slice 1
   * bound only the arrows and Esc; #409 made the bindings bare `a`/`s`/`b`,
   * which is what turned a latent bug into a daily one.
   *
   * Two rules, in order: a strip inside a hidden tab is never addressed, and
   * when focus sits inside some other editor pane that pane owns the key.
   */
  function addressedToThisPane(target: HTMLElement | null): boolean {
    if (!stripEl) return false;
    if (stripEl.closest(".hidden-doc")) return false;
    const pane = stripEl.closest(".editor-panel");
    const focused = target?.closest?.(".editor-panel") ?? null;
    return !focused || !pane || focused === pane;
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target as HTMLElement | null;
    if (target?.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target?.tagName ?? "")) return;
    if (!parked && !(target && stripEl?.contains(target))) return;
    if (!addressedToThisPane(target)) return;

    // A/S/B are TOGGLES, not held modifiers. Without this an OS auto-repeat
    // fires keydown ~30×/s and the view strobes between two states instead of
    // settling on one (§I). The arrows are exempt: repeating those is a
    // legitimate way to walk the timeline.
    const compare = /^[asb]$/i.test(event.key);
    if (compare && event.repeat) {
      event.preventDefault();
      return;
    }

    switch (event.key) {
      case "ArrowLeft":
        strip.step(-1);
        break;
      case "ArrowRight":
        strip.step(1);
        break;
      case "Escape":
        // Straight back to Live in one press, not via Both: Esc keeps one
        // meaning, and B is already the way back to Both.
        void strip.park(null);
        break;
      case "a":
      case "A":
        strip.toggleView("now");
        break;
      case "s":
      case "S":
        strip.toggleView("was");
        break;
      case "b":
      case "B":
        strip.setView("both");
        break;
      default:
        return;
    }
    event.preventDefault();
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="snapshot-strip" class:compact={!parked} class:waiting={strip.slow} role="group" aria-label="Snapshots" bind:this={stripEl}>
  <div class="strip-track">
    <!-- Ticks first, so notches paint above them. -->
    {#each visibleTicks as tick (tick.label)}
      <span class="tick" style={`left: ${agePosition(tick.minutes, span)}%`} aria-hidden="true">
        <b></b><em>{tick.label}</em>
      </span>
    {/each}

    {#each strip.snapshots as snapshot, index (snapshot.id)}
      <!-- Notches cut INTO the edge rather than sitting on it as beads, so if
           both axes ever appear on one card they read apart at a glance while
           the gesture stays identical. Tall and filled = explicit; short and
           faint = automatic. -->
      <button
        type="button"
        class="notch"
        class:kept={snapshot.retention === "kept"}
        class:current={strip.parked === snapshot.id}
        style={`left: ${positions[index]}%`}
        title={tooltip(index)}
        aria-label={tooltip(index)}
        aria-pressed={strip.parked === snapshot.id}
        onclick={() => void strip.park(strip.parked === snapshot.id ? null : snapshot.id)}
      ><i></i></button>
    {/each}

    <button
      type="button"
      class="notch notch-live"
      class:current={!parked}
      style={`left: ${LIVE_LEFT}%`}
      title="Live — the scene as it is now"
      aria-label="Live — the scene as it is now"
      aria-pressed={!parked}
      onclick={() => void strip.park(null)}
    ><i></i></button>
  </div>

  <!-- Fixed width in BOTH states. Anything here that grew or vanished would
       resize the track and slide every notch along the timeline — and a
       timeline that moves because you used it cannot be read (§E). -->
  <div class="strip-right">
    <button
      type="button"
      class="capture"
      title="Take a snapshot"
      aria-label="Take a snapshot"
      disabled={strip.busy}
      onclick={() => void strip.capture()}
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M4 7h3l1.6-2h6.8L17 7h3a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1z" />
        <circle cx="12" cy="13" r="3.4" />
      </svg>
    </button>
  </div>
</div>

<!-- The actions row exists only while parked, and everything variable lives
     here rather than beside the track — so it can be any width it likes. -->
{#if parked}
  <div class="snapshot-actions">
    <span class="asof">Snapshot · {relativeTime(strip.current?.captured_at ?? "")}</span>

    <!-- The compare axis. It lives HERE and not beside the track because it is
         variable-width, and nothing sharing the track's row may change width —
         that would slide every notch along the timeline (§E). -->
    <div class="compare" role="group" aria-label="Which version">
      {#each VIEWS as option (option.id)}
        <button
          type="button"
          class="cmp"
          class:on={strip.view === option.id}
          title={`${option.label} — ${option.hint} (${option.key})`}
          aria-pressed={strip.view === option.id}
          onclick={() => strip.setView(option.id)}
        >{option.label}<kbd>{option.key}</kbd></button>
      {/each}
    </div>

    <span class="keys" aria-hidden="true"><kbd>←</kbd><kbd>→</kbd> when · <kbd>Esc</kbd> live</span>
    <div class="spacer"></div>
    <button type="button" class="act act-restore" disabled={strip.busy} onclick={() => void strip.restore()}>
      Restore
    </button>
  </div>
{/if}

<style>
  /* A park that has gone on long enough to notice. Below a couple of seconds
     an indicator is worse than nothing — it flashes on every notch and reads as
     the app being slow rather than busy — so this only appears past the
     threshold, and it is the cursor rather than a spinner because there is no
     real progress to report. */
  .snapshot-strip.waiting,
  .snapshot-strip.waiting .notch,
  .snapshot-strip.waiting .capture {
    cursor: progress;
  }

  /* Compact at rest, expanding when engaged. At rest a quiet ruled line under
     the prose; parking earns the taller strip, the ticks and the actions. */
  .snapshot-strip {
    display: flex;
    align-items: stretch;
    gap: 16px;
    padding: 8px 14px;
    min-height: 46px;
    border-top: 1px solid var(--divider);
    background: var(--inset);
    transition: min-height 160ms ease-out, padding 160ms ease-out, background-color 160ms ease-out;
  }
  .snapshot-strip.compact {
    min-height: 27px;
    padding: 0 14px;
    background: transparent;
  }
  .snapshot-strip.compact .strip-track {
    padding-bottom: 6px;
  }
  .snapshot-strip.compact .strip-track::before {
    bottom: 5px;
  }
  .snapshot-strip.compact .notch {
    bottom: 5px;
  }
  .snapshot-strip.compact .tick {
    display: none;
  }
  .snapshot-strip.compact .notch i {
    height: 5px;
  }
  .snapshot-strip.compact .notch.kept i {
    height: 10px;
  }
  .snapshot-strip.compact .notch-live i {
    height: 13px;
  }
  /* Transparent until the pointer nears it — the strip should not compete with
     the prose while the author is writing. */
  .snapshot-strip.compact .capture {
    border-color: transparent;
    background: transparent;
    color: transparent;
  }
  .snapshot-strip.compact:hover {
    background: var(--inset);
  }
  .snapshot-strip.compact:hover .capture,
  .snapshot-strip.compact:focus-within .capture {
    border-color: var(--border);
    background: var(--surface);
    color: var(--text-2);
  }

  /* The track is FLUID — it fills whatever width the pane gives it, and the
     notches keep their proportional positions, so a resized pane shows the same
     timeline larger or smaller. What must never happen is the timeline shifting
     under a gesture that was about READING it. */
  .strip-track {
    position: relative;
    flex: 1 1 auto;
    min-width: 0;
    padding-bottom: 9px;
    transition: padding 160ms ease-out;
  }
  .strip-track::before {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    bottom: 8px;
    height: 1px;
    background: var(--border);
  }

  .tick {
    position: absolute;
    bottom: 8px;
    transform: translateX(-50%);
    display: flex;
    flex-direction: column;
    align-items: center;
    pointer-events: none;
  }
  .tick b {
    display: block;
    width: 1px;
    height: 5px;
    background: var(--border);
  }
  .tick em {
    display: block;
    font-style: normal;
    font-size: var(--fs-xs);
    color: var(--text-3);
    opacity: 0.75;
    margin-top: 1px;
  }

  .notch {
    position: absolute;
    bottom: 8px;
    transform: translateX(-50%);
    width: 14px;
    padding: 0;
    border: 0;
    background: none;
    cursor: pointer;
    display: flex;
    align-items: flex-end;
    justify-content: center;
  }
  .notch i {
    display: block;
    width: 2px;
    height: 9px;
    border-radius: 1px;
    background: var(--border-strong);
    transition: background-color 80ms linear, height 80ms linear;
  }
  .notch.kept i {
    height: 17px;
    background: var(--text-3);
  }
  .notch:hover i,
  .notch:focus-visible i {
    background: var(--diff-was);
  }
  .notch.current i {
    width: 3px;
    background: var(--diff-was);
  }
  .notch.current::after {
    content: "";
    position: absolute;
    bottom: -4px;
    left: 50%;
    transform: translateX(-50%);
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: var(--diff-was);
  }

  /* Live is warm and reads as the present; the snapshots are cool and read as
     the past (§H). Colour, never a glyph: a snapshot difference exists only
     while parked, and a glyph would put a permanent-looking mark on a temporary
     condition (§J). */
  /* `.notch.notch-live`, not `.notch-live`, and the doubled class is
     load-bearing: Live is `.current` at rest, and `.notch.current i` above
     would otherwise outrank a single-class rule and paint the present in the
     PAST's colour — the one thing this pair must never do. */
  .notch.notch-live i {
    width: 3px;
    height: 21px;
    border-radius: 2px;
    background: var(--diff-now);
  }
  .notch-live.current i {
    box-shadow: 0 0 0 3px var(--diff-now-soft);
  }

  .strip-right {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    flex: none;
    width: 34px;
  }

  .capture {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 26px;
    padding: 0;
    color: var(--text-2);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    cursor: pointer;
    transition: border-color 80ms linear, color 80ms linear, background-color 80ms linear;
  }
  .capture:hover:not(:disabled) {
    border-color: var(--diff-now);
    color: var(--diff-now);
  }
  .capture:disabled {
    cursor: default;
    opacity: 0.6;
  }
  .capture svg {
    width: 16px;
    height: 16px;
    flex: none;
  }

  .snapshot-actions {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    padding: 8px 14px;
    border-top: 1px solid var(--divider);
    background: var(--panel);
  }
  .asof {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--diff-was);
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  /* Active · Snapshot · Both. A segmented control rather than three loose
     buttons: they are one choice, and the selected one is the answer to
     "which version am I reading". */
  .compare {
    display: inline-flex;
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
  }
  .cmp {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font: inherit;
    font-size: var(--fs-sm);
    padding: 3px 9px;
    border: 0;
    border-left: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-2);
    cursor: pointer;
    transition: background-color 80ms linear, color 80ms linear;
  }
  .cmp:first-child {
    border-left: 0;
  }
  .cmp:hover {
    background: var(--inset);
  }
  .cmp.on {
    background: var(--accent-soft);
    color: var(--accent-emphasis);
    font-weight: 600;
  }
  .cmp kbd {
    font-family: inherit;
    font-size: var(--fs-xs);
    color: var(--text-3);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 0 3px;
    background: var(--panel);
  }
  .cmp.on kbd {
    color: var(--accent-emphasis);
    border-color: currentColor;
  }

  .keys {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }
  .keys kbd {
    font-family: inherit;
    font-size: var(--fs-xs);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 0 4px;
    background: var(--surface);
  }
  .spacer {
    flex: 1 1 auto;
  }
  .act {
    font-size: var(--fs-sm);
    padding: 4px 11px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
    cursor: pointer;
  }
  .act:disabled {
    cursor: default;
    opacity: 0.6;
  }
  .act-restore {
    border-color: var(--accent);
    color: var(--accent-emphasis);
    font-weight: 600;
  }
</style>
