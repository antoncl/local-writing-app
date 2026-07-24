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
  import { tick } from "svelte";
  import { SNAPSHOT_DESCRIPTION_MAX, type SnapshotStripController } from "@/lib/stores/snapshotStrip.svelte";
  import DriftReport from "@/components/editor/DriftReport.svelte";
  import { notchAges, notchTooltip, notchWhen } from "@/lib/utils/snapshotTime";
  import { LIVE_LEFT, TICKS, agePosition, notchPositions, trackSpanMinutes } from "@/lib/utils/snapshotTrack";

  let { strip }: { strip: SnapshotStripController } = $props();

  // Ages are read once per render against a single `now`, so every notch and
  // tick on one paint shares a clock. Recomputed whenever the list changes.
  //
  // By CONTENT age, not record age (#458) — and the list arrives ordered by the
  // same key, which is `notchPositions`' input contract. Both rules live in
  // `snapshotTime`, where they can be tested.
  let ages = $derived(notchAges(strip.snapshots, new Date()));
  let positions = $derived(notchPositions(ages));
  let span = $derived(trackSpanMinutes(ages));
  let visibleTicks = $derived(TICKS.filter((tick) => tick.minutes <= span));
  let parked = $derived(strip.parked !== null);

  // The playhead marks the parked notch: a cursor rides its position rather than
  // recolouring the mark, so "which is active" reads as a place, not a 1px width
  // change. Cool always — parking is only ever onto a snapshot (Live is never
  // parked, so it keeps its own warm halo and shows no playhead). `-1` at Live
  // gates the element out of the DOM entirely (§J: no permanent glyph on a
  // temporary condition).
  let currentIndex = $derived(
    strip.parked === null ? -1 : strip.snapshots.findIndex((snapshot) => snapshot.id === strip.parked),
  );
  let playheadLeft = $derived(currentIndex >= 0 ? positions[currentIndex] : LIVE_LEFT);

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

  // The description edits in place (variant B, ADR-0044 §L / Open item 4): at
  // rest the row shows only what exists — the one-liner with a pencil, or a
  // quiet "+ describe" when there is none — so the common empty case shows
  // nothing to fill in. The input appears only on the pencil.
  let editingDesc = $state(false);
  let descDraft = $state("");
  let descInput = $state<HTMLInputElement | null>(null);

  // Stepping to another notch abandons an open editor — the draft belonged to
  // the notch the author just left. Reading `strip.parked` registers it as the
  // dependency; `beginEdit` does not touch it, so opening the editor is safe.
  $effect(() => {
    strip.parked;
    editingDesc = false;
  });

  async function beginEdit(): Promise<void> {
    descDraft = strip.current?.description ?? "";
    editingDesc = true;
    await tick();
    descInput?.focus();
  }

  function commitDesc(): void {
    if (!editingDesc) return;
    editingDesc = false;
    // Trimming and the unchanged-text guard both live in `describe`, where a
    // test can reach them — closing the editor without editing costs nothing.
    void strip.describe(descDraft);
  }

  function onDescKeydown(event: KeyboardEvent): void {
    if (event.key === "Enter") {
      event.preventDefault();
      descInput?.blur(); // commits via onblur
    } else if (event.key === "Escape") {
      event.preventDefault();
      editingDesc = false; // abandon; the window handler ignores INPUT targets
    }
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
        title={notchTooltip(snapshot)}
        aria-label={notchTooltip(snapshot)}
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

    {#if parked && currentIndex >= 0}
      <!-- The playhead: the parked cursor. It rides the notch's position and
           animates between notches so the eye is carried to the new one; the
           slide length also reads as how far back in time the jump was. -->
      <div class="playhead" style={`left: ${playheadLeft}%`} aria-hidden="true"></div>
    {/if}
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
    <span class="asof">Snapshot · {notchWhen(strip.current)}</span>

    <!-- The description (variant B). Nothing empty is shown: with a note, the
         one-liner and a pencil to edit it; without one, a quiet "+ describe".
         The input appears only on the pencil, so the common empty case is a
         clean row (§L). Lives here because it is variable-width, like every
         other thing in this row — the track never sees it (§E). -->
    {#if editingDesc}
      <input
        class="desc-input"
        type="text"
        bind:value={descDraft}
        bind:this={descInput}
        placeholder="A one-line note…"
        aria-label="Snapshot description"
        maxlength={SNAPSHOT_DESCRIPTION_MAX}
        onblur={commitDesc}
        onkeydown={onDescKeydown}
      />
    {:else if strip.current?.description}
      <span class="desc">
        <span class="desc-text" title={strip.current.description}>“{strip.current.description}”</span>
        <button type="button" class="icon-btn" title="Edit description" aria-label="Edit description" onclick={beginEdit}>
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
          </svg>
        </button>
      </span>
    {:else}
      <button type="button" class="add-desc" onclick={beginEdit}>+ describe</button>
    {/if}

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
    <!-- Pin promotes an automatic to kept; an explicit one is already kept, so
         the button appears only on a `thinned` notch and a pinned one simply
         stops offering it — the affordance IS the one-directional rule. -->
    {#if strip.current?.retention === "thinned"}
      <button type="button" class="act" disabled={strip.busy} onclick={() => void strip.pin()}>
        Pin
      </button>
    {/if}
    <!-- Delete is the one irreversible gesture, so it is the one that confirms
         (restore captures first, so it does not). -->
    <button type="button" class="act act-del" disabled={strip.busy} onclick={() => strip.del()}>
      Delete
    </button>
  </div>

  <!-- Below the actions, not in front of them: the report is advisory, and
       Restore stays reachable without passing it (ADR-0043). It appears here
       because the diff already carries it — parking is what fetches the
       comparison, and a restore is only reachable from a parked notch, so
       "restore reports drift" costs nothing extra. -->
  {#if strip.hasDriftToReport}
    <DriftReport drift={strip.drift} />
  {/if}
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
    /* Tall enough for the notches above the rule AND the scale below it
       (#406). Only while parked — compact overrides it below, and parking is
       what earns the taller strip in the first place (§B). */
    min-height: 61px;
    /* One baseline for everything that lines up on the rule — the rule itself,
       the notches above it, the ticks below it (#406). Written once here and
       once in `.compact`; every consumer reads `var(--rule-bottom)`, so the two
       states are the only places the number lives and nothing can drift off the
       rule the way #406 did. */
    --rule-bottom: 23px;
    border-top: 1px solid var(--divider);
    background: var(--inset);
    transition: min-height 160ms ease-out, padding 160ms ease-out, background-color 160ms ease-out;
  }
  .snapshot-strip.compact {
    min-height: 27px;
    padding: 0 14px;
    background: transparent;
    --rule-bottom: 5px;
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
    padding-bottom: calc(var(--rule-bottom) + 1px);
    transition: padding 160ms ease-out;
  }
  .strip-track::before {
    content: "";
    position: absolute;
    left: 0;
    right: 0;
    bottom: var(--rule-bottom);
    height: 1px;
    background: var(--border);
    /* Moves with the rule baseline in lockstep with the strip's min-height, so
       parking doesn't snap the rule while the height animates (#406 follow-up). */
    transition: bottom 160ms ease-out;
  }

  /* The scale hangs BELOW the rule; notches rise above it (#406). They used to
     share the band above the line — 1px of width and one step of neutral grey
     apart — so a notch landing on `1h` was hard to pick out and the tick's
     label read as an annotation *of that notch*. The notch could not be the
     thing that moved: its position **is** the timeline (§D/§E). Two marks on
     opposite sides of one line can never be the same mark in the same place,
     whatever the spacing does. */
  .tick {
    position: absolute;
    bottom: var(--rule-bottom);
    transform: translate(-50%, 100%);
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
    bottom: var(--rule-bottom);
    transform: translateX(-50%);
    width: 14px;
    padding: 0;
    border: 0;
    background: none;
    cursor: pointer;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    /* In lockstep with the rule and the strip height, so parking doesn't leave
       the notches hanging above the strip while it grows (#406 follow-up). */
    transition: bottom 160ms ease-out;
  }
  /* Snapshots read as the past, so they carry the diff's cool tint at full
     strength (#481) — with no test-user population to tune a quieter resting
     state, always-legible beats the quietest desk. Automatic captures are
     HOLLOW, kept ones FILLED: the class reads as SHAPE, which survives greyscale
     where the tint cannot (ADR-0044 §H — warm and cool are equal-luminance by
     construction, so hue can only ever be the meaning layer, never the one that
     makes a mark visible). */
  .notch i {
    display: block;
    width: 4px;
    height: 9px;
    border: 1.5px solid var(--diff-was);
    border-radius: 1px;
    background: transparent;
    transition: height 80ms linear, box-shadow 80ms linear;
  }
  .notch.kept i {
    width: 3px;
    height: 17px;
    border: 0;
    background: var(--diff-was);
  }
  /* Hover, focus and the parked notch are affordance only — the tint is already
     full — so they add the soft wash as a HALO rather than a colour change.
     Scoped off Live, which owns the warm treatment below. The playhead is the
     primary "you are here"; this halo is the quiet confirmation under it. */
  .notch:not(.notch-live):hover i,
  .notch:not(.notch-live):focus-visible i,
  .notch:not(.notch-live).current i {
    box-shadow: 0 0 0 2px var(--diff-was-soft);
  }

  /* Live is warm and reads as the present; the snapshots are cool and read as
     the past (§H). Colour, never a glyph (§J). Live is FILLED warm — it must
     override the hollow-cool base every snapshot notch now uses, so it resets
     both the border and the background. */
  /* `.notch.notch-live`, not `.notch-live`: the doubled class keeps Live's fill
     ahead of the shared `.notch i` base whatever order the file lands in. */
  .notch.notch-live i {
    width: 3px;
    height: 21px;
    border: 0;
    border-radius: 2px;
    background: var(--diff-now);
  }
  .notch-live.current i {
    box-shadow: 0 0 0 3px var(--diff-now-soft);
  }

  /* The playhead — the parked cursor. A hairline riding the notch's position
     with a downward cap; the eye tracks it to the notch and the slide reads as
     distance travelled in time. Cool always: parking is only ever onto a
     snapshot. The cap is deliberately chunky (12×8) so it carries the "you are
     here" cue in greyscale, where the cool tint flattens into the notches' own
     grey (§H). */
  .playhead {
    position: absolute;
    bottom: var(--rule-bottom);
    width: 0;
    transform: translateX(-50%);
    pointer-events: none;
    transition: left 160ms ease-out, bottom 160ms ease-out;
  }
  .playhead::before {
    content: "";
    position: absolute;
    left: -0.75px;
    bottom: 0;
    width: 1.5px;
    height: 28px;
    background: var(--diff-was);
  }
  .playhead::after {
    content: "";
    position: absolute;
    left: -6px;
    bottom: 27px;
    width: 0;
    height: 0;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-top: 8px solid var(--diff-was);
  }
  /* Motion is the attention cue here, so reduced-motion must not drop it in
     silence: the slide is removed, but a persistent halo keeps the cursor
     findable at its new position. */
  @media (prefers-reduced-motion: reduce) {
    .playhead {
      transition: none;
    }
    .playhead::before {
      box-shadow: 0 0 0 2px var(--diff-was-soft);
    }
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
  /* Delete is destructive, so it borrows `--danger` on hover — but only on
     hover: a resting red button in a quiet writing desk reads as an alarm, and
     the confirmation is what actually guards the action (ADR-0043). */
  .act-del:hover:not(:disabled) {
    border-color: var(--danger);
    color: var(--danger);
  }

  /* The description surface (variant B). At rest it shows only what exists. */
  .desc {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    min-width: 0;
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .desc-text {
    font-style: italic;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 32ch;
  }
  .icon-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    padding: 0;
    border: 0;
    background: none;
    color: var(--text-3);
    cursor: pointer;
    border-radius: var(--r-sm);
    transition: color 80ms linear, background-color 80ms linear;
  }
  .icon-btn:hover {
    color: var(--accent-emphasis);
    background: var(--accent-soft);
  }
  /* The empty case: a quiet invitation, never an empty box (§L). */
  .add-desc {
    font-size: var(--fs-sm);
    color: var(--text-3);
    background: none;
    border: 0;
    cursor: pointer;
    padding: 2px 4px;
    border-radius: var(--r-sm);
  }
  .add-desc:hover {
    color: var(--accent-emphasis);
  }
  .desc-input {
    font: inherit;
    font-size: var(--fs-sm);
    color: var(--text);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 3px 8px;
    min-width: 140px;
    flex: 0 1 240px;
  }
  .desc-input::placeholder {
    color: var(--text-3);
    font-style: italic;
  }
  .desc-input:focus {
    outline: none;
    border-color: var(--accent);
  }
</style>
