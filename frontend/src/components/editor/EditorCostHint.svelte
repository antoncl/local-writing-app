<script lang="ts">
  // The editor footer's hint row (extracted from NodeEditor, #1261): the optional
  // status line plus the trailing cost cluster — live word count + per-character
  // roleplay costs + the session/last-call chip for a scene, or the single
  // all-time rollup chip for a lore character / the project. Purely presentational:
  // NodeEditor owns the cost state and computes the rows/rollup, and hands them
  // down here.
  import { formatCostEur } from "@/lib/utils/money";
  import type { CharacterCostRow, RollupCost } from "@/lib/editor-core/characterCost";

  let {
    todoStatusHint = "",
    documentKind,
    liveWordCount,
    characterCosts,
    lastInvocationCostUsd,
    sceneSessionCostUsd,
    rollupCost,
  }: {
    todoStatusHint?: string;
    documentKind: string;
    liveWordCount: number;
    characterCosts: CharacterCostRow[];
    lastInvocationCostUsd: number | null;
    sceneSessionCostUsd: number;
    rollupCost: RollupCost | null;
  } = $props();
</script>

{#if todoStatusHint || documentKind === "manuscript" || rollupCost}
  <div class="editor-hint">
    {#if todoStatusHint}
      <span class="editor-hint-text">{todoStatusHint}</span>
    {/if}
    {#if documentKind === "manuscript"}
      <div class="editor-hint-costs">
        <span class="word-count-chip" title="Live word count for this scene.">
          {liveWordCount.toLocaleString()} {liveWordCount === 1 ? "word" : "words"}
        </span>
        {#each characterCosts as row (row.id)}
          <span
            class="character-cost-chip"
            title={`Roleplay cost attributed to ${row.title} in this scene (all sessions).`}
            style={`--character-color: ${row.color}`}
          >
            <span class="character-cost-dot" aria-hidden="true"></span>
            <span class="character-cost-name">{row.title}</span>
            <span class="character-cost-amount">{formatCostEur(row.cost)}</span>
          </span>
        {/each}
        {#if lastInvocationCostUsd != null}
          <span class="continuation-cost-chip" title="Last continuation invocation cost · running total for this scene this session. Resets on reload or scene switch.">
            last {formatCostEur(lastInvocationCostUsd)} · session {formatCostEur(sceneSessionCostUsd)}
          </span>
        {/if}
      </div>
    {:else if rollupCost}
      <div class="editor-hint-costs">
        <span
          class="node-rollup-cost-chip"
          title={rollupCost.kind === "character"
            ? "All-time AI cost attributed to this character across every scene."
            : "Whole-project AI cost across every invocation."}
        >
          {rollupCost.kind === "character" ? "character" : "project"} cost {formatCostEur(rollupCost.value)}
        </span>
      </div>
    {/if}
  </div>
{/if}

<style>
  .editor-hint-text {
    flex: 1 1 auto;
    min-width: 0;
  }

  /* Per-scene continuation cost rollup. Frontend-only — resets on reload
     / scene switch. Sits in the trailing cost cluster on the footer hint
     row. Phase C added the persisted ai_invocations log; this chip stays
     as the session/last-call view, and `character-cost-chip` carries the
     per-character all-time totals from the log. */
  .continuation-cost-chip,
  /* The live word count (#1237): the same quiet, muted treatment as the cost
     chips — present for a glance, never loud (a scene shows it even with no AI
     costs yet). The value also lives in the `word_count` metadata field. */
  .word-count-chip {
    color: var(--text-3);
    font-size: var(--fs-xs);
    white-space: nowrap;
    cursor: default;
    flex: 0 0 auto;
  }

  /* Single-value rollup chip for character_cost / project_cost (lore
     character entries and the project node respectively). Same muted
     tone as the scene cost chips so the editor hint row stays calm. */
  .node-rollup-cost-chip {
    color: var(--text-3);
    font-size: var(--fs-xs);
    white-space: nowrap;
    cursor: default;
    flex: 0 0 auto;
    font-variant-numeric: tabular-nums;
  }

  /* Trailing cluster on the editor footer hint row. Holds the
     per-character roleplay-cost chips and the continuation chip. */
  .editor-hint-costs {
    display: flex;
    align-items: baseline;
    gap: 8px;
    flex-wrap: wrap;
    justify-content: flex-end;
    flex: 0 1 auto;
    min-width: 0;
  }

  /* Per-character cost chip — colored dot + character name + cost.
     Backed by the persisted ai_invocations log; character color resolves
     from the lore entry (or a deterministic hue when unset). */
  .character-cost-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: var(--fs-xs);
    color: var(--text-3);
    white-space: nowrap;
    cursor: default;
  }

  .character-cost-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--character-color, var(--text-3));
    flex: 0 0 auto;
  }

  .character-cost-name {
    color: var(--text);
  }

  .character-cost-amount {
    font-variant-numeric: tabular-nums;
  }
</style>
