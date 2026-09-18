<script lang="ts">
  // The foot dock's track picker (ADR-0088 §2). A single click-to-advance button
  // — the theme-cycle idiom (TopBar.onCycleTheme): the button is dumb, the host
  // owns the enum and advances it on click. It shows the CURRENT track's name
  // with an accent tint (the ViewSwitcher live-name pattern), NOT a
  // glyph-with-tooltip, and it is NOT a popover. It renders only when the node
  // has both timelines (the host gates the mount), so it is always in the live
  // state — the tint is unconditional, no `.live` toggle.
  type Track = "mutations" | "snapshots";

  let { track, onCycle }: { track: Track; onCycle: () => void } = $props();

  const TRACK_LABEL: Record<Track, string> = { mutations: "Mutations", snapshots: "Snapshots" };
  let currentLabel = $derived(TRACK_LABEL[track]);
  let nextLabel = $derived(track === "mutations" ? "Snapshots" : "Mutations");
</script>

<button
  type="button"
  class="mode-control"
  aria-label={`Timeline: ${currentLabel}`}
  title={`Switch the track to ${nextLabel}`}
  onclick={onCycle}
>
  <span class="dial" aria-hidden="true">⟳</span>
  <span class="mode-label">{currentLabel}</span>
</button>

<style>
  /* From the normative mockup's `.rotary` (docs/design/mockups/0087-rotary-
     scrubber.html). Always tinted with --accent-emphasis (the text/border
     emphasis token that brightens in dark, as TopBar's .action-button.active
     and the mockup's .rotary.live use): the control exists only while a real
     choice is live, so the "live" state is unconditional here. */
  .mode-control {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 4px 9px 4px 8px;
    border: 1px solid var(--accent-emphasis);
    background: var(--surface);
    color: var(--accent-emphasis);
    border-radius: var(--r-md);
    font-family: var(--sans);
    font-size: var(--fs-md);
    cursor: pointer;
    transition:
      background-color 80ms linear,
      color 80ms linear,
      border-color 80ms linear;
  }
  .mode-control:hover {
    background: var(--panel);
    /* Keep the accent border from the live rule; only the text neutralises on
       hover, matching the mockup. */
    color: var(--text);
  }
  .dial {
    width: 16px;
    height: 16px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: var(--fs-md);
    color: var(--accent-emphasis);
    transition: transform 220ms ease-out;
  }
  /* The dial physically turns on press — the click-to-advance affordance. */
  .mode-control:active .dial {
    transform: rotate(120deg);
  }
  .mode-label {
    font-weight: var(--w-semibold);
  }
</style>
