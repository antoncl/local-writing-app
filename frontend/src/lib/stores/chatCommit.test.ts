import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatCommitController, type ChatCommitDeps, patchToRows } from "./chatCommit.svelte";
import { entryBrainstorm } from "./entryBrainstorm.svelte";
import { api, HttpError } from "@/lib/api";
import { treeActions } from "@/lib/stores/treeActions.svelte";
import type { AIEntryPatch, EntryPatchExtraction, MutationSetEntry } from "@/lib/types";

// The chat-pane end of the ADR-0046 loop (#849 extracted it from ChatBodyView;
// ADR-0051 S4 made the commit a server-side extraction; ADR-0067 S2 made it a
// cached CONTINUATION of the chat itself, reading back the field set the
// chat's own lock render registered): it posts the transcript + chat_id to the
// extraction endpoint, then publishes the returned patch to the cross-pane
// `entryBrainstorm` store (revise) or holds a whole draft (create). These
// tests pin what the wiring could silently break: the launch-mode derivations,
// what's posted to the endpoint (assistant / history / chat_id), the `replace`
// body strip (the producer-side half of the S5-next prose-safety guarantee),
// cost attribution, and the guards.

// The whole module is mocked, so re-export a HttpError shaped like the real one
// (defined INSIDE the hoisted factory to dodge the class TDZ) — the controller's
// `instanceof HttpError` 404 check resolves against THIS class, and the tests
// construct it via the imported `HttpError`, so they agree.
vi.mock("@/lib/api", () => {
  class HttpError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  }
  return {
    HttpError,
    api: {
      extractEntryPatch: vi.fn(),
      extractEntryDraft: vi.fn(),
      createMutationSetEntry: vi.fn(),
      getMutationSetEntry: vi.fn(),
      saveMutationSetEntry: vi.fn(),
    },
  };
});

vi.mock("@/lib/stores/treeActions.svelte", () => ({
  treeActions: { createNodeFromDraft: vi.fn() },
}));

const extractPatch = vi.mocked(api.extractEntryPatch);
const extractDraft = vi.mocked(api.extractEntryDraft);
const createSet = vi.mocked(api.createMutationSetEntry);
const getSet = vi.mocked(api.getMutationSetEntry);
const saveSet = vi.mocked(api.saveMutationSetEntry);
const createFromDraft = vi.mocked(treeActions.createNodeFromDraft);

// A minimal created-set stub — the stage path only reads `.id`.
const madeSet = (id: string): MutationSetEntry => ({
  id,
  title: "Staged change",
  revision: "r1",
  entry_type: "mutation_set",
  target_entry_type: "lore:character",
  target_entity: "lore-1",
  rows: [],
  placed: false,
  source_layer_id: "",
  source_layer_label: "",
});

const patch = (over: Partial<AIEntryPatch> = {}): AIEntryPatch => ({
  body: null,
  fields: {},
  dropped: [],
  garbled: false,
  ...over,
});

// A successful extraction. `cost` null models a provider that returned no usage
// (the cost-attribution branch must skip it).
const okResult = (
  patchOver: Partial<AIEntryPatch> = {},
  cost: number | null = 0.02,
): EntryPatchExtraction => ({ patch: patch(patchOver), cost_usd: cost, ok: true, error: null });

// A failed extraction — the turn itself errored or returned nothing.
const failResult = (error: string, cost: number | null = 0): EntryPatchExtraction => ({
  patch: null,
  cost_usd: cost,
  ok: false,
  error,
});

function makeDeps(over: Partial<ChatCommitDeps> = {}): ChatCommitDeps {
  return {
    getAssistantId: () => "asst-1",
    getHistory: () => [{ role: "user", content: "brainstorm turn" }],
    getChatId: () => "chat_1",
    addTurnCost: vi.fn(async () => {}),
    setError: vi.fn(),
    setNotice: vi.fn(),
    entryTitle: vi.fn(() => null),
    getStagedSetId: vi.fn(() => ""),
    onStaged: vi.fn(async () => {}),
    onCreated: vi.fn(async () => {}),
    revealEntry: vi.fn(),
    ...over,
  };
}

function makeController(over: Partial<ChatCommitDeps> = {}) {
  const deps = makeDeps(over);
  return { c: new ChatCommitController(deps), deps };
}

describe("ChatCommitController — launch-mode derivations", () => {
  it("isCommitChat tracks whether the fed output declares a commit", () => {
    const { c } = makeController();
    expect(c.isCommitChat).toBe(false);
    c.output = {}; // a plain chat: no handler, no commit
    expect(c.isCommitChat).toBe(false);
    c.output = { handler: "extract_to_node", commit: { review: "visual_diff" } };
    expect(c.isCommitChat).toBe(true);
  });

  it("reads the revise target from the `entry` input draft (trimmed)", () => {
    const { c } = makeController();
    expect(c.commitTargetEntryId).toBe("");
    c.inputDrafts = { entry: "  lore-42  " };
    expect(c.commitTargetEntryId).toBe("lore-42");
  });

  it("isCreateBrainstorm = a commit + no entry + an entry_type", () => {
    const { c } = makeController();
    c.output = { handler: "extract_to_node", commit: { review: "visual_diff" } };
    c.inputDrafts = { entry_type: "lore:character" };
    expect(c.draftEntryType).toBe("lore:character");
    expect(c.isCreateBrainstorm).toBe(true);
    // A seeded `entry` makes it a revise, not a create — mutually exclusive.
    c.inputDrafts = { entry_type: "lore:character", entry: "lore-1" };
    expect(c.isCreateBrainstorm).toBe(false);
  });
});

// ADR-0063 S1: a prompt DECLARES the entry_type its commit creates. A declared
// target makes the chat a create brainstorm for that type — and WINS over how the
// chat was launched (a seeded `entry` would otherwise mean revise).
describe("ChatCommitController — commit.target (ADR-0063 S1)", () => {
  it("commitTarget reads output.commit.target (trimmed), else empty", () => {
    const { c } = makeController();
    expect(c.commitTarget).toBe("");
    c.output = { handler: "extract_to_node", commit: { review: "visual_diff", target: "  lore:character  " } };
    expect(c.commitTarget).toBe("lore:character");
  });

  it("a declared target drives draftEntryType and forces isCreateBrainstorm", () => {
    const { c } = makeController();
    c.output = { handler: "extract_to_node", commit: { review: "visual_diff", target: "lore:character" } };
    // No launch inputs at all — the target alone makes it a create brainstorm.
    expect(c.draftEntryType).toBe("lore:character");
    expect(c.isCreateBrainstorm).toBe(true);
  });

  it("the target wins over a seeded entry — create, never revise, and no staging", () => {
    const { c } = makeController();
    c.output = { handler: "extract_to_node", commit: { review: "visual_diff", target: "lore:character" } };
    // A seeded `entry` would normally mean revise; the declared target overrides it.
    c.inputDrafts = { entry: "lore-1" };
    c.subjectEntryType = "lore:character";
    expect(c.isCreateBrainstorm).toBe(true);
    expect(c.canStage).toBe(false);
  });

  it("commitDraft extracts against the declared target type", async () => {
    const { c } = makeController();
    c.output = { handler: "extract_to_node", commit: { review: "visual_diff", target: "lore:character" } };
    extractDraft.mockResolvedValue(okResult({ body: "a spine", fields: { name: "Vale" } }));

    await c.commitDraft();

    expect(extractDraft).toHaveBeenCalledWith("lore:character", {
      messages: [{ role: "user", content: "brainstorm turn" }],
      assistant_id: "asst-1",
      chat_id: "chat_1",
    });
  });
});

describe("ChatCommitController — commitToEntry", () => {
  beforeEach(() => {
    entryBrainstorm.clear("lore-1");
    vi.clearAllMocks();
  });

  function reviseController(over: Partial<ChatCommitDeps> = {}) {
    const made = makeController(over);
    made.c.output = { handler: "extract_to_node", commit: { review: "visual_diff" } };
    made.c.inputDrafts = { entry: "lore-1" };
    return made;
  }

  it("no-ops while a turn is streaming", async () => {
    const { c, deps } = reviseController();
    c.running = true;
    await c.commitToEntry();
    expect(extractPatch).not.toHaveBeenCalled();
    expect(deps.setError).not.toHaveBeenCalled();
  });

  it("errors when there is no target entry", async () => {
    const { c, deps } = makeController();
    c.output = { handler: "extract_to_node", commit: { review: "visual_diff" } }; // commit but no `entry` draft
    await c.commitToEntry();
    expect(deps.setError).toHaveBeenCalledWith(
      "This brainstorm has no target entry to commit to.",
    );
    expect(extractPatch).not.toHaveBeenCalled();
  });

  it("posts the transcript, assistant, and the chat's own id to the extraction endpoint", async () => {
    const { c } = reviseController();
    c.output = { handler: "extract_to_node", commit: { review: "replace" } };
    extractPatch.mockResolvedValue(okResult({ fields: { bio: "x" } }));

    await c.commitToEntry();

    // The whole point of S4/ADR-0067 S2: the commit is one call to the
    // extraction endpoint, carrying the transcript (pure input), the
    // assistant, and the chat's own id — so the server can read back the
    // field set the chat's lock render registered and continue the same
    // cached conversation.
    expect(extractPatch).toHaveBeenCalledWith("lore-1", {
      messages: [{ role: "user", content: "brainstorm turn" }],
      assistant_id: "asst-1",
      chat_id: "chat_1",
    });
  });

  it("publishes a visual_diff proposal and names the target", async () => {
    const { c, deps } = reviseController({ entryTitle: () => "Captain Vale" });
    extractPatch.mockResolvedValue(okResult({ body: "revised prose", fields: { bio: "new" } }));

    await c.commitToEntry();

    expect(extractPatch).toHaveBeenCalledWith(
      "lore-1",
      expect.objectContaining({ chat_id: "chat_1" }),
    );
    expect(entryBrainstorm.proposalFor("lore-1")).toEqual({
      body: "revised prose",
      fields: { bio: "new" },
      reviewMode: "visual_diff",
    });
    expect(deps.setNotice).toHaveBeenLastCalledWith("Committed — review it on Captain Vale.");
    expect(c.committing).toBe(false);
  });

  it("strips the body for a `replace` review — the producer-side prose guard", async () => {
    // A `replace` prompt (scene summary) swaps one field whole; even if the model
    // returns a body, the stored proposal must be fields-only so a summary
    // regenerate can never carry a scene's manuscript prose to the review.
    const { c } = reviseController();
    c.output = { handler: "extract_to_node", commit: { review: "replace" } };
    extractPatch.mockResolvedValue(okResult({ body: "REWRITTEN PROSE", fields: { summary: "a synopsis" } }));

    await c.commitToEntry();

    expect(entryBrainstorm.proposalFor("lore-1")).toEqual({
      body: null,
      fields: { summary: "a synopsis" },
      reviewMode: "replace",
    });
  });

  it("surfaces a garbled reply and proposes nothing", async () => {
    const { c, deps } = reviseController();
    extractPatch.mockResolvedValue(okResult({ garbled: true }));

    await c.commitToEntry();

    expect(deps.setError).toHaveBeenCalledWith(
      "Couldn't read the model's response as a patch — ask it to finalize again.",
    );
    expect(entryBrainstorm.proposalFor("lore-1")).toBeNull();
  });

  it("notices an empty patch instead of a silent no-op", async () => {
    const { c, deps } = reviseController();
    extractPatch.mockResolvedValue(okResult({ body: null, fields: {} }));

    await c.commitToEntry();

    expect(deps.setNotice).toHaveBeenCalledWith("The model proposed no changes to commit.");
    expect(entryBrainstorm.proposalFor("lore-1")).toBeNull();
  });

  it("reports dropped fields in the hand-off notice", async () => {
    const { c, deps } = reviseController({ entryTitle: () => "Vale" });
    extractPatch.mockResolvedValue(okResult({ fields: { bio: "x" }, dropped: ["id", "score"] }));

    await c.commitToEntry();

    expect(deps.setNotice).toHaveBeenLastCalledWith(
      "Committed — review it on Vale. Ignored 2 field(s) the model couldn't set legally: id, score.",
    );
  });

  it("falls back to \"the scene\" when the target isn't in the roster", async () => {
    const { c, deps } = reviseController(); // entryTitle → null (a scene subject)
    extractPatch.mockResolvedValue(okResult({ fields: { summary: "s" } }));

    await c.commitToEntry();

    expect(deps.setNotice).toHaveBeenLastCalledWith("Committed — review it on the scene.");
  });

  it("attributes the billed extraction turn's cost, and skips it when unbilled", async () => {
    const { c, deps } = reviseController();
    extractPatch.mockResolvedValue(okResult({ fields: { bio: "x" } }, 0.05));
    await c.commitToEntry();
    expect(deps.addTurnCost).toHaveBeenCalledWith(0.05);

    vi.mocked(deps.addTurnCost).mockClear();
    entryBrainstorm.clear("lore-1");
    extractPatch.mockResolvedValue(okResult({ fields: { bio: "x" } }, null)); // no usage returned
    await c.commitToEntry();
    expect(deps.addTurnCost).not.toHaveBeenCalled();
  });

  it("surfaces an extraction that returned nothing", async () => {
    const { c, deps } = reviseController();
    extractPatch.mockResolvedValue(failResult("boom"));

    await c.commitToEntry();

    expect(deps.setError).toHaveBeenCalledWith("boom");
    expect(entryBrainstorm.proposalFor("lore-1")).toBeNull();
  });

  it("fronts the target entry after a proposed commit", async () => {
    const { c, deps } = reviseController();
    extractPatch.mockResolvedValue(okResult({ fields: { bio: "new" } }));

    await c.commitToEntry();

    expect(deps.revealEntry).toHaveBeenCalledWith("lore-1");
  });

  it("does not front the entry when the patch proposes nothing", async () => {
    const { c, deps } = reviseController();
    extractPatch.mockResolvedValue(okResult({ body: null, fields: {} }));

    await c.commitToEntry();

    expect(deps.revealEntry).not.toHaveBeenCalled();
  });

  it("does not front the entry on a garbled reply", async () => {
    const { c, deps } = reviseController();
    extractPatch.mockResolvedValue(okResult({ garbled: true }));

    await c.commitToEntry();

    expect(deps.revealEntry).not.toHaveBeenCalled();
  });
});

describe("ChatCommitController — create mode", () => {
  beforeEach(() => vi.clearAllMocks());

  function createController(over: Partial<ChatCommitDeps> = {}) {
    const made = makeController(over);
    made.c.output = { handler: "extract_to_node", commit: { review: "visual_diff" } };
    made.c.inputDrafts = { entry_type: "lore:character" };
    return made;
  }

  it("holds a validated draft for the review card", async () => {
    const { c } = createController();
    extractDraft.mockResolvedValue(okResult({ body: "a life", fields: { name: "Vale" }, dropped: ["id"] }));

    await c.commitDraft();

    expect(extractDraft).toHaveBeenCalledWith("lore:character", {
      messages: [{ role: "user", content: "brainstorm turn" }],
      assistant_id: "asst-1",
      chat_id: "chat_1",
    });
    expect(c.draftProposal).toEqual({ body: "a life", fields: { name: "Vale" } });
    expect(c.draftDropped).toEqual(["id"]);
  });

  it("notices an empty draft and holds nothing", async () => {
    const { c, deps } = createController();
    extractDraft.mockResolvedValue(okResult({ body: null, fields: {} }));

    await c.commitDraft();

    expect(deps.setNotice).toHaveBeenCalledWith("The model proposed no entry to create.");
    expect(c.draftProposal).toBeNull();
  });

  it("createDraft resets and stamps the chat's subject only when the create succeeds", async () => {
    const { c, deps } = createController();
    c.draftProposal = { body: "a life", fields: { name: "Vale" } };

    createFromDraft.mockResolvedValueOnce(null); // e.g. a 409 — nothing created
    await c.createDraft();
    expect(c.draftProposal).not.toBeNull(); // draft survives so it isn't lost
    expect(deps.onCreated).not.toHaveBeenCalled(); // no entry → no subject stamp

    createFromDraft.mockResolvedValueOnce({ id: "lore_new", title: "Vale" });
    await c.createDraft();
    expect(createFromDraft).toHaveBeenLastCalledWith("lore:character", { body: "a life", fields: { name: "Vale" } });
    expect(c.draftProposal).toBeNull(); // cleared on success
    // #983: the created entry becomes the chat's subject — its first
    // conversation — and the title rides along for the host's retitle.
    expect(deps.onCreated).toHaveBeenCalledWith("lore_new", "Vale");
  });

  it("reset clears a pending draft", () => {
    const { c } = createController();
    c.draftProposal = { body: "x", fields: {} };
    c.draftDropped = ["id"];
    c.creatingDraft = true;
    c.reset();
    expect(c.draftProposal).toBeNull();
    expect(c.draftDropped).toEqual([]);
    expect(c.creatingDraft).toBe(false);
  });
});

// #986: the extraction spans seconds — if the user switches chat in the pane
// mid-flight, the host feeds a DIFFERENT active chat, and a write-back
// (cost / staged_set edge / subject stamp) minted from the stale extraction
// would land on the wrong chat. Each commit path snapshots `getChatId()` at
// entry and no-ops its write-back(s) when it's moved by the time the
// extraction resolves. Simulated here by flipping a mutable `getChatId`
// return value from inside the extraction/create mock, the way the real
// switch would race it.
describe("ChatCommitController — #986 chat switch during an in-flight commit", () => {
  beforeEach(() => vi.clearAllMocks());

  it("stage: a chat switch mid-extraction skips the set write-back and the cost", async () => {
    let activeChatId = "chat_1";
    const { c, deps } = makeController({ getChatId: () => activeChatId });
    c.output = { handler: "extract_to_node", commit: { review: "visual_diff" } };
    c.inputDrafts = { entry: "lore-1" };
    c.subjectEntryType = "lore:character";
    extractPatch.mockImplementation(async () => {
      activeChatId = "chat_2"; // the user switched chat while this extraction ran
      return okResult({ fields: { condition: "werewolf" } }, 0.03);
    });

    await c.stageToPendingSet();

    expect(createSet).not.toHaveBeenCalled();
    expect(deps.onStaged).not.toHaveBeenCalled();
    expect(deps.addTurnCost).not.toHaveBeenCalled();
  });

  it("commitToEntry: a chat switch mid-extraction skips the cost attribution", async () => {
    // The revise publish itself has no chat write-back (it only touches the
    // cross-pane entryBrainstorm store), so cost is the only gated effect.
    let activeChatId = "chat_1";
    const { c, deps } = makeController({ getChatId: () => activeChatId });
    c.output = { handler: "extract_to_node", commit: { review: "visual_diff" } };
    c.inputDrafts = { entry: "lore-1" };
    extractPatch.mockImplementation(async () => {
      activeChatId = "chat_2";
      return okResult({ fields: { bio: "x" } }, 0.05);
    });

    await c.commitToEntry();

    expect(deps.addTurnCost).not.toHaveBeenCalled();
  });

  it("createDraft: a chat switch mid-create skips the subject stamp; no switch still stamps it", async () => {
    let activeChatId = "chat_1";
    const { c, deps } = makeController({ getChatId: () => activeChatId });
    c.output = { handler: "extract_to_node", commit: { review: "visual_diff" } };
    c.inputDrafts = { entry_type: "lore:character" };

    c.draftProposal = { body: "a life", fields: { name: "Vale" } };
    createFromDraft.mockImplementationOnce(async () => {
      activeChatId = "chat_2"; // switched while the create was in flight
      return { id: "lore_new", title: "Vale" };
    });
    await c.createDraft();
    expect(deps.onCreated).not.toHaveBeenCalled();

    c.draftProposal = { body: "a life", fields: { name: "Vale" } };
    createFromDraft.mockResolvedValueOnce({ id: "lore_new2", title: "Vale" });
    await c.createDraft();
    expect(deps.onCreated).toHaveBeenCalledWith("lore_new2", "Vale");
  });
});

// ADR-0055 §2/§4a: the patch → mutation-set-rows mapping. Every row is a
// `replace` (always op-legal), and the patch's values were already type-validated
// by the extraction endpoint, so a staged set can never carry an illegal row.
describe("patchToRows", () => {
  it("maps body + scalar fields to replace rows (body first)", () => {
    expect(patchToRows({ body: "new prose", fields: { bio: "a soldier", rank: "captain" } })).toEqual([
      { field: "body", op: "replace", value: "new prose" },
      { field: "bio", op: "replace", value: "a soldier" },
      { field: "rank", op: "replace", value: "captain" },
    ]);
  });

  it("omits the body row when the patch has no body", () => {
    expect(patchToRows({ body: null, fields: { bio: "x" } })).toEqual([
      { field: "bio", op: "replace", value: "x" },
    ]);
  });

  it("comma-joins a collection value (mirrors the marker's whole-collection replace)", () => {
    // A collection replace carries the comma-joined value the backend splits with
    // `_split_collection_value` — matching the set editor's `String(array)`.
    expect(patchToRows({ body: null, fields: { aliases: ["Vale", "The Captain"] } })).toEqual([
      { field: "aliases", op: "replace", value: "Vale,The Captain" },
    ]);
  });

  it("serializes a null field value as \"\" (matches toMarkerString, not \"null\")", () => {
    expect(patchToRows({ body: null, fields: { epithet: null } })).toEqual([
      { field: "epithet", op: "replace", value: "" },
    ]);
  });

  it("is empty for a no-op patch", () => {
    expect(patchToRows({ body: null, fields: {} })).toEqual([]);
  });
});

describe("ChatCommitController — stageToPendingSet", () => {
  beforeEach(() => vi.clearAllMocks());

  // A committing brainstorm whose subject is a time-travel-aware lore entity: the
  // host fed its entry_type, so staging is offered (§4a/§6).
  function stageController(over: Partial<ChatCommitDeps> = {}) {
    const made = makeController(over);
    made.c.output = { handler: "extract_to_node", commit: { review: "visual_diff" } };
    made.c.inputDrafts = { entry: "lore-1" };
    made.c.subjectEntryType = "lore:character";
    return made;
  }

  it("canStage requires a commit, a lore target, and a fed entry_type", () => {
    const { c } = makeController();
    c.output = { handler: "extract_to_node", commit: { review: "visual_diff" } };
    c.inputDrafts = { entry: "lore-1" };
    expect(c.canStage).toBe(false); // no subject entry_type yet (not a lore subject)
    c.subjectEntryType = "lore:character";
    expect(c.canStage).toBe(true);
    // A scene/plot-card subject (no lore entry_type) never offers staging.
    c.subjectEntryType = "";
    expect(c.canStage).toBe(false);
  });

  it("mints a subject-pinned set from the extracted patch and points the chat at it", async () => {
    const { c, deps } = stageController({ entryTitle: () => "Mira" });
    extractPatch.mockResolvedValue(
      okResult({ body: "transformation notes", fields: { condition: "werewolf" } }),
    );
    createSet.mockResolvedValue(madeSet("set-9"));

    await c.stageToPendingSet();

    // Same fresh-extraction call as commitToEntry.
    expect(extractPatch).toHaveBeenCalledWith("lore-1", {
      messages: [{ role: "user", content: "brainstorm turn" }],
      assistant_id: "asst-1",
      chat_id: "chat_1",
    });
    // A set pinned to the subject, carrying the patch as replace rows.
    expect(createSet).toHaveBeenCalledWith({
      title: "Staged change — Mira",
      target_entry_type: "lore:character",
      target_entity: "lore-1",
      rows: [
        { field: "body", op: "replace", value: "transformation notes" },
        { field: "condition", op: "replace", value: "werewolf" },
      ],
    });
    // The chat owns it now (its staged_set edge). No update path — the chat
    // didn't already own a set.
    expect(deps.onStaged).toHaveBeenCalledWith("set-9");
    expect(getSet).not.toHaveBeenCalled();
    expect(saveSet).not.toHaveBeenCalled();
    expect(c.committing).toBe(false);
  });

  it("attributes the extraction cost and reports dropped fields in the notice", async () => {
    const { c, deps } = stageController({ entryTitle: () => "Mira" });
    extractPatch.mockResolvedValue(okResult({ fields: { condition: "werewolf" }, dropped: ["id"] }, 0.03));
    createSet.mockResolvedValue(madeSet("set-9"));

    await c.stageToPendingSet();

    expect(deps.addTurnCost).toHaveBeenCalledWith(0.03);
    expect(deps.setNotice).toHaveBeenLastCalledWith(
      "Staged to Mira (1 change) — review it under pending changes on the card, then place it from a scene." +
        " Ignored 1 field(s) the model couldn't set legally: id.",
    );
  });

  it("refines the SAME set in place when the chat already owns one (singular edge)", async () => {
    // The chat owns set-9; a re-stage must UPDATE it, not mint a second orphan.
    const { c, deps } = stageController({ entryTitle: () => "Mira", getStagedSetId: () => "set-9" });
    extractPatch.mockResolvedValue(okResult({ fields: { condition: "alpha werewolf" } }));
    getSet.mockResolvedValue(madeSet("set-9"));

    await c.stageToPendingSet();

    expect(getSet).toHaveBeenCalledWith("set-9");
    // The existing set's identity/revision is preserved; only the pin + rows are
    // rewritten from the fresh extraction.
    expect(saveSet).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "set-9",
        target_entry_type: "lore:character",
        target_entity: "lore-1",
        rows: [{ field: "condition", op: "replace", value: "alpha werewolf" }],
      }),
    );
    expect(createSet).not.toHaveBeenCalled();
    expect(deps.onStaged).not.toHaveBeenCalled(); // edge already correct
    expect(deps.setNotice).toHaveBeenLastCalledWith(
      "Updated the staged change to Mira (1 change) — review it under pending changes on the card, then place it from a scene.",
    );
  });

  it("mints a fresh set when the owned id is a 404 (the set was deleted)", async () => {
    const { c, deps } = stageController({ entryTitle: () => "Mira", getStagedSetId: () => "set-gone" });
    extractPatch.mockResolvedValue(okResult({ fields: { condition: "werewolf" } }));
    getSet.mockRejectedValue(new HttpError("not found", 404, null)); // the owned set is gone
    createSet.mockResolvedValue(madeSet("set-new"));

    await c.stageToPendingSet();

    expect(saveSet).not.toHaveBeenCalled();
    expect(createSet).toHaveBeenCalled();
    expect(deps.onStaged).toHaveBeenCalledWith("set-new"); // re-point at the fresh one
  });

  it("aborts on a transient load error instead of minting a duplicate", async () => {
    // A non-404 failure loading the owned set must NOT be treated as "deleted" —
    // otherwise a blip mints a second set and orphans the real one.
    const { c, deps } = stageController({ entryTitle: () => "Mira", getStagedSetId: () => "set-9" });
    extractPatch.mockResolvedValue(okResult({ fields: { condition: "werewolf" } }));
    getSet.mockRejectedValue(new HttpError("server busy", 503, null));

    await c.stageToPendingSet();

    expect(createSet).not.toHaveBeenCalled();
    expect(saveSet).not.toHaveBeenCalled();
    expect(deps.onStaged).not.toHaveBeenCalled();
    expect(deps.setError).toHaveBeenCalledWith("server busy");
  });

  it("does not create a set for an empty patch", async () => {
    const { c, deps } = stageController();
    extractPatch.mockResolvedValue(okResult({ body: null, fields: {} }));

    await c.stageToPendingSet();

    expect(createSet).not.toHaveBeenCalled();
    expect(deps.onStaged).not.toHaveBeenCalled();
    expect(deps.setNotice).toHaveBeenCalledWith("The model proposed no changes to stage.");
  });

  it("no-ops when the subject is not a lore entity (canStage false)", async () => {
    const { c } = stageController();
    c.subjectEntryType = ""; // e.g. a scene or plot-card subject
    await c.stageToPendingSet();
    expect(extractPatch).not.toHaveBeenCalled();
    expect(createSet).not.toHaveBeenCalled();
  });

  it("surfaces a garbled reply and stages nothing", async () => {
    const { c, deps } = stageController();
    extractPatch.mockResolvedValue(okResult({ garbled: true }));

    await c.stageToPendingSet();

    expect(deps.setError).toHaveBeenCalledWith(
      "Couldn't read the model's response as a change — ask it to finalize again.",
    );
    expect(createSet).not.toHaveBeenCalled();
  });

  it("does not point the chat at a set the create call failed to mint", async () => {
    const { c, deps } = stageController();
    extractPatch.mockResolvedValue(okResult({ fields: { condition: "werewolf" } }));
    createSet.mockRejectedValue(new Error("disk full"));

    await c.stageToPendingSet();

    expect(deps.onStaged).not.toHaveBeenCalled();
    expect(deps.setError).toHaveBeenCalledWith("disk full");
    expect(c.committing).toBe(false);
  });

  it("staging never fronts an entry (review lives on the card, not the entry pane)", async () => {
    const { c, deps } = stageController({ entryTitle: () => "Mira" });
    extractPatch.mockResolvedValue(okResult({ fields: { condition: "werewolf" } }));
    createSet.mockResolvedValue(madeSet("set-9"));

    await c.stageToPendingSet();

    expect(deps.revealEntry).not.toHaveBeenCalled();
  });
});
