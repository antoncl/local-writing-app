<script lang="ts">
  import type { AIHealthResponse, AIPolicy, ProjectValidation } from "./types";
  import { formatCostEur } from "./money";

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
