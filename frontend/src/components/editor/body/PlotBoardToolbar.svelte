<script lang="ts">
  import type { PlotDiagnosticSummary } from "./plotBoardDiagnostics";

  interface Props {
    cardCount: number;
    claimCount: number;
    diagnostics: PlotDiagnosticSummary;
    relationshipCount: number;
    savingMessage: string;
    saveError: string;
    addCard: () => void;
    addAct: () => void;
    addChapter: () => void;
  }

  let {
    cardCount,
    claimCount,
    diagnostics,
    relationshipCount,
    savingMessage,
    saveError,
    addCard,
    addAct,
    addChapter,
  }: Props = $props();
</script>

<div class="board-toolbar">
  <span>{cardCount} cards</span>
  <span>{claimCount} badges</span>
  {#if diagnostics.total > 0}
    <span class="diagnostic-count">{diagnostics.total} checks</span>
  {/if}
  <span>{relationshipCount} relationships</span>
  {#if savingMessage}
    <span>{savingMessage}...</span>
  {/if}
  {#if saveError}
    <span class="toolbar-error">{saveError}</span>
  {/if}
  <button type="button" class="tool-button" disabled={Boolean(savingMessage)} onclick={addCard}>
    <i class="ti ti-note" aria-hidden="true"></i>
    Card
  </button>
  <button type="button" class="tool-button" disabled={Boolean(savingMessage)} onclick={addAct}>
    <i class="ti ti-columns-3" aria-hidden="true"></i>
    Act
  </button>
  <button type="button" class="tool-button" disabled={Boolean(savingMessage)} onclick={addChapter}>
    <i class="ti ti-library-plus" aria-hidden="true"></i>
    Chapter
  </button>
</div>
