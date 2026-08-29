<script lang="ts">
  // Project validation results, as a modal launched from the project window's
  // "Validate" action (#417 — moved off the Project pane so it lives on a
  // surface that can't vanish). Purely presentational: App owns the run() side
  // effects (validate / repair) and passes the result + a checking flag down;
  // the parent owns the `open` guard, matching the other dialogs.
  //
  // Not a permission control, so no draft/explicit-save dance (unlike
  // AIPolicyModal): validate is a read, repair is an idempotent fix the user
  // asked for by clicking it here.
  import type { CodeFencedBody, ProjectValidation } from "@/lib/types";
  import Modal from "@/components/dialogs/Modal.svelte";

  let {
    open,
    onClose,
    validation,
    checking,
    onRepair,
    onUnwrap,
  }: {
    open: boolean;
    onClose: () => void;
    validation: ProjectValidation | null;
    checking: boolean;
    onRepair: () => void;
    // Offer to unwrap one entry whose whole body is a code fence (#1628). Opens
    // the entry with the unwrapped body proposed as a standard revision review —
    // the write is the user's Commit, never this click.
    onUnwrap: (fenced: CodeFencedBody) => void;
  } = $props();

  let hasIssues = $derived(
    !!validation && (validation.errors.length > 0 || validation.warnings.length > 0),
  );
</script>

{#if open}
  <Modal title="Validate project" label="Project validation result" frameStyle="--modal-width: min(480px, 92vw);">
    {#if checking}
      <p class="validate-status">Checking project files…</p>
    {:else if validation}
      <div class:invalid={!validation.valid} class="validation-body">
        <h3>{validation.valid ? "Project looks consistent" : "Project issues found"}</h3>
        {#if validation.migrations_applied.length > 0}
          <strong>Migrations applied</strong>
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
        {#if validation.code_fenced_bodies.length > 0}
          <strong>Bodies wrapped in a code block</strong>
          {#each validation.code_fenced_bodies as fenced (fenced.id)}
            <div class="code-fenced-row">
              <p><span class="fenced-title">{fenced.title}</span> renders as source — its whole body is one code block, likely a paste.</p>
              <button type="button" class="unwrap" onclick={() => onUnwrap(fenced)}>Unwrap…</button>
            </div>
          {/each}
        {/if}
        {#if validation.errors.length === 0 && validation.warnings.length === 0 && validation.code_fenced_bodies.length === 0}
          <p>No structure, scene, or TODO synchronization issues found.</p>
        {/if}
      </div>
    {:else}
      <p class="validate-status">No validation has run yet.</p>
    {/if}
    {#snippet actions()}
      {#if hasIssues}
        <!-- Disabled while a check/repair is in flight so a second click can't
             fire a concurrent repair POST (the body reads "Checking…" but this
             stays rendered off the pre-run result). -->
        <button type="button" onclick={onRepair} disabled={checking}>Repair TODO Links</button>
      {/if}
      <button type="button" class="primary" onclick={onClose}>Close</button>
    {/snippet}
  </Modal>
{/if}

<style>
  .validate-status {
    margin: 0;
    color: var(--text-2);
    font-size: var(--fs-md);
  }

  .validation-body {
    display: grid;
    gap: 5px;
  }

  .validation-body h3 {
    margin: 0 0 4px;
    font-size: var(--fs-md);
    color: var(--text-1);
  }

  .validation-body.invalid h3 {
    color: var(--star-border);
  }

  .validation-body strong {
    margin-top: 4px;
    color: var(--text-2);
    font-size: var(--fs-sm);
    text-transform: uppercase;
  }

  .validation-body p {
    margin: 0;
    color: var(--text-2);
    font-size: var(--fs-sm);
    line-height: 1.35;
  }

  .migration-applied {
    color: var(--accent-deep);
    font-family: var(--mono);
    font-size: var(--fs-sm);
  }

  .code-fenced-row {
    display: flex;
    align-items: baseline;
    gap: 10px;
  }

  .code-fenced-row p {
    flex: 1;
  }

  .fenced-title {
    color: var(--text-1);
    font-weight: 600;
  }

  .unwrap {
    flex: none;
    font-size: var(--fs-sm);
    padding: 2px 8px;
    color: var(--text-2);
    background: transparent;
    border: 1px solid var(--border);
    border-radius: 4px;
    cursor: pointer;
  }

  .unwrap:hover:not(:disabled) {
    color: var(--text-1);
    border-color: var(--text-3);
  }

  .unwrap:disabled {
    opacity: 0.5;
    cursor: default;
  }
</style>
