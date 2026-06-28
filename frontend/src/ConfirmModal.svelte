<script lang="ts" module>
  // Generic confirm/cancel modal. The parent owns the state machine —
  // pass `state` to show, null to hide. onConfirm fires the user's
  // chosen action; onCancel dismisses without doing anything.
  // Lives in <script module> because Svelte 5 disallows type exports from
  // instance scripts.
  export type ConfirmationState = {
    title: string;
    message: string;
    details?: string[];
    confirmLabel: string;
    destructive: boolean;
    // When true, show a prominent "this cannot be undone" warning line.
    cannotBeUndone?: boolean;
    // When set, render a "Don't show this again" checkbox; the parent
    // receives its value in onConfirm and persists suppression per key.
    dontShowAgainKey?: string;
    onConfirm: () => Promise<void> | void;
  };
</script>

<script lang="ts">
  export let state: ConfirmationState | null = null;
  export let onCancel: () => void = () => {};
  export let onConfirm: (dontShowAgain: boolean) => void | Promise<void> = () => {};

  // Reset the checkbox whenever a new confirmation opens (depends only on
  // `state`, so ticking the box itself doesn't re-trigger the reset).
  let dontShowAgain = false;
  $: state, (dontShowAgain = false);
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
      {#if state.cannotBeUndone}
        <p class="confirm-modal-undo"><i class="ti ti-alert-triangle" aria-hidden="true"></i> This cannot be undone.</p>
      {/if}
      {#if state.dontShowAgainKey}
        <label class="confirm-modal-dsa">
          <input type="checkbox" bind:checked={dontShowAgain} />
          Don't show this again
        </label>
      {/if}
      <div class="confirm-modal-actions">
        <button type="button" on:click={onCancel}>Cancel</button>
        <button
          class:danger-primary={state.destructive}
          class:primary={!state.destructive}
          type="button"
          on:click={() => onConfirm(dontShowAgain)}
        >
          {state.confirmLabel}
        </button>
      </div>
    </div>
  </section>
{/if}
