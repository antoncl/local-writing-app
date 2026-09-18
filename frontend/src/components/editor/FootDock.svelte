<script lang="ts">
  // The lore card's foot dock (ADR-0088). One dock, two modes: a lore entry
  // carries two time-axes — MUTATIONS (story time, LoreScrubController) and
  // SNAPSHOTS (edit time, SnapshotStripController) — and this shows ONE track at
  // a time. A click-to-advance ModeControl picks which; a single keyboard
  // gesture drives both (§4). A scene, or a lore entry with no mutations, has
  // only the snapshot axis and shows that track with no control — exactly
  // ADR-0044's strip.
  //
  // This is the ONE owner of the dock's `svelte:window` keydown: it was lifted
  // out of SnapshotStrip so the two strips stay pure presentational and there is
  // never a second window handler competing for the arrows (§4 / breakage).
  import ModeControl from "@/components/editor/ModeControl.svelte";
  import SnapshotStrip from "@/components/editor/SnapshotStrip.svelte";
  import MutationScrubber from "@/components/editor/MutationScrubber.svelte";
  import type { SnapshotStripController } from "@/lib/stores/snapshotStrip.svelte";
  import type { LoreScrubController } from "@/lib/stores/loreScrub.svelte";
  import type { DocumentKind } from "@/lib/types";
  import { paneOwnsKey } from "@/lib/utils/paneScope";

  type Track = "mutations" | "snapshots";

  let {
    snapshots,
    scrub,
    documentKind,
    writesLabel = null,
  }: {
    snapshots: SnapshotStripController;
    scrub: LoreScrubController;
    documentKind: DocumentKind;
    writesLabel?: string | null;
  } = $props();

  let footEl = $state<HTMLElement | null>(null);
  // The picked track. Default "snapshots" — it is the track already showing when
  // the mode control first appears (the ADR user journey).
  let mode = $state<Track>("snapshots");

  // The dock mounts only on a prose card, where the snapshot axis always exists;
  // the mutation axis exists only for a lore entry with authored mutations. So
  // "both timelines" ⇔ "has mutations", and that gates the mode control.
  let hasBothTimelines = $derived(documentKind === "lore" && scrub.units.length > 0);
  // The track follows the ENGAGED axis, wherever the engagement came from — the
  // dock's own mode control, OR the rail's mutation timeline, which drives the
  // same scrub controller (NodeEditor). So the dock can never show a parked
  // snapshot while the body shows a mutation scrub: engaging one axis takes the
  // track. With nothing engaged it shows the last explicit `mode`; with no
  // mutation axis at all it is always snapshots (a stale `mode` can't leave an
  // empty track).
  let shownTrack = $derived<Track>(
    !hasBothTimelines
      ? "snapshots"
      : scrub.index > 0
        ? "mutations"
        : snapshots.parked !== null
          ? "snapshots"
          : mode,
  );

  function cycle(): void {
    // Reset the outgoing axis to its editable end and flip the mode. The card's
    // mutual exclusion (at most one of scrubbed / snapshotParked) is kept by
    // `shownTrack` following the engaged axis, plus the rail timeline clearing the
    // snapshot park (NodeEditor) — NOT by this reset alone, so the body-overlay
    // precedence stays correct even when the rail engages the mutation axis.
    if (shownTrack === "snapshots") {
      void snapshots.park(null); // leaving snapshots → Live
      mode = "mutations";
    } else {
      void scrub.scrubTo(0); // leaving mutations → base
      mode = "snapshots";
    }
    // The track component swaps on the mode change, unmounting whatever the user
    // clicked to engage (a notch or bead) and dropping focus to <body> — which
    // would strand the keyboard behind the editable-end focus gate below. Move
    // focus to the persistent mode control so ← / → / Esc / m keep working (§4).
    footEl?.querySelector<HTMLElement>(".mode-control")?.focus();
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target as HTMLElement | null;
    if (target?.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target?.tagName ?? "")) return;

    // While parked/scrubbed the read-only overlay frees the whole keyboard; at
    // the editable end only a press with focus inside the dock is ours (else a
    // plain letter typed elsewhere in the pane would move the track).
    const engaged = shownTrack === "snapshots" ? snapshots.parked !== null : scrub.index > 0;
    if (!engaged && !(target && footEl?.contains(target))) return;
    if (!paneOwnsKey(footEl, target)) return;

    // One unmodified key cycles the mode — only when both timelines exist.
    // Swallow OS auto-repeat so a held key doesn't strobe the track.
    if ((event.key === "m" || event.key === "M") && hasBothTimelines) {
      if (event.repeat) {
        event.preventDefault();
        return;
      }
      cycle();
      event.preventDefault();
      return;
    }

    if (shownTrack === "snapshots") {
      // A/S/B are toggles, not held modifiers; ignore auto-repeat so the view
      // can't strobe between two states (ADR-0044 §I). Arrows are exempt.
      const compare = /^[asb]$/i.test(event.key);
      if (compare && event.repeat) {
        event.preventDefault();
        return;
      }
      switch (event.key) {
        case "ArrowLeft":
          snapshots.step(-1);
          break;
        case "ArrowRight":
          snapshots.step(1);
          break;
        case "Escape":
          void snapshots.park(null);
          break;
        case "a":
        case "A":
          snapshots.toggleView("now");
          break;
        case "s":
        case "S":
          snapshots.toggleView("was");
          break;
        case "b":
        case "B":
          snapshots.setView("both");
          break;
        default:
          return;
      }
      event.preventDefault();
    } else {
      // Mutations: ← / → step the stops, Esc → base. A/S/B are ABSENT — a
      // mutation stop is a single read-only effective state with nothing to
      // compare (§4) — so they fall through, unhandled, rather than no-op'ing.
      switch (event.key) {
        case "ArrowLeft":
          scrub.step(-1);
          break;
        case "ArrowRight":
          scrub.step(1);
          break;
        case "Escape":
          void scrub.scrubTo(0);
          break;
        default:
          return;
      }
      event.preventDefault();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="foot-dock" class:has-mode={hasBothTimelines} bind:this={footEl}>
  {#if hasBothTimelines}
    <div class="fd-rotary-col">
      <ModeControl track={shownTrack} onCycle={cycle} />
    </div>
  {/if}
  <div class="fd-track">
    {#if shownTrack === "snapshots"}
      <SnapshotStrip strip={snapshots} {writesLabel} />
    {:else}
      <MutationScrubber
        units={scrub.units}
        index={scrub.index}
        onScrub={(index) => void scrub.scrubTo(index)}
      />
    {/if}
  </div>
</div>

<style>
  /* One dock frame: the mode control in a fixed left column, the current track
     filling the rest. Each track keeps its own visual language (notches vs
     beads) so the mode reads at a glance (§3). */
  .foot-dock {
    display: flex;
    align-items: stretch;
  }
  .fd-rotary-col {
    flex: none;
    display: flex;
    align-items: center;
    padding: 6px 12px;
    border-top: 1px solid var(--divider);
    background: var(--panel);
  }
  .fd-track {
    flex: 1 1 auto;
    min-width: 0;
  }
</style>
