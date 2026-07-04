<script lang="ts">
  // Machine-global assistant-tag color manager (#88). Lists every registered
  // assistant tag with a SwatchPicker; picking a color persists via
  // PUT /api/assistant-tags/{name} and refreshes the shared store, so the
  // colored chips on assistant NodeRows update live. Tags register themselves
  // when a writer tags an assistant/prompt — this surface only assigns colors.
  import SwatchPicker from "@/components/widgets/SwatchPicker.svelte";
  import { api } from "@/lib/api";
  import { assistantTagsStore } from "@/lib/stores/assistantTags";

  let { onClose }: { onClose: () => void } = $props();

  let tags = $derived($assistantTagsStore);

  async function setColor(name: string, color: string | null): Promise<void> {
    assistantTagsStore.set((await api.setAssistantTagColor(name, color)).tags);
  }
</script>

<div
  class="atm-backdrop"
  role="button"
  tabindex="-1"
  aria-label="Close"
  onclick={onClose}
  onkeydown={(e) => e.key === "Escape" && onClose()}
></div>
<div class="atm-panel" role="dialog" aria-label="Assistant tag colors" aria-modal="true">
  <header class="atm-head">
    <h2>Assistant tag colors</h2>
    <button type="button" class="atm-close" title="Close" aria-label="Close" onclick={onClose}>×</button>
  </header>
  {#if tags.length === 0}
    <p class="atm-empty">No assistant tags yet. Tag an assistant or a prompt's assistant scope to register one.</p>
  {:else}
    <ul class="atm-list">
      {#each tags as tag (tag.name)}
        <li class="atm-row">
          <span class="atm-name">{tag.name}</span>
          <SwatchPicker value={tag.color} onChange={(id) => void setColor(tag.name, id)} />
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .atm-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.28);
    z-index: 60;
  }
  .atm-panel {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    z-index: 61;
    width: min(380px, 92vw);
    max-height: 78vh;
    overflow: auto;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    box-shadow: 0 12px 40px rgba(0, 0, 0, 0.28);
    padding: 14px 16px;
  }
  .atm-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;
  }
  .atm-head h2 {
    margin: 0;
    font-size: 14px;
    font-weight: 700;
  }
  .atm-close {
    border: none;
    background: none;
    font-size: 20px;
    line-height: 1;
    cursor: pointer;
    color: var(--text-3);
  }
  .atm-empty {
    color: var(--text-3);
    font-size: 12.5px;
    margin: 6px 2px;
  }
  .atm-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .atm-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 5px 6px;
    border-radius: 6px;
  }
  .atm-row:hover {
    background: var(--inset);
  }
  .atm-name {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-1);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
