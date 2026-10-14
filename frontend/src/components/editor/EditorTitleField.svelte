<script lang="ts">
  // The title input in its seven states (split out of NodeEditor, #2473). Two
  // renderers use it: the non-chat header wraps it in the `.title-label`, the
  // chat body renders it bare (ADR-0076 S6). Each input carries its own
  // `aria-label`, so it needs no label wrapper. Persistence stays in NodeEditor:
  // this reports a typed title via `onInput` (it writes the bound `title`) and a
  // stop-edit commit via `onCommitStop`.
  import type { SnapshotStripController } from "@/lib/stores/snapshotStrip.svelte";

  interface Props {
    title: string;
    scrubbed: boolean;
    stopEditable: boolean;
    titleMutated: boolean;
    // The title as of the scrub point (the base title when not mutated there).
    effectiveTitle: string;
    snapshotParked: boolean;
    snapshots: SnapshotStripController;
    reviewing: boolean;
    inheritedReadOnly: boolean;
    bodyFrozen: boolean;
    documentLabel: string;
    documentNameLabel: string;
    onInput: () => void;
    onCommitStop: (draft: string) => void;
  }

  let {
    title = $bindable(),
    scrubbed,
    stopEditable,
    titleMutated,
    effectiveTitle,
    snapshotParked,
    snapshots,
    reviewing,
    inheritedReadOnly,
    bodyFrozen,
    documentLabel,
    documentNameLabel,
    onInput,
    onCommitStop,
  }: Props = $props();

  // ADR-0095 §8 decision 7: the input's own edit draft while scrubbed —
  // re-seeded from `effectiveTitle` on every stop change (a scrub step, or the
  // refresh after this stop's own save lands), never touched by a keystroke
  // elsewhere. `commitTitleStopEdit` is the blur/Enter gesture below.
  let titleStopDraft = $state("");
  $effect(() => {
    if (scrubbed) titleStopDraft = effectiveTitle;
  });
  function commitTitleStopEdit() {
    if (!scrubbed || titleStopDraft === effectiveTitle) return;
    onCommitStop(titleStopDraft);
  }
</script>

{#if scrubbed}
  {#if stopEditable}
    <!-- ADR-0095 §8 decision 7: a title edit AT A STOP saves this stop's
         mutation set (a `replace` row, removed when it lands back on the
         base title) — never `emitChange`/`handleTitleInput`, which write
         the base. Commits on blur/Enter, Esc reverts, the same gesture the
         rail's inline scalar inputs use (RailScalarCell's `.fr-edit`
         Escape/focusout handling) — this is a bespoke input (the shell's
         own title header/chat-row field, not a rail row), so the gesture is
         reimplemented here rather than shared. -->
    <input
      class="title-input"
      class:mutated={titleMutated}
      aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()} (editing this stop)`}
      bind:value={titleStopDraft}
      onkeydown={(e) => {
        if (e.key === "Enter") (e.currentTarget as HTMLInputElement).blur();
        else if (e.key === "Escape") {
          titleStopDraft = effectiveTitle;
          (e.currentTarget as HTMLInputElement).blur();
        }
      }}
      onblur={commitTitleStopEdit}
    />
  {:else}
    <!-- Effective title as of the scrub point — read-only (parked/
         reviewing/inherited wins over the scrub axis). -->
    <input class="title-input" class:mutated={titleMutated} readonly aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()} (effective, read-only)`} value={effectiveTitle} />
  {/if}
{:else if snapshotParked}
  <!-- Parked: the title flips with the body and the rail, and is
       read-only like them. Leaving it editable let an author type
       into a document they were not looking at. -->
  <input
    class="title-input"
    class:flipped={snapshots.titleDiffers}
    class:flip-was={snapshots.titleDiffers && snapshots.view === "was"}
    readonly
    aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()} (snapshot, read-only)`}
    value={snapshots.titleForView}
  />
{:else if reviewing}
  <!-- Frozen for AI review (#634): read-only like the parked/scrubbed
       title, so the author can't edit an entry mid-review — the review
       is a transaction that writes once, not a co-editing surface. -->
  <input class="title-input" readonly aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()} (under review, read-only)`} value={title} />
{:else if inheritedReadOnly}
  <!-- Inherited prompt (ADR-0049 Library or an ancestor project, #676):
       read-only in place. The title cannot be renamed here; clone it
       to edit. -->
  <input class="title-input" readonly aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()} (inherited, read-only)`} value={title} />
{:else if bodyFrozen}
  <!-- A written card shows its scene's title (ADR-0097 §3); rename it on the board
       or in the scene. -->
  <input class="title-input" readonly aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()} (written as a scene, read-only)`} value={title} />
{:else}
  <input class="title-input" aria-label={`${documentLabel} ${documentNameLabel.toLowerCase()}`} placeholder={documentNameLabel} bind:value={title} oninput={onInput} />
{/if}

<style>
  .title-input[readonly] {
    background: var(--inset);
    cursor: default;
  }
  /* The same two colours as the body and the rail — one vocabulary, and never a
     glyph (§J). Two rules rather than one with a variable, so a state class
     cannot silently outrank an identity class for a single property. */
  .title-input.flipped {
    color: var(--diff-now);
    font-weight: 600;
    box-shadow: inset 0 -2px 0 var(--diff-now-edge);
  }
  /* Dotted, matching the body and the rail — the greyscale channel is shape. */
  .title-input.flipped.flip-was {
    color: var(--diff-was);
    box-shadow: none;
    background-image: repeating-linear-gradient(
      to right,
      var(--diff-was-edge) 0 3px,
      transparent 3px 6px
    );
    background-repeat: no-repeat;
    background-position: 0 100%;
    background-size: 100% 2px;
  }
  .title-input.mutated {
    color: var(--mutation-color);
    font-weight: 600;
  }

  .title-input {
    border: 0;
    border-bottom: 1px solid var(--divider);
    border-radius: 0;
    font-family: var(--serif);
    font-size: var(--fs-2xl);
    font-weight: 700;
    padding-left: 0;
  }

  .title-input:focus {
    border-bottom-color: var(--accent);
    outline: none;
  }
</style>
