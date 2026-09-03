<script lang="ts">
  // The brainstorm-commit review overlay, extracted from NodeEditor (#1261). The
  // live body stays mounted and hidden beneath (the host does that); adopting
  // writes through the same emitChange autosave (body + metadata in one PUT).
  // Shared by the prose AND code body branches (#711) — the run-diff reads a
  // prompt's template exactly as it reads prose. Two presentations, chosen by the
  // launching prompt's `commit.review` carried on the proposal (ADR-0054 §2).
  //
  // One prop: the whole controller. Every field/callback hangs off it, so the
  // overlay is a pure view of the review state — no shell coupling.
  import EntryRevisionReview from "@/components/editor/body/EntryRevisionReview.svelte";
  import ReplaceReviewCard from "@/components/editor/body/ReplaceReviewCard.svelte";
  import type { EntryProposalController } from "@/lib/stores/entryProposal.svelte";

  let { review }: { review: EntryProposalController } = $props();
</script>

{#if review.commitError}
  <!-- #1797 round 2 (Y1): an accept-time step (a tag-vocabulary flip's
       title→id resolve/mint) can fail partway through — `commit()` aborts,
       keeps the review open with the flip still pending, and records the
       message here. Shown above either review presentation so the author
       sees why nothing saved and can just retry. -->
  <p class="entry-review-error">{review.commitError}</p>
{/if}
{#key review.proposal}
  {#if review.proposal?.reviewMode === "replace"}
    <!-- `replace`: a whole-field swap (a scene summary regenerated from the
         body) — a plain current→proposed card, no run-diff (a regenerated value
         has no meaningful per-run diff). Replace adopts ONLY the shown long_text
         fields via `acceptFields` — never the body or a structured flip — so the
         write set equals what the card displays and a scene's prose can't be
         rewritten. -->
    <ReplaceReviewCard
      fields={review.fields}
      onReplace={() => {
        review.acceptFields();
        void review.commit();
      }}
      onDiscard={() => review.abandon()}
    />
  {:else}
    <!-- ADR-0046 slice 3: the per-run adopt flip (body + each long_text field),
         plus the structured rail flips and the A/S/B judge axis. -->
    <EntryRevisionReview
      currentBody={review.currentBody()}
      proposedBody={review.proposal?.body ?? null}
      fields={review.fields}
      hasChanges={review.hasPendingChanges}
      view={review.view}
      onView={(v) => review.setView(v)}
      onToggleView={(v) => review.toggleView(v)}
      onBodyResolved={(v) => review.setBodyResolution(v)}
      onFieldResolved={(id, v) => review.setFieldResolution(id, v)}
      onAcceptAll={() => {
        review.acceptAll();
        void review.commit();
      }}
      onDone={() => review.commit()}
      onDiscard={() => review.abandon()}
    />
  {/if}
{/key}

<style>
  .entry-review-error {
    margin: 0 0 8px;
    font-size: var(--fs-sm);
    color: var(--danger);
  }
</style>
