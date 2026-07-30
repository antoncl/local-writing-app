<script lang="ts">
  // The one "Manage tags" home (#247, slice 2 PR-3b). Both tag vocabularies —
  // project tags (per-layer, scoped) and the flat, machine-global assistant
  // tags — are governed from the SAME roster the "+" popover uses, injected with
  // its vocabulary's adapter. No add-target here (onAdd omitted), so each row is
  // a static label whose ⋯ opens Rename / Merge / colour (+ Suggest-on for the
  // scoped project vocabulary). Retires the old lopsided TagManagerDialog
  // (project scope/merge, no colour) + AssistantTagManager (colour only).
  //
  // No onChanged: every governance op calls its adapter.reconcile(), which bumps
  // App's one tag-vocabulary-revision signal; App's refreshAfterTagChange then
  // re-syncs both rosters (the stores we read below) and any open editors.
  import TagRosterPopover from "@/components/widgets/TagRosterPopover.svelte";
  import { knownTagsStore } from "@/lib/stores/tags";
  import { assistantTagsStore, assistantTagsAsScoped } from "@/lib/stores/assistantTags";
  import { projectTagGovernance, assistantTagGovernance } from "@/lib/utils/tagGovernance";

  let { onClose }: { onClose: () => void } = $props();

  const projectTags = $derived($knownTagsStore);
  const assistantTags = $derived(assistantTagsAsScoped($assistantTagsStore));
  // The roster's "already added" affordance is entity-only; nothing is selected
  // in the manager.
  const noSelection = new Set<string>();
</script>

<div class="gm-backdrop" role="presentation" onmousedown={onClose}>
  <div
    class="gm-dialog tm-dialog"
    role="dialog"
    aria-modal="true"
    aria-label="Manage tags"
    tabindex="-1"
    onmousedown={(e) => e.stopPropagation()}
  >
    <header class="gm-head">
      <i class="ti ti-tag" aria-hidden="true"></i>
      <h2>Manage tags</h2>
      <button class="gm-close" type="button" onclick={onClose}>Close</button>
    </header>

    <div class="gm-body tm-body">
      <section class="tm-section">
        <h3 class="tm-section-head">Project tags</h3>
        {#if projectTags.length === 0}
          <p class="tm-section-empty">No project tags yet. Tag a scene or entry to register one.</p>
        {:else}
          <TagRosterPopover
            tags={projectTags}
            selectedKeys={noSelection}
            adapter={projectTagGovernance}
            ariaLabel="Project"
          />
        {/if}
      </section>

      <section class="tm-section">
        <h3 class="tm-section-head">Assistant tags</h3>
        {#if assistantTags.length === 0}
          <p class="tm-section-empty">
            No assistant tags yet. Tag an assistant or a prompt's assistant scope to register one.
          </p>
        {:else}
          <TagRosterPopover
            tags={assistantTags}
            selectedKeys={noSelection}
            adapter={assistantTagGovernance}
            ariaLabel="Assistant"
          />
        {/if}
      </section>
    </div>
  </div>
</div>

<style>
  .gm-backdrop {
    position: fixed;
    inset: 0;
    z-index: var(--z-modal);
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--scrim);
  }
  .gm-dialog {
    width: 560px;
    max-width: calc(100vw - 40px);
    max-height: calc(100vh - 80px);
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border: 1px solid var(--border-strong);
    border-radius: 14px;
    background: var(--surface);
    box-shadow: var(--elev-3);
  }
  .gm-head {
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--divider);
    background: var(--panel);
  }
  .gm-head h2 {
    margin: 0;
    font-family: var(--serif);
    font-size: var(--fs-xl);
    font-weight: 600;
  }
  .gm-close {
    margin-left: auto;
    padding: 5px 11px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    font-size: var(--fs-sm);
    cursor: pointer;
  }
  .gm-body {
    overflow: auto;
    padding: 12px 16px 16px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  .tm-section {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .tm-section-head {
    margin: 0;
    font-size: var(--fs-xs);
    font-weight: 800;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--text-3);
  }
  .tm-section-empty {
    margin: 2px 2px 4px;
    font-size: var(--fs-sm);
    color: var(--text-3);
  }
</style>
