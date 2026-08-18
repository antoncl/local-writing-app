<script lang="ts">
  // Shared modal chrome — the backdrop, the centered frame, the title header,
  // and the right-aligned action footer. Svelte has no component inheritance,
  // so this is the composition stand-in for a "base dialog class": the dialogs
  // (ConfirmModal, CreateProjectWizard, MachineSettingsDialog) compose this Modal
  // instead of re-declaring the chrome, and the chrome's CSS lives here in one
  // scoped style block rather than as global classes everyone shares.
  //
  // The open/close guard stays with each caller (they have different
  // conditions — `state`, `open`, `open && draft`), so Modal renders
  // unconditionally and the caller wraps it in its own {#if}.
  import type { Snippet } from "svelte";

  let {
    // Title text (the <h2>) and the dialog's accessible name.
    title,
    // Backdrop's accessible name; defaults to the title.
    label = "",
    // Extra class on the frame (for per-dialog descendant styling).
    frameClass = "",
    // Inline style on the frame — consumers size it by setting the --modal-*
    // custom properties here (e.g. a wider settings dialog). Custom props beat
    // the scoped default cleanly, without a specificity fight.
    frameStyle = "",
    // Footer buttons; the body is the default slot content.
    actions = undefined,
    children = undefined,
  }: {
    title: string;
    label?: string;
    frameClass?: string;
    frameStyle?: string;
    actions?: Snippet;
    children?: Snippet;
  } = $props();

  const backdropLabel = $derived(label || title);
</script>

<section class="modal-backdrop" aria-label={backdropLabel}>
  <div class="confirm-modal {frameClass}" style={frameStyle} role="dialog" aria-modal="true" aria-label={title}>
    <header class="confirm-modal-header">
      <h2>{title}</h2>
    </header>
    {@render children?.()}
    {#if actions}
      <div class="confirm-modal-actions">
        {@render actions()}
      </div>
    {/if}
  </div>
</section>

<style>
  .modal-backdrop {
    position: fixed;
    inset: 0;
    z-index: 2000;
    display: grid;
    place-items: center;
    padding: 24px;
    background: var(--scrim);
  }

  .confirm-modal {
    display: grid;
    gap: 14px;
    /* Defaults; consumers override via --modal-* custom props (see frameStyle). */
    width: var(--modal-width, min(420px, calc(100vw - 48px)));
    max-height: var(--modal-max-height, none);
    overflow-y: var(--modal-overflow-y, visible);
    padding: 18px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    box-shadow: var(--elev-3);
  }

  .confirm-modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  /* Paragraphs are slotted in by the consuming dialog, so they carry the
     consumer's scope hash, not Modal's — :global keeps the rule from being
     pruned. */
  .confirm-modal :global(p) {
    margin: 0;
    color: var(--text-2);
    font-size: var(--fs-md);
    line-height: 1.45;
    white-space: pre-line;
  }

  .confirm-modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }
</style>
