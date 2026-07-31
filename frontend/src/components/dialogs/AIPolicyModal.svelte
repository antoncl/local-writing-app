<script lang="ts">
  // The per-project AI access policy, as a modal launched from the project
  // window's "AI Policy" action (#417 — moved off the Project pane so it lives
  // on a surface that can't vanish). The parent owns the `open` guard, matching
  // the other dialogs.
  //
  // Fails-closed (decisions_ai_permission_fails_closed): a radio click alone
  // never persists. The modal holds a local draft; only Save commits it to the
  // aiSettings controller and writes it back. Cancel/close discards the draft —
  // cleaner than the old pane, which left the controller's value mutated.
  import { aiSettings, type AIPolicyDraft } from "@/lib/stores/aiSettings.svelte";
  import Modal from "@/components/dialogs/Modal.svelte";
  import PolicyRadioGroup from "@/components/widgets/PolicyRadioGroup.svelte";

  let { open, onClose }: { open: boolean; onClose: () => void } = $props();

  let draft = $state<AIPolicyDraft>("off");

  // Snapshot the stored policy on each open→shown transition only; a later
  // controller change (e.g. our own save) must not re-seed a live edit.
  let wasOpen = false;
  $effect(() => {
    if (open && !wasOpen) draft = aiSettings.policy;
    wasOpen = open;
  });

  async function save(): Promise<void> {
    aiSettings.policy = draft; // commit the draft, then persist — the one place
    // AI access is written (fails-closed). Close only when the persist landed;
    // on failure `save` surfaces the error and we stay open so the change isn't
    // silently lost on a permission control.
    if (await aiSettings.save()) onClose();
  }
</script>

{#if open}
  <Modal title="AI access" label="AI access policy" frameStyle="--modal-width: min(420px, 92vw);">
    <p class="ai-policy-help">
      Controls whether this project may reach AI providers. <strong>Inherit</strong> takes the
      policy from an ancestor project — or Off at the top of the chain.
    </p>
    <PolicyRadioGroup bind:value={draft} includeInherit />
    {#snippet actions()}
      <button type="button" onclick={onClose}>Cancel</button>
      <button type="button" class="primary" onclick={save}>Save</button>
    {/snippet}
  </Modal>
{/if}

<style>
  .ai-policy-help {
    margin: 0 0 12px;
    font-size: var(--fs-sm);
    color: var(--text-2);
    line-height: 1.4;
  }
</style>
