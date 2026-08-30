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
import { entryIdFromPickValue } from "@/lib/editor-core/promptResolution";
import { entryBrainstorm } from "@/lib/stores/entryBrainstorm.svelte";
import { treeActions } from "@/lib/stores/treeActions.svelte";
import { extractHandler, type ExtractHost } from "@/lib/editor-core/outputHandlers";

/** The live chat state + status/cost sinks the controller reaches into. Stable
 *  for the controller's life (wired once at construction) — the reactive inputs
 *  the derivations track are the fed `$state` below, not these. */
export interface ChatCommitDeps {
  /** Assistant bound to the chat, or "" for the machine default. */
  getAssistantId: () => string;
  /** The visible transcript, mapped to the extraction request's message shape —
   *  the extraction reads it as pure input (ADR-0051 S4). */
  getHistory: () => Pick<ChatMessage, "role" | "content">[];
  /** The chat's own node id (ADR-0067 S2): the commit runs as a cached
   *  CONTINUATION of this chat, so the server can read back the field set its
   *  lock render registered and reuse the cached system prefix + lore. */
  getChatId: () => string;
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
   *  drafted it (#983). `entryTitle` rides along for the host's retitle to the
   *  launched-with-subject naming convention. Same host-owned write-back shape
   *  as onStaged. */
  onCreated: (entryId: string, entryTitle: string) => Promise<void>;
  /** Bring the entry a revise commit just proposed to into view — open its pane
   *  and front it — so the proposed-vs-current review renders where the author is
   *  looking, not only behind a review-dot on a tab they must find. The commit
   *  runs from the chat pane; the review renders on the entry pane. Host-owned
   *  because resolving an entry's kind to a pane opener is host policy (the
   *  controller is kind-agnostic). Called only after a change was actually
   *  proposed. */
  revealEntry: (entryId: string) => void;
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
  /** The active prompt's `output` config (ADR-0054): routing is
   *  `outputHandlerFor(output.handler)` (`PromptOutput` has no `.kind`); a
   *  `.commit` marks a brainstorm whose result is extracted to its `entry`
   *  target (`.commit.review` = how it's reviewed; WHAT it extracts is
   *  authored in the prompt's own `field_contract` loop, read back at commit —
   *  ADR-0067 S2). */
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

  // #986: the chat this in-flight commit belongs to, snapshotted at entry. The
  // extraction spans seconds; if the user switches chat mid-flight the host feeds
  // a different active chat, so the write-backs (cost, staged_set edge, subject
  // stamp) would land on the WRONG chat and silently corrupt it. They no-op when
  // this token has moved. Safe as a single field because only one commit runs at
  // a time (the `committing` / `creatingDraft` guards).
  private commitOriginChatId = "";

  private chatUnchanged(): boolean {
    return this.deps.getChatId() === this.commitOriginChatId;
  }

  constructor(private readonly deps: ChatCommitDeps) {}

  /** A chat carrying a `commit` (ADR-0054 §2) extracts its result to a
   *  schema-typed node. The predicate is the *presence of the commit object* —
   *  "the presence of the object is the whole test" (ADR-0054 §2) — which is the
   *  canonical classification the rest of the app uses: `promptDeclaresCommit`,
   *  ChatBodyView's `chatSubjectEntryType`, and the backend `prompt_disposition`
   *  "Revise entities" shelf. Keying off the output *handler* instead diverges on
   *  representable front matter (an `extract_to_node` prompt with no `.commit`, or
   *  a commit riding an empty handler), so this reads `.commit` directly (#1705). */
  isCommitChat = $derived(!!this.output?.commit);
  /** The revise target — the `entry` input the launch seeded (empty in create
   *  mode). The draft may be an encoded context_pick list or a legacy bare id;
   *  read through the shared decoder, not as a raw string (#1482). */
  commitTargetEntryId = $derived(entryIdFromPickValue(this.inputDrafts["entry"]));
  // ADR-0046 §6.4 / ADR-0067 Amendment 1: the target entry_type is input-driven.
  // Every launcher seeds the required `entry_type`; create-vs-revise falls out of
  // whether an `entry` was also seeded.
  draftEntryType = $derived((this.inputDrafts["entry_type"] ?? "").trim());
  isCreateBrainstorm = $derived(
    this.isCommitChat && !this.commitTargetEntryId && !!this.draftEntryType,
  );
  /** ADR-0055 §4a/§6: a committing brainstorm on a time-travel-aware lore subject
   *  may stage its result as a subject-pinned mutation set (the timeline branch)
   *  instead of writing the entry's base (the canonical branch). Offered only
   *  when there is a revise target (a seeded `entry`) that is a lore entity — a
   *  create has no base to stage. */
  canStage = $derived(
    this.isCommitChat &&
      !!this.commitTargetEntryId &&
      !!this.subjectEntryType,
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
    // #986: the chat switched during the extraction — attributing this
    // extraction's cost to the now-active chat is the corruption; skip it.
    if (typeof result.cost_usd === "number" && this.chatUnchanged())
      await this.deps.addTurnCost(result.cost_usd);
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
  // transcript, assistant, and chat_id) — kept in one place so the two
  // destinations can never drift on what's posted. The garbled message is
  // per-caller (an entry "patch" vs a staged "change").
  private extractPatch(entryId: string, garbledMessage: string): Promise<AIEntryPatch | null> {
    return this.runExtraction(
      () =>
        api.extractEntryPatch(entryId, {
          messages: this.deps.getHistory(),
          assistant_id: this.deps.getAssistantId() || null,
          chat_id: this.deps.getChatId(),
        }),
      garbledMessage,
    );
  }

  // The commit-lifecycle shell every `extract_to_node` destination shares
  // (#1263): reset error/notice, hold the `committing` flag, run the handler's
  // produce → apply, surface a failure. Each caller supplies only its guard and
  // its ExtractHost (revise / stage / draft); a `produce` that returns null has
  // already reported why, so it just stops.
  private async runExtractCommit(host: ExtractHost): Promise<void> {
    this.deps.setError(null);
    this.deps.setNotice(null);
    this.committing = true;
    try {
      const patch = await extractHandler.produce(host);
      if (!patch) return;
      await extractHandler.apply(patch, host);
    } catch (e) {
      this.deps.setError((e as Error).message);
    } finally {
      this.committing = false;
    }
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
      // Set-and-return BEFORE runExtractCommit, so its setError(null) reset
      // never runs on this path and the message survives.
      this.deps.setError("This brainstorm has no target entry to commit to.");
      return;
    }
    this.commitOriginChatId = this.deps.getChatId();
    await this.runExtractCommit(this.reviseExtractHost(entryId));
  }

  // The `extract_to_node` host for a revise commit (ADR-0065): `produce` runs the
  // shared transcript extraction; `apply` publishes the patch to the entry pane's
  // diff review. The controller-state-bound work (cost attribution inside
  // extractPatch, the cross-pane propose + hand-off notice) stays here; the
  // handler is the registered dispatch seam.
  private reviseExtractHost(entryId: string): ExtractHost {
    return {
      extract: () =>
        this.extractPatch(
          entryId,
          "Couldn't read the model's response as a patch — ask it to finalize again.",
        ),
      publish: (patch) => this.publishRevisePatch(entryId, patch),
    };
  }

  // Publish an extracted patch to the entry pane's proposed-vs-current review
  // (the `patch_diff` apply). `replace` (a scene summary) swaps one field whole,
  // so any body the model returned is stripped — the producer side of the
  // prose-never-rewritten guarantee (which lives in `acceptFields`). A patch that
  // proposes nothing is surfaced, never a silent no-op.
  private publishRevisePatch(entryId: string, patch: AIEntryPatch): void {
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
    this.deps.revealEntry(entryId);
    // Hand-off cue (#710 slice 3): the commit lands here in the chat pane but the
    // review renders on the entry pane. Name where it went so the author knows to
    // flip over. A scene subject isn't in the caller's roster → "the scene".
    const reviewOn = this.deps.entryTitle(entryId) ?? "the scene";
    const dropped =
      patch.dropped.length > 0
        ? ` Ignored ${patch.dropped.length} field(s) the model couldn't set legally: ${patch.dropped.join(", ")}.`
        : "";
    this.deps.setNotice(`Committed — review it on ${reviewOn}.${dropped}`);
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
    this.commitOriginChatId = this.deps.getChatId();
    await this.runExtractCommit(
      this.stageExtractHost(this.commitTargetEntryId, this.subjectEntryType),
    );
  }

  // The `extract_to_node` host for the STAGE destination: the same fresh
  // transcript extraction the revise commit runs, but `apply` mints/refines a
  // subject-pinned mutation set instead of proposing a base-write. Routing it
  // through the handler keeps the chat pane's extract+review contract in a single
  // seam (#1126) — only the publish destination differs.
  private stageExtractHost(entryId: string, entryType: string): ExtractHost {
    return {
      extract: () =>
        this.extractPatch(
          entryId,
          "Couldn't read the model's response as a change — ask it to finalize again.",
        ),
      publish: (patch) => this.publishStage(entryId, entryType, patch),
    };
  }

  // Publish an extracted patch as a subject-pinned mutation set (ADR-0055 §4a/§6):
  // the AI authors *what* changes and *to whom*, never *where* — the set has no
  // scene and no position; the writer later PLACES it in prose (§5, S4b). A patch
  // that proposes nothing is surfaced, never a silent no-op.
  private async publishStage(
    entryId: string,
    entryType: string,
    patch: AIEntryPatch,
  ): Promise<void> {
    // #986: the chat switched during the extraction — the host now feeds a
    // different chat, so minting a set + `onStaged` would clobber THAT chat's
    // singular staged_set edge. Abort silently; the origin chat is no longer in
    // the pane, and a stray notice would land on the wrong one.
    if (!this.chatUnchanged()) return;
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
    // via the caller's catch rather than silently minting a duplicate. `onStaged`
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
        title: `Mutation set — ${subject}`,
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
      `${updated ? "Updated the mutation set" : "Staged a mutation set"} for ${subject} (${count}) — ` +
        `review it under Mutation sets on the card, then place it in a scene to make it active.${dropped}`,
    );
  }

  // Create mode (ADR-0046 §6.4 / ADR-0051 S4): a fresh extraction against the
  // target entry_type (no entry read), held as a whole draft for the review card.
  // Nothing is written until the author clicks Create.
  async commitDraft(): Promise<void> {
    if (this.running || this.committing || !this.isCreateBrainstorm) return;
    this.commitOriginChatId = this.deps.getChatId();
    await this.runExtractCommit(this.draftExtractHost(this.draftEntryType));
  }

  // The `extract_to_node` host for CREATE mode (ADR-0046 §6.4): a fresh extraction
  // against the target entry_type (no entry is read, so `extractEntryDraft` not
  // `extractEntryPatch`), whose `apply` holds the whole draft for the review card —
  // nothing is written until the author clicks Create. Same handler seam as
  // revise/stage (#1126); only the source and the held-draft destination differ.
  private draftExtractHost(entryType: string): ExtractHost {
    return {
      extract: () =>
        this.runExtraction(
          () =>
            api.extractEntryDraft(entryType, {
              messages: this.deps.getHistory(),
              assistant_id: this.deps.getAssistantId() || null,
              chat_id: this.deps.getChatId(),
            }),
          "Couldn't read the model's response as an entry — ask it to finalize again.",
        ),
      publish: (patch) => this.publishDraft(patch),
    };
  }

  // Hold an extracted patch as the create-mode draft for the review card. A patch
  // that proposes nothing is surfaced, never a silent no-op.
  private publishDraft(patch: AIEntryPatch): void {
    const hasBody = patch.body != null;
    const hasFields = Object.keys(patch.fields).length > 0;
    if (!hasBody && !hasFields) {
      this.deps.setNotice("The model proposed no entry to create.");
      return;
    }
    this.draftDropped = patch.dropped;
    this.draftProposal = { body: patch.body, fields: patch.fields };
  }

  async createDraft(): Promise<void> {
    if (!this.draftProposal || this.creatingDraft) return;
    const proposal = this.draftProposal;
    this.commitOriginChatId = this.deps.getChatId();
    this.creatingDraft = true;
    try {
      // Null only when no entry was minted (run() swallows the error and the
      // draft must survive a 409 / offline rejection); a post-create step
      // failure still returns the id, so an entry that exists always clears
      // the draft — a surviving Create button would mint a duplicate.
      const created = await treeActions.createNodeFromDraft(this.draftEntryType, proposal);
      // #986: a chat switch while the create was in flight — whether or not it
      // also reset this controller (applyChatSession → reset()) — means the host
      // now feeds a different chat, so the subject write-back would stamp THAT
      // chat with this brainstorm's entry. Skip it via the shared chat-id token;
      // the draft is already gone with the old chat's state.
      if (!this.chatUnchanged()) return;
      if (created) {
        // The entry exists, so the draft is spent regardless of how the stamp
        // goes. Note reset() releases creatingDraft while onCreated is still
        // in flight — re-entry stays blocked by the null draftProposal, which
        // is the guard a future onCreated implementation may rely on.
        this.reset();
        await this.deps.onCreated(created.id, created.title);
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
