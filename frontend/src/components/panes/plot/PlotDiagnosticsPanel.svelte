<!--
  PlotDiagnosticsPanel — the plot board's cross-dimension findings rail (ADR-0048 S7,
  the payoff). Lists the deterministic diagnostics the projection carries: places where
  two plot layers disagree (a payoff revealed before its setup, beats out of order) or a
  beat the structure leaves unfilled. Clicking a finding LIGHTS its cards on the board
  (the highlight the parent drives); clicking again clears it.

  Presentational: it takes the findings + the selected id and reports clicks. It reports,
  never prescribes — there is no "fix" button; the writer acts on the board or dismisses.
  A findings list is not a node collection (each row is a wrapped diagnostic sentence with
  a severity glyph, not a titled node), so it does NOT compose NodeRow/NodeList — a small
  bespoke list, like the error log. Imports nothing from @xyflow/svelte so it mounts in
  happy-dom for its render test.
-->
<script lang="ts">
  import type { PlotDiagnostic } from "@/lib/types";

  let {
    diagnostics,
    selectedId,
    onSelect,
    onClose,
  }: {
    diagnostics: PlotDiagnostic[];
    selectedId: string | null;
    onSelect: (id: string) => void;
    onClose: () => void;
  } = $props();

  // The three kinds, in the order the detector emits them: the sharpest contradiction
  // first, the softer "a beat is missing" hint last. `warn` = a real layer disagreement
  // (amber); a gap is a quieter, muted cue.
  const GROUPS = [
    { kind: "causal_inversion", label: "Out of sequence", icon: "ti-alert-triangle", tone: "warn" },
    { kind: "beat_inversion", label: "Beats out of order", icon: "ti-alert-triangle", tone: "warn" },
    { kind: "beat_gap", label: "Missing beats", icon: "ti-flag", tone: "muted" },
  ] as const;

  let groups = $derived(
    GROUPS.map((g) => ({ ...g, items: diagnostics.filter((d) => d.kind === g.kind) })).filter(
      (g) => g.items.length > 0,
    ),
  );
</script>

<aside class="diag-panel" aria-label="Plot diagnostics">
  <div class="diag-head">
    <span class="diag-title">Diagnostics</span>
    <button class="diag-close" type="button" onclick={onClose} aria-label="Close diagnostics">
      <i class="ti ti-x" aria-hidden="true"></i>
    </button>
  </div>

  {#if diagnostics.length === 0}
    <div class="diag-empty">
      <i class="ti ti-check" aria-hidden="true"></i>
      <p>No problems found — the plot layers agree.</p>
    </div>
  {:else}
    <div class="diag-list">
      {#each groups as group (group.kind)}
        <div class="diag-group">
          <div class="diag-group-head">
            <span>{group.label}</span>
            <span class="diag-count">{group.items.length}</span>
          </div>
          {#each group.items as finding (finding.id)}
            <button
              class="diag-item"
              class:selected={finding.id === selectedId}
              type="button"
              aria-pressed={finding.id === selectedId}
              onclick={() => onSelect(finding.id)}
            >
              <i class="ti {group.icon} tone-{group.tone}" aria-hidden="true"></i>
              <span class="diag-msg">{finding.message}</span>
            </button>
          {/each}
        </div>
      {/each}
    </div>
  {/if}
</aside>

<style>
  .diag-panel {
    flex: none;
    width: 280px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 10px;
    border-left: 1px solid var(--border);
    background: var(--panel);
    overflow: hidden auto;
  }
  .diag-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 2px 2px 2px 4px;
  }
  .diag-title {
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--text-2);
  }
  .diag-close {
    appearance: none;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border: none;
    border-radius: var(--r-sm);
    background: transparent;
    color: var(--text-3);
    cursor: pointer;
  }
  .diag-close:hover {
    background: var(--inset);
    color: var(--text);
  }
  /* The all-clear state: a quiet check, not a celebration. */
  .diag-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 20px 12px;
    text-align: center;
    color: var(--text-3);
  }
  .diag-empty i {
    font-size: var(--fs-lg);
    color: var(--text-3);
  }
  .diag-empty p {
    margin: 0;
    font-size: var(--fs-sm);
  }
  .diag-list {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-height: 0;
  }
  .diag-group {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .diag-group-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 2px 4px;
    font-size: var(--fs-xs);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--text-3);
  }
  .diag-count {
    font-variant-numeric: tabular-nums;
    color: var(--text-3);
  }
  .diag-item {
    appearance: none;
    display: flex;
    align-items: flex-start;
    gap: 8px;
    width: 100%;
    padding: 8px 10px;
    border: 1px solid transparent;
    border-radius: var(--r-md);
    background: transparent;
    color: var(--text);
    cursor: pointer;
    text-align: left;
  }
  .diag-item:hover {
    background: var(--inset);
  }
  /* Selected mirrors the board: the finding's cards are lit, so its row carries the
     same accent outline as a lit card (an outline, so it doesn't shift the row). */
  .diag-item.selected {
    border-color: var(--accent);
    background: var(--inset);
  }
  .diag-item i {
    flex: none;
    margin-top: 1px;
    font-size: var(--fs-sm);
    line-height: 1.3;
  }
  .tone-warn {
    color: var(--warn);
  }
  .tone-muted {
    color: var(--text-3);
  }
  .diag-msg {
    min-width: 0;
    font-size: var(--fs-sm);
    line-height: 1.35;
  }
</style>
