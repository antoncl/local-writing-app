// The entry-proposal review wiring (ADR-0046 slice 2/3), split out of NodeEditor
// (#2473). NodeEditor owns the shell state the review reads and writes (title,
// status, metadata, the body views), so the host hands this a getter/setter bag —
// the RailUndoController / wireReviewFreeze precedent — and gets the one
// controller back. Must be called during the host's initialization: it registers
// effects, and their order is creation order (the feed `$effect.pre` first).
import { todoActions } from "@/lib/stores/todoActions.svelte";
import { EntryProposalController, bodyAdopter } from "@/lib/stores/entryProposal.svelte";
import { refreshTagNodes, resolveAdoptedTagFields } from "@/lib/stores/tagNodes";
import { wireReviewFreeze, type ReviewFreezeSignal } from "@/lib/editor-core/reviewFreeze.svelte";
import type { EditableDocument, EntryMetadata, MetadataSchema } from "@/lib/types";

export interface EntryReviewHost {
  scene: () => EditableDocument | null;
  metadataSchema: () => MetadataSchema | null | undefined;
  bodyFrozen: () => boolean;
  // The shell-owned fields a patch can flip (title/status ride off `metadata`).
  title: () => string;
  setTitle: (next: string) => void;
  status: () => string;
  setStatus: (next: string) => void;
  metadata: () => EntryMetadata;
  setMetadata: (next: EntryMetadata) => void;
  // The layer an adopted tag-vocabulary flip mints at (`createLayerId`).
  createLayerId: () => string | null | undefined;
  // Body adopt/read route to the ACTIVE body view (raw editor vs TipTap).
  rawBodyMode: () => boolean;
  rawBody: () => string;
  setRawBody: (body: string) => void;
  proseView: () => { adoptBody(body: string): Promise<void> } | null | undefined;
  readLiveBody: () => string | undefined;
  emitChange: () => void;
  flushReviewCommit: () => ((entryId: string) => Promise<boolean>) | undefined;
  reviewFreezeSignal: () => ReviewFreezeSignal | undefined;
}

export function wireEntryReview(host: EntryReviewHost): EntryProposalController {
  const entryReview = new EntryProposalController();
  $effect.pre(() => {
    entryReview.nodeId = host.scene()?.id ?? null;
    entryReview.schema = host.metadataSchema() ?? null;
    // `title`/`status` live off `metadata` in their own shell state, but a patch
    // can flip them (a rename / a status change), so fold them into the metadata
    // view the controller diffs against — else their flip's "current" side reads
    // as unset. Adoption routes them back out (onAdoptFields below).
    entryReview.metadata = { ...host.metadata(), title: host.title(), status: host.status() };
    entryReview.bodyFrozen = host.bodyFrozen();
  });
  entryReview.onAdoptFields = async (fields) => {
    // `title`/`status` are proposable but stored off `metadata` (saved via the
    // top-level payload fields, and the backend applies a rename on post), so
    // route an adopted flip to the matching shell state and keep it out of the
    // metadata merge — else the merge would set a phantom key the save ignores.
    // emitChange (below) packages title + status + metadata into the one PUT.
    const next = { ...fields };
    if ("title" in next) {
      host.setTitle(String(next.title ?? ""));
      delete next.title;
    }
    if ("status" in next) {
      host.setStatus(String(next.status ?? ""));
      delete next.status;
    }
    // ADR-0082 §2 / #1797: an ADOPTED tag-vocabulary flip may still carry
    // unresolved titles (the validator never mints — see entryProposal's
    // module note). Resolve/mint them now, only because the author accepted
    // this field — the same `createLayerId` the metadata panel's own picker
    // threads for its "Create ‹x›" (P5), so an AI-accepted tag lands at the
    // identical layer a hand-typed one would. A rejection here is left to
    // propagate — deliberately not caught: `EntryProposalController.commit()`
    // (round 2, Y1) is what turns it into `commitError` + an aborted commit
    // that keeps the review open, so there's nothing to handle at this layer.
    // Shared with treeActions' create-from-draft accept moment (#1821) —
    // see `resolveAdoptedTagFields`'s doc comment.
    await resolveAdoptedTagFields(next, host.metadataSchema(), host.createLayerId() ?? null);
    host.setMetadata({ ...host.metadata(), ...next });
  };
  // Body adopt/read route to the ACTIVE body view: the raw editor for a code body
  // (a prompt template — #711), TipTap otherwise. Both sides are plain strings, so
  // the run-diff review reads a template exactly as it reads prose. `rawBody` feeds
  // the save the same way a keystroke does (the rawBodyMode effect → emitChange).
  entryReview.onAdoptBody = bodyAdopter({
    rawBodyMode: host.rawBodyMode,
    setRawBody: host.setRawBody,
    proseView: host.proseView,
  });
  entryReview.onEmitChange = host.emitChange;
  entryReview.readCurrentBody = () =>
    host.rawBodyMode() ? host.rawBody() : (host.readLiveBody() ?? host.scene()?.body ?? "");
  // The one explicit post that ends a commit — the pane controller cancels the
  // (frozen) timer and PUTs once (body + metadata together).
  entryReview.onFlush = () => {
    const id = host.scene()?.id;
    if (id) return host.flushReviewCommit()?.(id);
  };
  // ADR-0090 §4: mark a review item done once its Propose-launched patch adopts.
  // The write goes through the todo controller like every other todo write;
  // its `run` surfaces a failure without undoing the adopt.
  entryReview.onReviewItemAdopted = (reviewItemId) => todoActions.markReviewItemDone(reviewItemId);

  // The hooks the pane's close path uses to commit or discard the review.
  const reviewCommitter = {
    hasChanges: () => entryReview.hasPendingChanges,
    commit: () => entryReview.commit(),
    discard: () => entryReview.abandon(),
  };
  // Freeze while reviewing, thaw (null) the instant the review ends or the pane
  // unmounts. Fires only on a genuine transition (entry id / `reviewing`) — never on
  // App recreating the inline `onReviewFreeze` arrow each render, which used to
  // thrash begin/endReviewLock into an unbounded flush loop (#1965). The wiring lives
  // in editor-core so the reactivity contract is unit-testable off the mega-component.
  wireReviewFreeze({
    entryId: () => host.scene()?.id ?? null,
    reviewing: () => entryReview.hasReview,
    committer: () => reviewCommitter,
    signal: host.reviewFreezeSignal,
  });
  // Reset accumulated review resolution whenever the proposal identity changes,
  // so a superseding commit starts clean instead of inheriting prior adoptions.
  $effect(() => {
    entryReview.proposal;
    entryReview.resetResolution();
  });
  // A patch touching a tag-vocabulary field (#1797/#1799) may name a tag that
  // was created elsewhere since this pane last refreshed its roster — pull it
  // so a title the backend DID resolve to a real id (`tagTitleById` just
  // stale) renders as that tag's title, not a false "new tag" candidate
  // (`MetadataPanel`'s flip-chip strip tells the two apart by roster
  // membership alone). Never mints anything itself — only ACCEPT does that.
  $effect(() => {
    if (entryReview.proposesTagField) refreshTagNodes();
  });
  return entryReview;
}
