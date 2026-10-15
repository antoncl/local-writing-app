<script lang="ts">
  // ADR-0099 §4: the "Follow-ups" section of the entry review — changes the
  // conversation implied for OTHER entries. Each starts unticked; a ticked one
  // becomes a TODO on Done. Shown under either review presentation (the
  // overlay mounts it), only when the proposal carries any. A pure view: the
  // controller owns the ticks.
  import type { FollowUp } from "@/lib/types";

  let {
    followUps,
    isTicked,
    onToggle,
  }: {
    followUps: FollowUp[];
    isTicked: (index: number) => boolean;
    onToggle: (index: number) => void;
  } = $props();
</script>

{#if followUps.length > 0}
  <section class="follow-ups" data-testid="follow-ups" aria-label="Follow-ups">
    <p class="follow-ups-hint">Follow-ups for other entries — tick the ones to keep as TODOs</p>
    {#each followUps as followUp, index (index)}
      <label class="follow-up-row" data-testid="follow-up-row">
        <input
          type="checkbox"
          data-testid="follow-up-tick"
          checked={isTicked(index)}
          onchange={() => onToggle(index)}
        />
        <span class="follow-up-text">
          <strong class="follow-up-entry">{followUp.entry_name}</strong>
          <span class="follow-up-change">{followUp.change}</span>
          {#if followUp.why}<span class="follow-up-why">{followUp.why}</span>{/if}
        </span>
      </label>
    {/each}
  </section>
{/if}

<style>
  .follow-ups {
    flex: none;
    display: flex;
    flex-direction: column;
    gap: 6px;
    max-height: 40%;
    overflow-y: auto;
    padding: 8px 24px;
    border-top: 1px solid var(--divider);
  }
  .follow-ups-hint {
    margin: 0;
    font-size: var(--fs-sm);
    color: var(--text-2);
  }
  .follow-up-row {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    cursor: pointer;
  }
  .follow-up-row input {
    margin-top: 3px;
  }
  .follow-up-text {
    display: flex;
    flex-direction: column;
    font-size: var(--fs-sm);
    line-height: 1.4;
    color: var(--text);
  }
  .follow-up-why {
    color: var(--text-3);
  }
</style>
