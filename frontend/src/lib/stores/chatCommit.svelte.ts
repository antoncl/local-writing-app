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
  MutationSetEntry,
  MutationSetRow,
  PromptOutput,
  ReviewMode,
} from "@/lib/types";
import { api, HttpError } from "@/lib/api";
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
  /** The id of the set the chat already owns (its `staged_set` edge), or "" —
   *  read at stage time so a re-stage refines the SAME set in place rather than
   *  minting an orphan (the edge is singular, ADR-0055 §4). */
  getStagedSetId: () => string;
  /** Persist a newly-staged pinned set's id onto the chat's `staged_set` edge
   *  (ADR-0055 §4). The host owns the chat session + persist, so the write-back
   *  rides its save path — the controller never touches the chat node. Only
   *  called when the chat didn't already own the set (a first stage). */
  onStaged: (setId: string) => Promise<void>;
  /** Stamp the entry a create-mode brainstorm just minted as the chat's
   *  `subject` (ADR-0051 S2) and persist — the chat was launched before its
   *  entry existed, so the association can only be written here, at create time;
   *  without it the new entry's Conversations surface never lists the chat that
   *  drafted it (#983). Same host-owned write-back shape as onStaged. */
  onCreated: (entryId: string) => Promise<void>;
}

// ADR-0055 §2/§4a: a staged mutation set carries the same content as an entry
// commit, re-expressed as rows. The extracted patch's field values are already
// validated against the subject's type (the commit endpoint runs
// `validate_ai_entry_patch_for_type`, dropping anything illegal), and every row
// is `op: "replace"` — always op-legal for any field, title, or body
// (`lore_mutations` gates only add/remove) — so a staged set can never carry a
// field/op a placed marker would reject. This is the §2 "validate AI rows at
// stage time" guarantee, met by reusing the commit's own validator rather than
// re-running the marker validator. A value is serialized exactly as the set
// editor's `toMarkerString` does — null → "" (not the literal "null"), and a
// collection comma-joined (mirroring the marker's whole-collection `replace` /
// `_split_collection_value`) — so a staged row and a hand-authored one match.
export function patchToRows(patch: EntryPatch): MutationSetRow[] {
  const rows: MutationSetRow[] = [];
  if (patch.body != null) rows.push({ field: "body", op: "replace", value: patch.body });
  for (const [field, value] of Object.entries(patch.fields)) {
    const str =
      value == null ? "" : Array.isArray(value) ? value.map(String).join(",") : String(value);
    rows.push({ field, op: "replace", value: str });
  }
  return rows;
}

export class ChatCommitController {
  // ---- fed each render by the host (the derivations below track these) -------
  /** The active prompt's `output` config (ADR-0054): `.kind` is the disposition;
   *  a `.commit` marks a brainstorm whose result is extracted to its `entry`
   *  target (`.commit.review` = how it's reviewed, `.commit.fields` = what it
   *  extracts). */
  output = $state<PromptOutput | null>(null);
  /** The chat's per-input drafts — `entry` (revise target) / `entry_type`
   *  (create target) are seeded here at launch (ADR-0046 §6.4). */
  inputDrafts = $state<Record<string, string>>({});
  /** Whether a chat turn is streaming — a commit must not race it. */
  running = $state(false);
  /** The subject's `entry_type` when it is a time-travel-aware lore entity, else
   *  "" — fed by the host from the lore roster (ADR-0055 §2). It gates staging:
   *  only a lore subject carries a timeline, so only a lore commit may stage a
   *  mutation set (§4a/§6). A scene or plot-card subject leaves this "" and sees
   *  the canonical commit path alone. */
  subjectEntryType = $state<string>("");

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

  /** A chat carrying a `commit` (ADR-0054 §2) extracts its result to a
   *  schema-typed node — the routing question that was `output.kind ===
   *  "entry_patch"`. */
  isCommitChat = $derived(!!this.output?.commit);
  /** The revise target — the `entry` input the launch seeded (empty in create
   *  mode). */
  commitTargetEntryId = $derived((this.inputDrafts["entry"] ?? "").trim());
  // ADR-0046 §6.4: the target entry_type for a create-mode brainstorm (no entry
  // seeded). Mutually exclusive with commitTargetEntryId by how the chat was
  // launched — revise seeds `entry`, create seeds `entry_type`.
  draftEntryType = $derived((this.inputDrafts["entry_type"] ?? "").trim());
  isCreateBrainstorm = $derived(
    this.isCommitChat && !this.commitTargetEntryId && !!this.draftEntryType,
  );
  /** The prompt's `commit.fields` allow-list (ADR-0054 §2), sent to the extraction
   *  endpoint so the server narrows the generated contract to those targets. Null
   *  → the default (body + all proposable fields). */
  commitFields = $derived(this.output?.commit?.fields ?? null);

  /** ADR-0055 §4a/§6: a committing brainstorm on a time-travel-aware lore subject
   *  may stage its result as a subject-pinned mutation set (the timeline branch)
   *  instead of writing the entry's base (the canonical branch). Offered only
   *  when there is a revise target that is a lore entity. */
  canStage = $derived(
    this.isCommitChat && !!this.commitTargetEntryId && !!this.subjectEntryType,
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

  // The one extraction call `commitToEntry` and `stageToPendingSet` share (same
  // transcript, assistant, and commit.fields allow-list) — kept in one place so
  // the two destinations can never drift on what's posted. The garbled message
  // is per-caller (an entry "patch" vs a staged "change").
  private extractPatch(entryId: string, garbledMessage: string): Promise<AIEntryPatch | null> {
    return this.runExtraction(
      () =>
        api.extractEntryPatch(entryId, {
          messages: this.deps.getHistory(),
          assistant_id: this.deps.getAssistantId() || null,
          commit_fields: this.commitFields,
        }),
      garbledMessage,
    );
  }

  // Commit the brainstorm to its target entry (ADR-0046 slice 3 / ADR-0051 S4).
  // The extraction runs a fresh, server-rebuilt contract over the transcript and
  // returns a validated EntryPatch, handed to the entry's pane for the
  // proposed-vs-current review; nothing is written from here. A patch that
  // proposes nothing is surfaced, never a silent no-op.
  async commitToEntry(): Promise<void> {
    if (this.running || this.committing || !this.isCommitChat) return;
    const entryId = this.commitTargetEntryId;
    if (!entryId) {
      this.deps.setError("This brainstorm has no target entry to commit to.");
      return;
    }
    this.deps.setError(null);
    this.deps.setNotice(null);
    this.committing = true;
    try {
      const patch = await this.extractPatch(
        entryId,
        "Couldn't read the model's response as a patch — ask it to finalize again.",
      );
      if (!patch) return;
      // `replace` (a scene summary) swaps one field whole; strip any body the
      // model returned so the stored proposal stays fields-only (the commit-side
      // guarantee that prose is never rewritten lives in `acceptFields`).
      const reviewMode: ReviewMode =
        this.output?.commit?.review === "replace" ? "replace" : "visual_diff";
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

  // Stage the brainstorm as a subject-pinned mutation set (ADR-0055 §4a/§6 — the
  // timeline branch of the commit). Same fresh extraction as `commitToEntry`; the
  // only difference is the destination — instead of proposing a base-write to the
  // entry's pane, it mints a mutation set pinned to the subject and points the
  // chat's `staged_set` edge at it (via `onStaged`). The AI authors *what*
  // changes and *to whom*, never *where*: the set has no scene and no position;
  // the writer later PLACES it in prose (§5, S4b). Nothing overwrites the entry.
  async stageToPendingSet(): Promise<void> {
    if (this.running || this.committing || !this.canStage) return;
    const entryId = this.commitTargetEntryId;
    const entryType = this.subjectEntryType;
    this.deps.setError(null);
    this.deps.setNotice(null);
    this.committing = true;
    try {
      const patch = await this.extractPatch(
        entryId,
        "Couldn't read the model's response as a change — ask it to finalize again.",
      );
      if (!patch) return;
      const rows = patchToRows(patch);
      if (rows.length === 0) {
        this.deps.setNotice("The model proposed no changes to stage.");
        return;
      }
      const subject = this.deps.entryTitle(entryId) ?? "the entry";
      // The edge is singular (§4): if the chat already owns a set, refine THAT
      // set in place — a whole re-extraction replaces its rows — rather than
      // minting a second, orphaned one. Only a *deleted* owned set (404) falls
      // through to a fresh mint; any other load failure (transient, 5xx) aborts
      // via the outer catch rather than silently minting a duplicate. `onStaged`
      // runs only on a first stage, so a refine never rewrites the correct edge.
      const ownedId = this.deps.getStagedSetId();
      let existing: MutationSetEntry | null = null;
      if (ownedId) {
        try {
          existing = await api.getMutationSetEntry(ownedId);
        } catch (e) {
          if (!(e instanceof HttpError && e.status === 404)) throw e;
          existing = null; // the owned set was deleted — stage a fresh one below
        }
      }
      let updated = false;
      if (existing) {
        await api.saveMutationSetEntry({
          ...existing,
          target_entry_type: entryType,
          target_entity: entryId,
          rows,
        });
        updated = true;
      } else {
        const set = await api.createMutationSetEntry({
          title: `Staged change — ${subject}`,
          target_entry_type: entryType,
          target_entity: entryId,
          rows,
        });
        await this.deps.onStaged(set.id);
      }
      const dropped =
        patch.dropped.length > 0
          ? ` Ignored ${patch.dropped.length} field(s) the model couldn't set legally: ${patch.dropped.join(", ")}.`
          : "";
      const count = `${rows.length} change${rows.length > 1 ? "s" : ""}`;
      this.deps.setNotice(
        `${updated ? "Updated the staged change" : "Staged"} to ${subject} (${count}) — ` +
          `review it under pending changes on the card, then place it from a scene.${dropped}`,
      );
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
            commit_fields: this.commitFields,
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
    const proposal = this.draftProposal;
    this.creatingDraft = true;
    try {
      // Null only when no entry was minted (run() swallows the error and the
      // draft must survive a 409 / offline rejection); a post-create step
      // failure still returns the id, so an entry that exists always clears
      // the draft — a surviving Create button would mint a duplicate.
      const createdId = await treeActions.createLoreEntryFromDraft(this.draftEntryType, proposal);
      // A chat switch while the create was in flight reset this controller
      // (applyChatSession → reset()): the host now feeds a different chat, so
      // the subject write-back would stamp THAT chat with this brainstorm's
      // entry. Skip it — the draft is already gone with the old chat's state.
      if (this.draftProposal !== proposal) return;
      if (createdId) {
        // The entry exists, so the draft is spent regardless of how the stamp
        // goes. Note reset() releases creatingDraft while onCreated is still
        // in flight — re-entry stays blocked by the null draftProposal, which
        // is the guard a future onCreated implementation may rely on.
        this.reset();
        await this.deps.onCreated(createdId);
      }
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
