<script lang="ts">
  // The editor pane's footer rows (split out of NodeEditor, #2473): the foot
  // dock, the Line edit review bar, and the status line. A fragment — the three
  // roots stay direct children of NodeEditor's `.editor-panel` grid, so its
  // `> :global(*)` column pinning still reaches them.
  import FootDock from "@/components/editor/FootDock.svelte";
  import FlagReviewBar from "@/components/editor/body/FlagReviewBar.svelte";
  import LineEditReviewBar from "@/components/editor/body/LineEditReviewBar.svelte";
  import LineNoteReviewBar from "@/components/editor/body/LineNoteReviewBar.svelte";
  import type { AiSuggestionController } from "@/lib/editor-core/aiSuggestion.svelte";
  import type { SnapshotStripController } from "@/lib/stores/snapshotStrip.svelte";
  import type { LoreScrubController } from "@/lib/stores/loreScrub.svelte";
  import type { DocumentKind } from "@/lib/types";

  interface Props {
    snapshots: SnapshotStripController;
    scrub: LoreScrubController;
    documentKind: DocumentKind;
    // Whether the open document is a scene/lore entry with a prose body.
    dockVisible: boolean;
    snapshotWritesLabel: string | null;
    stopEditable: boolean;
    lineEditReview: AiSuggestionController | null;
    // The open document's title, or null when nothing is open.
    sceneTitle: string | null;
    dirty: boolean;
  }

  let {
    snapshots,
    scrub,
    documentKind,
    dockVisible,
    snapshotWritesLabel,
    stopEditable,
    lineEditReview,
    sceneTitle,
    dirty,
  }: Props = $props();
</script>

<!-- Foot-docked: the lore card's two time-axes share ONE dock (ADR-0088 S2).
     For a scene, or a lore entry with no mutations, FootDock degrades to
     exactly ADR-0044's snapshot strip with no mode control. Gated on a prose
     body: the read-only compare overlay is prose. -->
{#if dockVisible}
  <FootDock {snapshots} {scrub} {documentKind} writesLabel={snapshotWritesLabel} {stopEditable} />
{/if}

<!-- Line edit review (#2460): a pane footer row, NOT inside the prose scroll frame, so it never covers text.
     A lore check's notes (ADR-0098) take the same row; one review is open per editor. -->
{#if lineEditReview?.flags}
  <FlagReviewBar
    flags={lineEditReview.flags}
    view={lineEditReview.lineEditView}
    onView={(v) => lineEditReview?.setLineEditView(v)}
    onAcceptAllEdits={() => lineEditReview?.acceptAllFlagEdits()}
    onRejectAll={() => lineEditReview?.rejectAllFlags()}
  />
{:else if lineEditReview?.lineNotes}
  <LineNoteReviewBar
    lineNotes={lineEditReview.lineNotes}
    meta={lineEditReview.meta}
    generating={lineEditReview.generating}
    onDismissAll={() => lineEditReview?.dismissAllLineNotes()}
    onRetry={() => lineEditReview?.retry()}
  />
{:else if lineEditReview?.lineEdits}
  <LineEditReviewBar
    lineEdits={lineEditReview.lineEdits}
    view={lineEditReview.lineEditView}
    onView={(v) => lineEditReview?.setLineEditView(v)}
    meta={lineEditReview.meta}
    generating={lineEditReview.generating}
    onAcceptAll={() => lineEditReview?.acceptAllLineEdits()}
    onRejectAll={() => lineEditReview?.rejectAllLineEdits()}
    onRetry={() => lineEditReview?.retry()}
  />
{/if}

<footer class="status">
  {#if sceneTitle !== null}
    {dirty ? "Unsaved changes" : `Loaded ${sceneTitle}`}
  {:else}
    No scene open
  {/if}
</footer>
