<script lang="ts">
  import type { AIHealthResponse, AIPolicy, ProjectValidation } from "@/lib/types";
  import { formatCostEur } from "@/lib/utils/money";

  export let isProjectOpen: boolean;
  export let projectTitle: string;
  export let projectPath: string;
  export let projectCostTotal: number | null;
  export let projectCostBreakdown: { id: string; title: string; cost_usd: number }[];
  export let aiHealthResult: AIHealthResponse | null;
  export let aiHealthChecking: boolean;
  export let validation: ProjectValidation | null;

  // Two-way bound: App is the source of truth (these are set on project load
  // and read back when saving AI settings), so they stay there and bind down.
  // projectCostExpanded is bound too because App resets it on project switch.
  export let aiPolicy: AIPolicy;
  export let aiDefaultProvider: string;
  export let aiDefaultModelClass: string;
  export let projectCostExpanded: boolean;

  // Actions — App owns the side effects (API calls, opening other panes).
  export let onValidate: () => void;
  export let onOpenChats: () => void;
  export let onSaveAISettings: () => void;
  export let onHealthCheck: () => void;
  export let onOpenPrompts: () => void;
  export let onOpenMutations: () => void;
  export let onRepair: () => void;
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
    <label>
      Preferred subscription
      <select bind:value={aiDefaultProvider}>
        <option value="">(machine default)</option>
        <option value="anthropic">Anthropic</option>
        <option value="openai">OpenAI</option>
        <option value="openrouter">OpenRouter</option>
        <option value="ollama">Ollama (local)</option>
      </select>
    </label>
    <label>
      Preferred assistant tier
      <select bind:value={aiDefaultModelClass}>
        <option value="">(unset)</option>
        <option value="cheap">cheap</option>
        <option value="balanced">balanced</option>
        <option value="best">best</option>
      </select>
    </label>
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
    font-size: 13px;
  }

  .project-identity {
    display: grid;
    gap: 6px;
    margin-bottom: 8px;
  }

  .project-identity-title {
    font-size: 16px;
    color: var(--text);
  }

  .project-identity-path {
    font-size: 11px;
    color: var(--text-3);
    background: var(--inset);
    border: 1px solid var(--divider);
    border-radius: 3px;
    padding: 2px 6px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }

  .project-cost-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    margin-top: 6px;
    padding: 2px 8px;
    font-size: 0.82em;
    background: transparent;
    border: 1px solid var(--color-border, #444);
    border-radius: 10px;
    color: var(--color-text, #ccc);
    cursor: pointer;
    font-variant-numeric: tabular-nums;
  }
  .project-cost-chip:hover {
    background: var(--color-hover, rgba(255, 255, 255, 0.05));
  }
  .project-cost-caret {
    font-size: 0.85em;
    opacity: 0.6;
  }
  .project-cost-breakdown {
    list-style: none;
    margin: 4px 0 0;
    padding: 4px 0;
    font-size: 0.82em;
    border-top: 1px dashed var(--color-border-soft, #333);
  }
  .project-cost-breakdown li {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    padding: 2px 8px;
  }
  .project-cost-breakdown-value {
    font-variant-numeric: tabular-nums;
    color: var(--color-muted, #888);
  }

  .ai-settings {
    display: grid;
    gap: 10px;
    margin-top: 16px;
    padding-top: 14px;
    border-top: 1px solid var(--border);
  }

  .ai-settings h3 {
    margin: 0;
    font-size: 13px;
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
    font-size: 12px;
    color: var(--text-2);
    padding: 0 4px;
  }

  .ai-policy label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 13px;
  }

  .ai-health-result {
    margin: 0;
    padding: 8px 10px;
    border-radius: 4px;
    font-size: 13px;
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
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12px;
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
    font-size: 12px;
    text-transform: uppercase;
  }

  .validation-panel p {
    margin: 0;
    color: var(--text-2);
    font-size: 12px;
    line-height: 1.35;
  }

  .validation-actions {
    display: flex;
    justify-content: flex-end;
    margin-top: 6px;
  }
</style>
