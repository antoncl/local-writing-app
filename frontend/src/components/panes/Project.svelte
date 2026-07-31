<script lang="ts">
  import { formatCostEur } from "@/lib/utils/money";

  export let isProjectOpen: boolean;
  export let projectTitle: string;
  export let projectCostTotal: number | null;
  export let projectCostBreakdown: { id: string; title: string; cost_usd: number }[];

  // Two-way bound: App resets projectCostExpanded on project switch, so it binds
  // down and back up.
  export let projectCostExpanded: boolean;

  // Actions — App owns the side effects (API calls). All moved out: Validate +
  // its result panel to the project window as a modal (#417), alongside the
  // AI-policy control; Chats/Prompts/Mutations to the app menu, Health Check to
  // the Settings AI tab (#629); loose-scene import to its own "Import
  // documents…" surface (#635); the inheritance roster to the breadcrumb popover
  // (#417 slice 4b); the child roster ("Contains") to the breadcrumb's descent
  // menu (#417 slice 5). What's left here is read-only project info (title +
  // cost), until slice 6 deletes the pane.
</script>

{#if !isProjectOpen}
  <p class="muted project-empty-hint">
    No project open. Pick one from the switcher above — recents, browse, or create new.
  </p>
{:else}
  <div class="project-identity">
    <strong class="project-identity-title">{projectTitle}</strong>
    <!-- The filesystem path moved to the project node's editor window as a
         read-only `path` computed field (#417 slice 3) — off the pane so it
         survives the pane's removal. Title + cost stay here until slice 6. -->
    {#if projectCostTotal != null && projectCostTotal > 0}
      <button
        type="button"
        class="project-cost-chip"
        title="AI cost across all chats in this project. Click to break down by chat."
        on:click={() => (projectCostExpanded = !projectCostExpanded)}
      >
        {formatCostEur(projectCostTotal)} this project
        <span class="project-cost-caret" aria-hidden="true">{projectCostExpanded ? "▾" : "▸"}</span>
      </button>
      {#if projectCostExpanded}
        <ul class="project-cost-breakdown">
          {#each projectCostBreakdown.filter((r) => r.cost_usd > 0) as row (row.id)}
            <li>
              <span class="project-cost-breakdown-title">{row.title}</span>
              <span class="project-cost-breakdown-value">{formatCostEur(row.cost_usd)}</span>
            </li>
          {/each}
          {#if projectCostBreakdown.filter((r) => r.cost_usd > 0).length === 0}
            <li class="muted">No chats with cost yet.</li>
          {/if}
        </ul>
      {/if}
    {/if}
  </div>

  <!--
    The inheritance declaration moved onto the breadcrumb (#417 slice 4b): the
    "edit…" affordance on the populated chain opens a popover hosting the same
    `InheritsFromList`, so the editor lives where the inheritance STATE is now
    shown (slice 4a) rather than in a pane that #417 is retiring. The child
    roster ("Contains") likewise moved to the breadcrumb's descent menu (#417
    slice 5) — both directions of the chain now live on the bar that can't vanish.
  -->
{/if}

<style>
  /* Co-located from styles.css (#14): single-owner Project styles. `.muted` is
     also used here but stays global (shared utility). */
  .project-empty-hint {
    margin: 4px 0;
    font-size: var(--fs-md);
  }

  .project-identity {
    display: grid;
    gap: 6px;
    margin-bottom: 8px;
  }

  .project-identity-title {
    font-size: var(--fs-xl);
    color: var(--text);
  }

  .project-cost-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: 6px;
    padding: 2px 8px;
    font-size: var(--fs-xs);
    background: transparent;
    border: 1px solid var(--divider);
    border-radius: 10px;
    color: var(--text-2);
    cursor: pointer;
    font-variant-numeric: tabular-nums;
  }
  .project-cost-chip:hover {
    background: var(--inset);
  }
  .project-cost-caret {
    font-size: var(--fs-xs);
    opacity: 0.6;
  }
  .project-cost-breakdown {
    list-style: none;
    margin: 4px 0 0;
    padding: 4px 0;
    font-size: var(--fs-xs);
    border-top: 1px dashed var(--divider);
  }
  .project-cost-breakdown li {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    padding: 2px 8px;
  }
  .project-cost-breakdown-value {
    font-variant-numeric: tabular-nums;
    color: var(--text-3);
  }
</style>
