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
  import Modal from "@/components/dialogs/Modal.svelte";

  export let state: ConfirmationState | null = null;
  export let onCancel: () => void = () => {};
  export let onConfirm: (dontShowAgain: boolean) => void | Promise<void> = () => {};

  // Reset the checkbox whenever a new confirmation opens (depends only on
  // `state`, so ticking the box itself doesn't re-trigger the reset).
  let dontShowAgain = false;
  $: state, (dontShowAgain = false);
</script>

{#if state}
  <Modal title={state.title}>
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
    {#snippet actions()}
      <button type="button" on:click={onCancel}>Cancel</button>
      <button
        class:danger-primary={state.destructive}
        class:primary={!state.destructive}
        type="button"
        on:click={() => onConfirm(dontShowAgain)}
      >
        {state.confirmLabel}
      </button>
    {/snippet}
  </Modal>
{/if}

<style>
  /* ConfirmModal-only body bits — these render in this component's own DOM
     (passed as Modal's slotted content), so plain scoped rules match. */
  .confirm-modal-details {
    margin: 0;
    padding-left: 20px;
    color: var(--text-2);
    font-size: 13px;
    line-height: 1.5;
    max-height: 200px;
    overflow: auto;
  }

  .confirm-modal-undo {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 0 !important;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--danger, #9d2f2a);
  }

  .confirm-modal-dsa {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: 12.5px;
    color: var(--text-2, var(--text-2));
    cursor: pointer;
  }

  .confirm-modal-dsa input {
    width: auto;
    margin: 0;
  }
</style>
