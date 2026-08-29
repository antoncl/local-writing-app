<script lang="ts">
  // The per-row Library-shelf affordances (ADR-0049 §2), shared by every pane
  // that lists built-in Library nodes (Prompts, Plot templates). A shipped
  // Library entry is used in place, cloned to own, or hidden; a revealed hidden
  // row (under "Show N hidden") swaps clone+hide for a single un-hide. All three
  // key on `is_library` — the writer's own entries / owned clones have nothing to
  // clone or hide, so this renders nothing for them.
  //
  // Render this INSIDE a NodeRow's `trailing` snippet: the clone/hide buttons opt
  // into NodeRow's hover-reveal (`.reveal-on-hover`, styled by
  // `.node-row-trailing :global(button)`), and un-hide stays always-visible so a
  // dimmed row keeps its one way back. Extracted from the near-verbatim copies in
  // Prompts.svelte / PlotTemplates.svelte (#723) so the shelf affordance has one
  // home.

  import { hiddenLibraryStore, hideLibraryEntry, unhideLibraryEntry } from "@/lib/stores/hiddenLibrary";

  let {
    entry,
    // The kind noun for the clone tooltip ("prompt", "template", …) — the only
    // per-pane wording; hide/un-hide read the entry title, not the kind.
    noun,
    onClone,
  }: {
    entry: { id: string; title: string; is_library?: boolean };
    noun: string;
    onClone: (id: string) => void;
  } = $props();

  const hiddenSet = $derived($hiddenLibraryStore);
</script>

{#if entry.is_library}
  {#if hiddenSet.has(entry.id)}
    <button
      type="button"
      title={`Show “${entry.title}” on this project's Library shelf again`}
      aria-label={`Show ${entry.title} again`}
      onmousedown={(event) => event.stopPropagation()}
      onclick={(event) => {
        event.stopPropagation();
        unhideLibraryEntry(entry.id);
      }}
    ><i class="ti ti-eye-off" aria-hidden="true"></i></button>
  {:else}
    <button
      class="reveal-on-hover"
      type="button"
      title={`Clone this shipped ${noun} into an editable copy in this project`}
      aria-label={`Clone ${entry.title} into this project`}
      onmousedown={(event) => event.stopPropagation()}
      onclick={(event) => {
        event.stopPropagation();
        onClone(entry.id);
      }}
    >⧉</button>
    <button
      class="reveal-on-hover"
      type="button"
      title={`Hide “${entry.title}” from this project's Library shelf`}
      aria-label={`Hide ${entry.title} from this project`}
      onmousedown={(event) => event.stopPropagation()}
      onclick={(event) => {
        event.stopPropagation();
        hideLibraryEntry(entry.id);
      }}
    ><i class="ti ti-eye" aria-hidden="true"></i></button>
  {/if}
{/if}
