<!--
  ChatJournalScope — "In context" strip for ChatBodyView (#99). Purely
  presentational read-through of the chat's implicit-context journal; the
  parent owns the journal + fresh-id state and passes them in.
-->
<script lang="ts">
  import type { ChatSessionJournalEntry } from "@/lib/types";

  interface Props {
    journal: ChatSessionJournalEntry[];
    freshIds: Set<string>;
  }

  let { journal, freshIds }: Props = $props();
</script>

<div class="cbv-journal-scope" aria-label="Lore entries currently in this chat's implicit-context cache">
  <span class="cbv-journal-scope-label">In context:</span>
  {#each journal as entry (entry.entry_id)}
    <span
      class="cbv-journal-scope-chip"
      class:cbv-journal-scope-chip-fresh={freshIds.has(entry.entry_id)}
      class:cbv-journal-scope-chip-depth1={entry.source === "depth1_expansion"}
      title={entry.source === "depth1_expansion"
        ? `${entry.title} — pulled in because another entity's body mentions it`
        : `${entry.title} — detected in a user message`}
    >
      {entry.title || entry.entry_id}
      {#if freshIds.has(entry.entry_id)}
        <span class="cbv-journal-scope-pip cbv-journal-scope-pip-fresh">FRESH</span>
      {:else if entry.source === "depth1_expansion"}
        <span class="cbv-journal-scope-pip cbv-journal-scope-pip-depth1">↳ depth 1</span>
      {/if}
    </span>
  {/each}
</div>

<style>
  /* ---- 6 · journal scope (inset) ---- */
  /* flex: 0 0 auto keeps the strip at natural height as a flex child of
     .chat-body-view (was carried by the shared sibling-group rule in the
     parent before this block moved out — #99). */
  .cbv-journal-scope {
    flex: 0 0 auto;
    display: flex; flex-wrap: wrap; gap: 6px 7px; align-items: center;
    padding: 11px 14px; border-radius: 10px; border: 1px solid var(--divider);
    background: var(--inset); font-size: var(--fs-xs);
  }
  .cbv-journal-scope-label {
    font-size: var(--fs-xs); font-weight: 800; letter-spacing: 0.07em; text-transform: uppercase; color: var(--text-3);
  }
  .cbv-journal-scope-chip {
    display: inline-flex; align-items: center; gap: 6px; padding: 2px 9px; border-radius: 999px;
    background: var(--k-lore-soft); border: 1px solid var(--k-lore-border);
    color: var(--k-lore-text); font-weight: 600;
    transition: background 250ms ease-out, border-color 250ms ease-out;
  }
  .cbv-journal-scope-chip::before {
    content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--k-lore);
  }
  .cbv-journal-scope-chip-depth1 { background: var(--surface); border-style: dashed; }
  /* Dimmer dot than the base chip: depth1 (ancestor) reads fainter than fresh. */
  .cbv-journal-scope-chip-depth1::before { background: var(--k-lore-border); }
  .cbv-journal-scope-chip-fresh { border-color: var(--accent-soft2); }
  .cbv-journal-scope-chip-fresh::before { background: var(--accent); }
  .cbv-journal-scope-pip {
    font-size: var(--fs-xs); font-weight: 700; border-radius: 4px;
    padding: 1px 4px; margin-left: 1px; line-height: 1.3;
  }
  .cbv-journal-scope-pip-fresh {
    color: var(--accent-emphasis); background: var(--accent-soft2);
  }
  .cbv-journal-scope-pip-depth1 {
    color: var(--k-lore-text); background: var(--k-lore-soft);
  }
</style>
