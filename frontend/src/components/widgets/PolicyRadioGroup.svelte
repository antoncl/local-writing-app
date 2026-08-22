<script lang="ts">
  // The AI-access radio group, shared by the per-project AIPolicyModal and the
  // app-wide "Default AI access" control in Settings → AI (#780 — the two had
  // drifting copies of this fieldset + its CSS). It renders only the stops; the
  // fails-closed commit (a radio click never persists on its own) stays with
  // each host, which owns its own draft/Save gesture
  // (decisions_ai_permission_fails_closed).
  //
  // `includeInherit` is the one real difference between the two: the per-project
  // control offers "Inherit" (take the ancestor's policy, or Off at the top of
  // the chain); the app-wide floor is that top, so it omits it.
  import type { AIPolicyDraft } from "@/lib/stores/aiSettings.svelte";

  let {
    value = $bindable("off"),
    includeInherit = false,
  }: {
    value?: AIPolicyDraft;
    includeInherit?: boolean;
  } = $props();
</script>

<fieldset class="ai-policy">
  <legend>Access</legend>
  {#if includeInherit}
    <label
      title="Set no policy of your own — inherit it from an ancestor project, or default to Off (#471)"
    >
      <input type="radio" bind:group={value} value="inherit" /> Inherit
    </label>
  {/if}
  <label><input type="radio" bind:group={value} value="off" /> Off</label>
  <label><input type="radio" bind:group={value} value="local-only" /> Local only</label>
  <label><input type="radio" bind:group={value} value="cloud-allowed" /> Cloud allowed</label>
</fieldset>

<style>
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

</style>
