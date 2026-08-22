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
    // Optional second resolution rendered next to the primary (e.g.
    // "Discard changes and close"); Cancel still means "do neither".
    secondaryLabel?: string;
    onSecondary?: () => Promise<void> | void;
  };
</script>

<script lang="ts">
  import Modal from "@/components/dialogs/Modal.svelte";

  // Destructured as `confirmState` locally (not `state`) — a local binding
  // named `state` collides with the `$state` rune used below for
  // `dontShowAgain` (Svelte reads `$state` as an auto-subscription to a
  // local `state` variable in that case). The external prop name stays
  // `state` for callers (e.g. `<ConfirmModal state={...} />`).
  let {
    state: confirmState = null,
    onCancel = () => {},
    onConfirm = () => {},
    onSecondary = () => {},
  }: {
    state?: ConfirmationState | null;
    onCancel?: () => void;
    onConfirm?: (dontShowAgain: boolean) => void | Promise<void>;
    onSecondary?: () => void | Promise<void>;
  } = $props();

  // Reset the checkbox whenever a new confirmation opens (depends only on
  // `confirmState`, so ticking the box itself doesn't re-trigger the reset).
  let dontShowAgain = $state(false);
  $effect(() => {
    confirmState;
    dontShowAgain = false;
  });
</script>

{#if confirmState}
  <Modal title={confirmState.title}>
    <p>{confirmState.message}</p>
    {#if confirmState.details && confirmState.details.length > 0}
      <ul class="confirm-modal-details">
        {#each confirmState.details as detail}
          <li>{detail}</li>
        {/each}
      </ul>
    {/if}
    {#if confirmState.cannotBeUndone}
      <p class="confirm-modal-undo"><i class="ti ti-alert-triangle" aria-hidden="true"></i> This cannot be undone.</p>
    {/if}
    {#if confirmState.dontShowAgainKey}
      <label class="confirm-modal-dsa">
        <input type="checkbox" bind:checked={dontShowAgain} />
        Don't show this again
      </label>
    {/if}
    {#snippet actions()}
      <button type="button" onclick={onCancel}>Cancel</button>
      {#if confirmState.secondaryLabel}
        <button type="button" onclick={() => onSecondary()}>{confirmState.secondaryLabel}</button>
      {/if}
      <button
        class:danger-primary={confirmState.destructive}
        class:primary={!confirmState.destructive}
        type="button"
        onclick={() => onConfirm(dontShowAgain)}
      >
        {confirmState.confirmLabel}
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
    font-size: var(--fs-md);
    line-height: 1.5;
    max-height: 200px;
    overflow: auto;
  }

  .confirm-modal-undo {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 0 !important;
    font-size: var(--fs-sm);
    font-weight: 600;
    color: var(--danger);
  }

  .confirm-modal-dsa {
    display: flex;
    align-items: center;
    gap: 7px;
    font-size: var(--fs-sm);
    color: var(--text-2);
    cursor: pointer;
  }

  .confirm-modal-dsa input {
    margin: 0;
  }
</style>
