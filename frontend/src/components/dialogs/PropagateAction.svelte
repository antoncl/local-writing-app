<script lang="ts">
  // The "Propagate…" doc action (ADR-0090 §1/§7) on a lore entry — extracted
  // from App.svelte's editorDocActions snippet (the file-size guard), the
  // exact shape of PromoteAction.svelte: App only supplies the open pane's
  // document kind + entry; the actual work (building the candidate set,
  // showing the confirm surface) lives behind `openPropagatePane`, which
  // opens the on-demand `propagate` region.
  import { openPropagatePane } from "@/lib/stores/paneOpeners";
  import type { EditableDocument } from "@/lib/types";

  let {
    documentKind,
    entry,
  }: {
    // The open pane's document kind — the action only offers on "lore".
    documentKind: string | undefined;
    // The open pane's document, typed as the general union (what a pane
    // carries); the kind check above is what narrows it in practice.
    entry: EditableDocument | null | undefined;
  } = $props();

  let showAction = $derived(documentKind === "lore" && !!entry);

  function openPropagate(): void {
    if (!entry || documentKind !== "lore") return;
    openPropagatePane(entry.id, entry.title);
  }
</script>

{#if showAction}
  <button
    class="pin-button"
    type="button"
    title="Propagate this entry's change to its dependents"
    aria-label="Propagate this entry's change to its dependents"
    onmousedown={(event) => event.stopPropagation()}
    onclick={openPropagate}
  >
    Propagate…
  </button>
{/if}
