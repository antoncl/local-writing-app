<script lang="ts">
  // The entry-patch brainstorm launcher (ADR-0046 slice 2; the loop generalized
  // to any schema-typed node, ADR-0048 §5). Extracted from NodeEditor so the
  // shell stays under the size guard and the launch concern is one cohesive unit.
  // Renders a quiet header verb that opens the first available `revise:entry`
  // prompt (output.kind `entry_patch`) as a chat bound to this node — seeded as
  // its `entry` input, which the template loads via entry(input.entry). Hidden
  // when no such prompt instance exists yet (issue #606 — pre-rolled prompts
  // still need a materialized instance). The component is kind-neutral; the host
  // (NodeEditor) decides which kinds render it (currently lore — no plot yet).
  //
  // A temporary home: ADR-0047's node contextual-actions are the eventual
  // surface, but that is unbuilt, so this follows roleplay's invocation shape.

  import { chatSessions } from "@/lib/stores/chatSessions.svelte";
  import { hiddenLibraryStore } from "@/lib/stores/hiddenLibrary";
  import {
    promptEntriesForSurface,
    type PromptResolutionContext,
  } from "@/lib/editor-core/promptResolution";
  import type { MetadataSchema, PromptEntrySummary } from "@/lib/types";

  let {
    entryId,
    entryTitle = "",
    promptEntries,
    metadataSchema,
    hostPaneId = null,
  }: {
    entryId: string;
    // The host node's display title — names the launched chat "<entry> — <prompt>"
    // so brainstorming two entries with the same prompt doesn't yield two
    // identically-titled chats (ADR-0051 S2).
    entryTitle?: string;
    promptEntries: PromptEntrySummary[];
    metadataSchema: MetadataSchema | null;
    // The editor pane hosting this bar. The launched chat registers as its
    // subordinate so it auto-closes when this entry's pane closes.
    hostPaneId?: string | null;
  } = $props();

  let ctx = $derived<PromptResolutionContext>({
    metadataSchema,
    promptEntries,
    loreEntries: [],
    availableScenes: [],
    hiddenPromptIds: $hiddenLibraryStore,
  });
  let brainstormPrompts = $derived(promptEntriesForSurface(ctx, "entry_patch"));

  async function launch(): Promise<void> {
    const prompt = brainstormPrompts[0];
    if (!prompt || !entryId) return;
    // This entry IS the subject the brainstorm is about (ADR-0051 S2): stamp it
    // so the chat surfaces in "chats about this entry" and is named after it.
    await chatSessions.openChatFromPromptEntry(prompt, { entry: entryId }, null, {
      parentPaneId: hostPaneId,
      subject: entryId,
      subjectTitle: entryTitle,
    });
  }
</script>

{#if brainstormPrompts.length > 0}
  <button
    type="button"
    class="brainstorm-launch"
    title="Brainstorm a revision with AI, then review it against this entry"
    onclick={() => void launch()}
  >
    Brainstorm
  </button>
{/if}

<style>
  /* A quiet header verb next to the title (design language — a text button, no
     glyph). */
  .brainstorm-launch {
    justify-self: end;
    font: inherit;
    font-size: var(--fs-sm);
    padding: 3px 12px;
    border-radius: var(--r-sm);
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text-2);
    cursor: pointer;
    white-space: nowrap;
  }
  .brainstorm-launch:hover {
    color: var(--text);
    border-color: var(--accent);
  }
</style>
