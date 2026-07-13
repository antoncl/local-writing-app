<!--
  The parameter mark (ADR-0038 §E, Claude Design pass / #240): a promoted config
  slot is a "half" unit until an actual value fills it "whole". Deliberately a
  ring so it *rhymes with the ring ports* — a parameter is a promoted port. The
  same mark carries the formal declaration (designer: rail + the per-field
  promote affordance) and, in future, the runtime binding strip (#182/#199), so
  "formal + actual = one completed parameter" reads as one token everywhere.

  - `bound` (a real default/value): a whole accent disc.
  - unbound: a hollow muted ring with only the LOWER HALF filled — literally the
    lower half of a unit, awaiting the rest. Replaces the old dashed "inert /
    unbound" tint (#198): the mark itself carries the state.
-->
<script lang="ts">
  let { bound = false, size = 14 }: { bound?: boolean; size?: number } = $props();
</script>

<svg class="pmark" width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
  {#if bound}
    <circle cx="8" cy="8" r="6.4" fill="var(--accent)" stroke="var(--accent)" stroke-width="1.4" />
  {:else}
    <circle cx="8" cy="8" r="6.4" fill="none" stroke="var(--text-3)" stroke-width="1.4" />
    <path d="M1.6 8 A6.4 6.4 0 0 0 14.4 8 Z" fill="var(--text-3)" />
  {/if}
</svg>

<style>
  .pmark {
    display: inline-flex;
    vertical-align: middle;
    line-height: 1;
    flex-shrink: 0;
  }
</style>
