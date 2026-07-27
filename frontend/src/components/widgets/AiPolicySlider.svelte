<script lang="ts">
  // The AI-policy control, three-stop slider form (design-doc §5 step 3, §8).
  // Slice 0 built the muted-inherited / live-overridden + "Reset to <source>"
  // treatment on the Project-pane RADIO; this is the SLIDER form of the same
  // control, used to lead the create-wizard's AI step. The app has no generic
  // slider, so this is bespoke — modelled on the .fr-toggle track+knob in
  // FieldValueEditor.svelte.
  //
  // Three concrete stops Off · Local · Cloud map to AIPolicy. A fourth *state*
  // (not a stop) is "inherit": when the wizard has declared an ancestor chain
  // and the author has stated no policy of their own, the whole control reads
  // muted and no stop is active — picking a stop overrides (goes live), and the
  // Reset affordance returns it to inheriting. Absence of a stated policy is
  // exactly what makes the chain resolve it (§7's one inheritance law).
  import type { AIPolicy } from "@/lib/types";

  type PolicyDraft = AIPolicy | "inherit";

  let {
    value,
    canInherit = false,
    onChange,
  }: {
    value: PolicyDraft;
    // True only when there is a chain to inherit from (candidates ticked).
    // First-run / top-level projects have nothing above them, so the control is
    // always a concrete Off/Local/Cloud with no inherit state or Reset.
    canInherit?: boolean;
    onChange: (next: PolicyDraft) => void;
  } = $props();

  const STOPS: { policy: AIPolicy; label: string; icon: string }[] = [
    { policy: "off", label: "Off", icon: "ti-power" },
    { policy: "local-only", label: "Local", icon: "ti-device-desktop" },
    { policy: "cloud-allowed", label: "Cloud", icon: "ti-cloud" },
  ];

  // Inheriting = declared a chain AND stated no policy here. No stop is active;
  // the control reads muted. The concrete inherited value is not resolvable
  // before the project exists, so the resting label names the relationship
  // ("the projects above"), not a specific ancestor.
  const inheriting = $derived(canInherit && value === "inherit");
  const activePolicy = $derived<AIPolicy | null>(value === "inherit" ? null : value);
</script>

<div class="policy-slider" class:inheriting>
  <div class="stops" role="radiogroup" aria-label="AI policy">
    <div class="track" aria-hidden="true"></div>
    {#each STOPS as stop (stop.policy)}
      <button
        type="button"
        class="stop"
        class:active={activePolicy === stop.policy}
        role="radio"
        aria-checked={activePolicy === stop.policy}
        aria-label={stop.label}
        onclick={() => onChange(stop.policy)}
      >
        <span class="glyph"><i class={`ti ${stop.icon}`} aria-hidden="true"></i></span>
        <span class="dot"></span>
        <span class="cap">{stop.label}</span>
      </button>
    {/each}
  </div>

  {#if canInherit}
    {#if inheriting}
      <p class="inherit-note">
        Inheriting from the projects above — pick a stop to set a policy for this project.
      </p>
    {:else}
      <!-- On the --star provenance axis (slice 0), naming the source of the
           value it returns to rather than the word "inherit". -->
      <button type="button" class="reset" onclick={() => onChange("inherit")}>
        <i class="ti ti-arrow-back-up" aria-hidden="true"></i>Reset to inherited
      </button>
    {/if}
  {/if}
</div>

<style>
  .policy-slider {
    display: grid;
    gap: 10px;
    margin: 20px 8px 4px;
  }

  .stops {
    position: relative;
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
  }

  /* The rail the stops sit on — a quiet line behind the dots (the .fr-toggle
     track idiom). Inset by a dot-radius each side so it runs dot-centre to
     dot-centre rather than overhanging. */
  .track {
    position: absolute;
    left: 7px;
    right: 7px;
    top: calc(var(--fs-md) + 12px);
    height: 4px;
    border-radius: 999px;
    background: var(--inset);
    border: 1px solid var(--border);
  }

  .stop {
    position: relative;
    z-index: 1;
    display: grid;
    justify-items: center;
    gap: 6px;
    padding: 0;
    border: none;
    background: transparent;
    cursor: pointer;
    color: var(--text-3);
  }

  .glyph {
    font-size: var(--fs-md);
    line-height: 1;
    color: var(--text-3);
  }

  .dot {
    width: 14px;
    height: 14px;
    border-radius: 999px;
    background: var(--surface);
    border: 2px solid var(--border-strong);
    transition: background-color 120ms ease, border-color 120ms ease;
  }

  .cap {
    font-size: var(--fs-xs);
    color: var(--text-3);
    white-space: nowrap;
  }

  /* Live (a policy stated here): the chosen stop leads with the accent. */
  .stop.active .glyph {
    color: var(--text);
  }
  .stop.active .dot {
    background: var(--accent);
    border-color: var(--accent);
  }
  .stop.active .cap {
    color: var(--text);
    font-weight: 600;
  }

  .stop:not(.active):hover .glyph,
  .stop:not(.active):hover .cap {
    color: var(--text-2);
  }
  .stop:not(.active):hover .dot {
    border-color: var(--accent);
  }

  /* Inheriting: the whole control reads gently muted (a dim, not a box — §8),
     so it stays subtle and does not overpower dark mode. */
  .policy-slider.inheriting {
    opacity: 0.6;
  }

  .inherit-note {
    margin: 0;
    font-size: var(--fs-xs);
    color: var(--text-3);
  }

  /* The Reset control lives on the provenance/override axis (--star), matching
     the MetadataPanel "Reset to <source>" gesture slice 0 shipped. */
  .reset {
    justify-self: start;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 6px;
    border: 1px solid transparent;
    border-radius: 6px;
    background: transparent;
    color: var(--star);
    font-size: var(--fs-xs);
    cursor: pointer;
  }
  .reset:hover {
    border-color: var(--border);
    background: var(--surface);
  }
</style>
