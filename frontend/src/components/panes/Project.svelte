<script lang="ts">
  import type { AIHealthResponse, AIPolicy, ProjectChild, ProjectValidation } from "@/lib/types";
  import NodeList from "@/components/widgets/NodeList.svelte";
  import NodeRow from "@/components/widgets/NodeRow.svelte";
  import { formatCostEur } from "@/lib/utils/money";

  export let isProjectOpen: boolean;
  export let projectTitle: string;
  export let projectPath: string;
  export let projectCostTotal: number | null;
  export let projectCostBreakdown: { id: string; title: string; cost_usd: number }[];
  export let aiHealthResult: AIHealthResponse | null;
  export let aiHealthChecking: boolean;
  export let validation: ProjectValidation | null;
  // Project folders directly inside this one (#310). Direct children only —
  // a level offers the places you can open *from here*, not the whole shelf.
  // Empty for a leaf, which is the only thing that distinguishes one: there
  // is no level type to branch on, and depth is not consulted anywhere.
  export let projectChildren: ProjectChild[] = [];

  // Two-way bound: App is the source of truth. aiPolicy is set on project load
  // and read back when saving AI settings; projectCostExpanded is bound because
  // App resets it on project switch. Both stay there and bind down.
  export let aiPolicy: AIPolicy;
  export let projectCostExpanded: boolean;

  // Actions — App owns the side effects (API calls, opening other panes).
  export let onValidate: () => void;
  export let onOpenChats: () => void;
  export let onSaveAISettings: () => void;
  export let onHealthCheck: () => void;
  export let onOpenPrompts: () => void;
  export let onOpenMutations: () => void;
  export let onRepair: () => void;
  // Opening a child is a resolution-scope change, i.e. a unit boundary
  // (ADR-0045) — App routes it through the same open path as the switcher
  // rather than mutating anything in place.
  export let onOpenChild: (path: string) => void;
</script>

{#if !isProjectOpen}
  <p class="muted project-empty-hint">
    No project open. Pick one from the switcher above — recents, browse, or create new.
  </p>
{:else}
  <div class="project-identity">
    <strong class="project-identity-title">{projectTitle}</strong>
    <code class="project-identity-path" title={projectPath}>{projectPath}</code>
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
    <div class="button-row">
      <button type="button" on:click={onValidate}>Validate</button>
    </div>
  </div>

  <!--
    The child roster (#310). Rendered only when there is something in it: a
    leaf has no children, and an always-present empty section would be noise on
    every book. That emptiness IS the only leaf/non-leaf distinction in the UI —
    no depth, no level type, nothing derived from the chain's shape.
  -->
  {#if projectChildren.length > 0}
    <section class="project-children" aria-label="Projects inside this one">
      <h3>Contains</h3>
      <NodeList isEmpty={false}>
        {#each projectChildren as child (child.path)}
          <!--
            `detail` is the folder name, and only when it differs from the
            title: a project keeps its folder name as its default title, so
            passing it unconditionally prints the same string twice on exactly
            the projects nobody has renamed yet.

            No `dataNodeId`: it exists so focus helpers can find a row by node
            id, and a filesystem path is not one. ViewNodeList interpolates that
            attribute straight into a `querySelector`, so putting a Windows path
            there is a hazard bought for nothing.
          -->
          <NodeRow
            title={child.title}
            detail={child.name === child.title ? null : child.name}
            ariaLabel={`Open ${child.title}`}
            onClick={() => onOpenChild(child.path)}
          />
        {/each}
      </NodeList>
    </section>
  {/if}
{/if}

<section class="ai-settings" aria-label="AI settings" class:disabled-section={!isProjectOpen}>
  <h3>AI</h3>
  {#if isProjectOpen}
  <div class="button-row">
    <button type="button" on:click={onOpenChats}>Chats…</button>
  </div>
  {/if}
  {#if isProjectOpen}
    <fieldset class="ai-policy">
      <legend>AI access</legend>
      <label><input type="radio" bind:group={aiPolicy} value="off" /> Off</label>
      <label><input type="radio" bind:group={aiPolicy} value="local-only" /> Local only</label>
      <label><input type="radio" bind:group={aiPolicy} value="cloud-allowed" /> Cloud allowed</label>
    </fieldset>
    <div class="button-row">
      <button type="button" on:click={onSaveAISettings}>Save AI Settings</button>
      <button type="button" disabled={aiHealthChecking || aiPolicy === "off"} on:click={onHealthCheck}>
        {aiHealthChecking ? "Pinging…" : "Health Check"}
      </button>
    </div>
    <div class="button-row">
      <button type="button" on:click={onOpenPrompts}>Prompts…</button>
      <button type="button" on:click={onOpenMutations}>Mutations…</button>
    </div>
    {#if aiHealthResult}
      <p class="ai-health-result" class:ok={aiHealthResult.ok} class:fail={!aiHealthResult.ok}>
        {#if aiHealthResult.ok}
          ✓ {aiHealthResult.provider} · {aiHealthResult.model} · {aiHealthResult.latency_ms} ms
        {:else}
          ✗ {aiHealthResult.provider || "(no provider)"} — {aiHealthResult.error}
        {/if}
      </p>
    {/if}
  {/if}
</section>
{#if validation}
  <section class:invalid={!validation.valid} class="validation-panel" aria-label="Project validation result">
    <h3>{validation.valid ? "Project Looks Consistent" : "Project Issues Found"}</h3>
    {#if validation.migrations_applied.length > 0}
      <strong>Migrations Applied</strong>
      {#each validation.migrations_applied as migration}
        <p class="migration-applied">{migration}</p>
      {/each}
    {/if}
    {#if validation.errors.length > 0}
      <strong>Errors</strong>
      {#each validation.errors as validationError}
        <p>{validationError}</p>
      {/each}
    {/if}
    {#if validation.warnings.length > 0}
      <strong>Warnings</strong>
      {#each validation.warnings as validationWarning}
        <p>{validationWarning}</p>
      {/each}
    {/if}
    {#if validation.errors.length === 0 && validation.warnings.length === 0}
      <p>No structure, scene, or TODO synchronization issues found.</p>
    {/if}
    {#if validation.errors.length > 0 || validation.warnings.length > 0}
      <div class="validation-actions">
        <button type="button" on:click={onRepair}>Repair TODO Links</button>
      </div>
    {/if}
  </section>
{/if}

<style>
  /* Co-located from styles.css (#14): single-owner Project styles. `.muted` and
     `.button-row` are also used here but stay global (shared utilities). */
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

  .project-identity-path {
    font-size: var(--fs-xs);
    color: var(--text-3);
    background: var(--inset);
    border: 1px solid var(--divider);
    border-radius: 3px;
    padding: 2px 6px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--mono);
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

  /* Same section rhythm as the AI block below — a sibling section of the
     pane, not a nested treatment. The rows inside are plain NodeRows, so
     they carry the canonical card chrome and need nothing here. */
  .project-children,
  .ai-settings {
    display: grid;
    gap: 10px;
    margin-top: 16px;
    padding-top: 14px;
    border-top: 1px solid var(--border);
  }

  .project-children h3,
  .ai-settings h3 {
    margin: 0;
    font-size: var(--fs-md);
    font-weight: 600;
    color: var(--text);
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .ai-policy {
    display: flex;
    flex-wrap: wrap;
    gap: 14px;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 10px;
  }

  .ai-policy legend {
    font-size: var(--fs-sm);
    color: var(--text-2);
    padding: 0 4px;
  }

  .ai-policy label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: var(--fs-md);
  }

  .ai-health-result {
    margin: 0;
    padding: 8px 10px;
    border-radius: 4px;
    font-size: var(--fs-md);
    line-height: 1.4;
  }

  .ai-health-result.ok {
    background: var(--accent-soft);
    color: var(--accent-deep);
    border: 1px solid var(--accent-soft2);
  }

  .ai-health-result.fail {
    background: var(--danger-soft);
    color: var(--danger);
    border: 1px solid var(--danger-border);
  }

  .disabled-section {
    opacity: 0.6;
  }

  .migration-applied {
    color: var(--accent-deep);
    font-family: var(--mono);
    font-size: var(--fs-sm);
  }

  .validation-panel {
    display: grid;
    gap: 5px;
    padding: 10px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--surface);
  }

  .validation-panel.invalid {
    border-color: var(--star-border);
    background: var(--star-soft);
  }

  .validation-panel strong {
    margin-top: 4px;
    color: var(--text-2);
    font-size: var(--fs-sm);
    text-transform: uppercase;
  }

  .validation-panel p {
    margin: 0;
    color: var(--text-2);
    font-size: var(--fs-sm);
    line-height: 1.35;
  }

  .validation-actions {
    display: flex;
    justify-content: flex-end;
    margin-top: 6px;
  }
</style>
