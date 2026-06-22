<script lang="ts">
  // Generic confirm/cancel modal. The parent owns the state machine —
  // pass `state` to show, null to hide. onConfirm fires the user's
  // chosen action; onCancel dismisses without doing anything.
  export type ConfirmationState = {
    title: string;
    message: string;
    details?: string[];
    confirmLabel: string;
    destructive: boolean;
    onConfirm: () => Promise<void> | void;
  };

  export let state: ConfirmationState | null = null;
  export let onCancel: () => void = () => {};
  export let onConfirm: () => void | Promise<void> = () => {};
</script>

{#if state}
  <section class="modal-backdrop" aria-label={state.title}>
    <div class="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <header class="confirm-modal-header">
        <h2 id="confirm-title">{state.title}</h2>
      </header>
      <p>{state.message}</p>
      {#if state.details && state.details.length > 0}
        <ul class="confirm-modal-details">
          {#each state.details as detail}
            <li>{detail}</li>
          {/each}
        </ul>
      {/if}
      <div class="confirm-modal-actions">
        <button type="button" on:click={onCancel}>Cancel</button>
        <button
          class:danger-primary={state.destructive}
          class:primary={!state.destructive}
          type="button"
          on:click={onConfirm}
        >
          {state.confirmLabel}
        </button>
      </div>
    </div>
  </section>
{/if}
