// The chat-pane end of the entry-patch brainstorm loop (ADR-0046 slice 2/3;
// generalized to any schema-typed node, ADR-0048 §5 / ADR-0051 S5-next; the
// commit is a fresh extraction, ADR-0051 S4), as a per-instance rune controller
// — the shape `EntryProposalController` uses, and ChatBodyView composes.
//
// A `revise:entry` brainstorm is a conversation; the *commit* asks for the final
// structured state. This controller owns that commit-and-hand-off orchestration:
// it posts the transcript to the fresh-extraction endpoint (which rebuilds the
// format contract server-side and runs it as its own pass — S4, replacing the old
// client-side finalize replay), and either publishes the returned `EntryPatch` to
// the cross-pane `entryBrainstorm` store for review on the entry's pane, or holds
// a from-scratch draft for the create card. The *entry* pane's
// `EntryProposalController` is the other half; `entryBrainstorm` bridges them.
//
// It is kind-agnostic: it keys off the fed `output` (which prompt surface is
// bound) and `inputDrafts` (which entry / entry_type the launch seeded), never a
// node `kind`. Which kinds may launch a brainstorm is the host's policy.
//
// The controller owns only the commit machinery + its own review state
// (`committing`, the pending `draftProposal`). ChatBodyView keeps the chat
// session, cost accounting (`pendingTurnCost`), and the status lines — the
// controller reaches those through the wired `deps`, so `persistActiveChat` and
// `chatError`/`chatNotice` stay component-owned.
import type {
  AIEntryPatch,
  ChatMessage,
  EntryPatch,
  EntryPatchExtraction,
  MetadataValue,
  ReviewMode,
} from "@/lib/types";
import { api } from "@/lib/api";
import { entryBrainstorm } from "@/lib/stores/entryBrainstorm.svelte";
import { treeActions } from "@/lib/stores/treeActions.svelte";

/** The live chat state + status/cost sinks the controller reaches into. Stable
 *  for the controller's life (wired once at construction) — the reactive inputs
 *  the derivations track are the fed `$state` below, not these. */
export interface ChatCommitDeps {
  /** Assistant bound to the chat, or "" for the machine default. */
  getAssistantId: () => string;
  /** The visible transcript, mapped to the extraction request's message shape —
   *  the extraction reads it as pure input (ADR-0051 S4). */
  getHistory: () => Pick<ChatMessage, "role" | "content">[];
  /** Attribute the (always-billed) extraction turn's cost to the session and
   *  persist — the host owns `pendingTurnCost`, so the delta rides its next save. */
  addTurnCost: (usd: number) => Promise<void>;
  /** Set / clear the chat error line (component-owned). */
  setError: (message: string | null) => void;
  /** Set / clear the non-error commit notice (component-owned). */
  setNotice: (message: string | null) => void;
  /** Title of the entry a patch was committed to, for the hand-off cue — null
   *  when it isn't in the caller's roster (e.g. a scene subject). */
  entryTitle: (entryId: string) => string | null;
}

export class ChatCommitController {
  // ---- fed each render by the host (the derivations below track these) -------
  /** The active prompt's `output` config: `.kind` is the surface (`entry_patch`
   *  chats commit to their `entry` target), `.review` how it's reviewed. */
  output = $state<Record<string, MetadataValue> | null>(null);
  /** The chat's per-input drafts — `entry` (revise target) / `entry_type`
   *  (create target) are seeded here at launch (ADR-0046 §6.4). */
  inputDrafts = $state<Record<string, string>>({});
  /** Whether a chat turn is streaming — a commit must not race it. */
  running = $state(false);

  // ---- commit / draft review state (owned here) ------------------------------
  committing = $state(false);
  // ADR-0046 §6.4 create mode: a from-scratch brainstorm has no entry to flip
  // against, so its commit is held here as a whole proposed draft and reviewed in
  // a card (Create / Discard) rather than routed to an entry pane. `null` when
  // there is no pending draft.
  draftProposal = $state<EntryPatch | null>(null);
  draftDropped = $state<string[]>([]);
  creatingDraft = $state(false);

  constructor(private readonly deps: ChatCommitDeps) {}

  /** An `entry_patch`-surfaced chat commits to a schema-typed node. */
  isEntryPatchChat = $derived(this.output?.kind === "entry_patch");
  /** The revise target — the `entry` input the launch seeded (empty in create
   *  mode). */
  commitTargetEntryId = $derived((this.inputDrafts["entry"] ?? "").trim());
  // ADR-0046 §6.4: the target entry_type for a create-mode brainstorm (no entry
  // seeded). Mutually exclusive with commitTargetEntryId by how the chat was
  // launched — revise seeds `entry`, create seeds `entry_type`.
  draftEntryType = $derived((this.inputDrafts["entry_type"] ?? "").trim());
  isCreateBrainstorm = $derived(
    this.isEntryPatchChat && !this.commitTargetEntryId && !!this.draftEntryType,
  );
  /** The prompt's `output.extract` override, sent to the extraction endpoint so
   *  the server renders it in place of the default generated contract (ADR-0051
   *  S4). Null → the default (body + all proposable fields). */
  extractTemplate = $derived(
    typeof this.output?.extract === "string" ? this.output.extract : null,
  );

  // The commit preamble both modes share: run the extraction, attribute the
  // (always-billed) turn's cost like a streamed one, and surface the two failure
  // shapes — the turn returned nothing (ok=false / no patch), or the reply
  // couldn't be read as a patch (garbled). Returns the validated patch, or null
  // when the caller should stop (a message was already set). This is the seam the
  // deleted `runFinalizeTurn` held, so the two modes can't drift on cost/failure
  // handling. The per-mode tail (propose vs hold a draft) stays in each method.
  private async runExtraction(
    extract: () => Promise<EntryPatchExtraction>,
    garbledMessage: string,
  ): Promise<AIEntryPatch | null> {
    const result = await extract();
    if (typeof result.cost_usd === "number") await this.deps.addTurnCost(result.cost_usd);
    if (!result.ok || !result.patch) {
      this.deps.setError(result.error || "The model returned nothing to commit.");
      return null;
    }
    if (result.patch.garbled) {
      this.deps.setError(garbledMessage);
      return null;
    }
    return result.patch;
  }

  // Commit the brainstorm to its target entry (ADR-0046 slice 3 / ADR-0051 S4).
  // The extraction runs a fresh, server-rebuilt contract over the transcript and
  // returns a validated EntryPatch, handed to the entry's pane for the
  // proposed-vs-current review; nothing is written from here. A patch that
  // proposes nothing is surfaced, never a silent no-op.
  async commitToEntry(): Promise<void> {
    if (this.running || this.committing || !this.isEntryPatchChat) return;
    const entryId = this.commitTargetEntryId;
    if (!entryId) {
      this.deps.setError("This brainstorm has no target entry to commit to.");
      return;
    }
    this.deps.setError(null);
    this.deps.setNotice(null);
    this.committing = true;
    try {
      const patch = await this.runExtraction(
        () =>
          api.extractEntryPatch(entryId, {
            messages: this.deps.getHistory(),
            assistant_id: this.deps.getAssistantId() || null,
            extract_template: this.extractTemplate,
          }),
        "Couldn't read the model's response as a patch — ask it to finalize again.",
      );
      if (!patch) return;
      // `replace` (a scene summary) swaps one field whole; strip any body the
      // model returned so the stored proposal stays fields-only (the commit-side
      // guarantee that prose is never rewritten lives in `acceptFields`).
      const reviewMode: ReviewMode = this.output?.review === "replace" ? "replace" : "visual_diff";
      const body = reviewMode === "replace" ? null : patch.body;
      const hasBody = body != null;
      const hasFields = Object.keys(patch.fields).length > 0;
      if (!hasBody && !hasFields) {
        this.deps.setNotice("The model proposed no changes to commit.");
        return;
      }
      entryBrainstorm.propose(entryId, { body, fields: patch.fields, reviewMode });
      // Hand-off cue (#710 slice 3): the commit lands here in the chat pane but
      // the review renders on the entry pane. Name where it went so the author
      // knows to flip over. A scene subject isn't in the caller's roster → "the scene".
      const reviewOn = this.deps.entryTitle(entryId) ?? "the scene";
      const dropped =
        patch.dropped.length > 0
          ? ` Ignored ${patch.dropped.length} field(s) the model couldn't set legally: ${patch.dropped.join(", ")}.`
          : "";
      this.deps.setNotice(`Committed — review it on ${reviewOn}.${dropped}`);
    } catch (e) {
      this.deps.setError((e as Error).message);
    } finally {
      this.committing = false;
    }
  }

  // Create mode (ADR-0046 §6.4 / ADR-0051 S4): a fresh extraction against the
  // target entry_type (no entry read), held as a whole draft for the review card.
  // Nothing is written until the author clicks Create.
  async commitDraft(): Promise<void> {
    if (this.running || this.committing || !this.isCreateBrainstorm) return;
    const entryType = this.draftEntryType;
    this.deps.setError(null);
    this.deps.setNotice(null);
    this.committing = true;
    try {
      const patch = await this.runExtraction(
        () =>
          api.extractEntryDraft(entryType, {
            messages: this.deps.getHistory(),
            assistant_id: this.deps.getAssistantId() || null,
            extract_template: this.extractTemplate,
          }),
        "Couldn't read the model's response as an entry — ask it to finalize again.",
      );
      if (!patch) return;
      const hasBody = patch.body != null;
      const hasFields = Object.keys(patch.fields).length > 0;
      if (!hasBody && !hasFields) {
        this.deps.setNotice("The model proposed no entry to create.");
        return;
      }
      this.draftDropped = patch.dropped;
      this.draftProposal = { body: patch.body, fields: patch.fields };
    } catch (e) {
      this.deps.setError((e as Error).message);
    } finally {
      this.committing = false;
    }
  }

  async createDraft(): Promise<void> {
    if (!this.draftProposal || this.creatingDraft) return;
    this.creatingDraft = true;
    try {
      // Only clear the reviewed draft if the create actually succeeded — run()
      // reports failure as `false` (it swallows the error), so clearing
      // unconditionally would silently lose the draft on a 409 / offline / save
      // rejection with nothing created.
      const ok = await treeActions.createLoreEntryFromDraft(this.draftEntryType, this.draftProposal);
      if (ok) this.reset();
    } catch (e) {
      this.deps.setError((e as Error).message);
    } finally {
      this.creatingDraft = false;
    }
  }

  // ADR-0046 §6.4: the create-mode draft is component-local (not routed to an
  // entry pane), so it must be cleared whenever the chat state resets — else a
  // pending card leaks across a chat-session switch and Create would run against
  // the new chat's entry_type.
  reset(): void {
    this.draftProposal = null;
    this.draftDropped = [];
    this.creatingDraft = false;
  }
}
