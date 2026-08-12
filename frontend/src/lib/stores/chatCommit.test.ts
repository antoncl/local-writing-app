import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatCommitController, type ChatCommitDeps } from "./chatCommit.svelte";
import { entryBrainstorm } from "./entryBrainstorm.svelte";
import { api } from "@/lib/api";
import { treeActions } from "@/lib/stores/treeActions.svelte";
import type { AIChatResponse, AIEntryPatch } from "@/lib/types";

// The chat-pane end of the ADR-0046 loop (#849 extracted it from ChatBodyView):
// it runs the out-of-band finalize turn, validates the reply into a patch, and
// either publishes it to the cross-pane `entryBrainstorm` store (revise) or holds
// a whole draft (create). These tests pin what the extraction could silently
// break: the launch-mode derivations, the `replace` body strip (the producer-side
// half of the S5-next prose-safety guarantee), cost attribution, and the guards.

vi.mock("@/lib/api", () => ({
  api: {
    aiChat: vi.fn(),
    validateAiEntryPatch: vi.fn(),
    validateAiEntryDraft: vi.fn(),
  },
}));

vi.mock("@/lib/stores/treeActions.svelte", () => ({
  treeActions: { createLoreEntryFromDraft: vi.fn() },
}));

const aiChat = vi.mocked(api.aiChat);
const validatePatch = vi.mocked(api.validateAiEntryPatch);
const validateDraft = vi.mocked(api.validateAiEntryDraft);
const createFromDraft = vi.mocked(treeActions.createLoreEntryFromDraft);

// A minimal successful finalize reply. `cost` null models a provider that
// returned no usage (the cost-attribution branch must skip it).
const reply = (content: string, cost: number | null = 0.02): AIChatResponse =>
  ({
    role: "assistant",
    content,
    provider: "p",
    model: "m",
    latency_ms: 1,
    ok: true,
    truncated: false,
    cost_usd: cost,
  }) as AIChatResponse;

const patch = (over: Partial<AIEntryPatch> = {}): AIEntryPatch => ({
  body: null,
  fields: {},
  dropped: [],
  garbled: false,
  ...over,
});

function makeDeps(over: Partial<ChatCommitDeps> = {}): ChatCommitDeps {
  return {
    getAssistantId: () => "asst-1",
    getSystemPrompt: () => "SYSTEM",
    getHistory: () => [{ role: "user", content: "brainstorm turn" }],
    addTurnCost: vi.fn(async () => {}),
    setError: vi.fn(),
    setNotice: vi.fn(),
    entryTitle: vi.fn(() => null),
    ...over,
  };
}

function makeController(over: Partial<ChatCommitDeps> = {}) {
  const deps = makeDeps(over);
  return { c: new ChatCommitController(deps), deps };
}

describe("ChatCommitController — launch-mode derivations", () => {
  it("isEntryPatchChat tracks the fed output surface", () => {
    const { c } = makeController();
    expect(c.isEntryPatchChat).toBe(false);
    c.output = { kind: "chat_panel" };
    expect(c.isEntryPatchChat).toBe(false);
    c.output = { kind: "entry_patch" };
    expect(c.isEntryPatchChat).toBe(true);
  });

  it("reads the revise target from the `entry` input draft (trimmed)", () => {
    const { c } = makeController();
    expect(c.commitTargetEntryId).toBe("");
    c.inputDrafts = { entry: "  lore-42  " };
    expect(c.commitTargetEntryId).toBe("lore-42");
  });

  it("isCreateBrainstorm = entry_patch + no entry + an entry_type", () => {
    const { c } = makeController();
    c.output = { kind: "entry_patch" };
    c.inputDrafts = { entry_type: "lore:character" };
    expect(c.draftEntryType).toBe("lore:character");
    expect(c.isCreateBrainstorm).toBe(true);
    // A seeded `entry` makes it a revise, not a create — mutually exclusive.
    c.inputDrafts = { entry_type: "lore:character", entry: "lore-1" };
    expect(c.isCreateBrainstorm).toBe(false);
  });
});

describe("ChatCommitController — commitToEntry", () => {
  beforeEach(() => {
    entryBrainstorm.clear("lore-1");
    vi.clearAllMocks();
  });

  function reviseController(over: Partial<ChatCommitDeps> = {}) {
    const made = makeController(over);
    made.c.output = { kind: "entry_patch" };
    made.c.inputDrafts = { entry: "lore-1" };
    return made;
  }

  it("no-ops while a turn is streaming", async () => {
    const { c, deps } = reviseController();
    c.running = true;
    await c.commitToEntry();
    expect(aiChat).not.toHaveBeenCalled();
    expect(deps.setError).not.toHaveBeenCalled();
  });

  it("errors when there is no target entry", async () => {
    const { c, deps } = makeController();
    c.output = { kind: "entry_patch" }; // entry_patch but no `entry` draft
    await c.commitToEntry();
    expect(deps.setError).toHaveBeenCalledWith(
      "This brainstorm has no target entry to commit to.",
    );
    expect(aiChat).not.toHaveBeenCalled();
  });

  it("threads assistant, system prompt, and history into the out-of-band finalize turn", async () => {
    const { c } = reviseController();
    aiChat.mockResolvedValue(reply("{json}"));
    validatePatch.mockResolvedValue(patch({ fields: { bio: "x" } }));

    await c.commitToEntry();

    // The deps getters must reach the request verbatim, plus the appended finalize
    // instruction; chat_id is null so the turn stays out of band (not persisted).
    // Without this the whole point of the #849 extraction — that the wiring
    // survived — goes unchecked.
    expect(aiChat).toHaveBeenCalledWith(
      expect.objectContaining({
        assistant_id: "asst-1",
        system_prompt: "SYSTEM",
        chat_id: null,
        messages: [
          { role: "user", content: "brainstorm turn" },
          expect.objectContaining({ role: "user", content: expect.stringContaining("Finalize now") }),
        ],
      }),
    );
  });

  it("publishes a visual_diff proposal and names the review target", async () => {
    const { c, deps } = reviseController({ entryTitle: () => "Captain Vale" });
    aiChat.mockResolvedValue(reply("{json}"));
    validatePatch.mockResolvedValue(patch({ body: "revised prose", fields: { bio: "new" } }));

    await c.commitToEntry();

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
    c.output = { kind: "entry_patch", review: "replace" };
    aiChat.mockResolvedValue(reply("{json}"));
    validatePatch.mockResolvedValue(patch({ body: "REWRITTEN PROSE", fields: { summary: "a synopsis" } }));

    await c.commitToEntry();

    expect(entryBrainstorm.proposalFor("lore-1")).toEqual({
      body: null,
      fields: { summary: "a synopsis" },
      reviewMode: "replace",
    });
  });

  it("surfaces a garbled reply and proposes nothing", async () => {
    const { c, deps } = reviseController();
    aiChat.mockResolvedValue(reply("not json"));
    validatePatch.mockResolvedValue(patch({ garbled: true }));

    await c.commitToEntry();

    expect(deps.setError).toHaveBeenCalledWith(
      "Couldn't read the model's response as a patch — ask it to finalize again.",
    );
    expect(entryBrainstorm.proposalFor("lore-1")).toBeNull();
  });

  it("notices an empty patch instead of a silent no-op", async () => {
    const { c, deps } = reviseController();
    aiChat.mockResolvedValue(reply("{}"));
    validatePatch.mockResolvedValue(patch({ body: null, fields: {} }));

    await c.commitToEntry();

    expect(deps.setNotice).toHaveBeenCalledWith("The model proposed no changes to commit.");
    expect(entryBrainstorm.proposalFor("lore-1")).toBeNull();
  });

  it("reports dropped fields in the hand-off notice", async () => {
    const { c, deps } = reviseController({ entryTitle: () => "Vale" });
    aiChat.mockResolvedValue(reply("{json}"));
    validatePatch.mockResolvedValue(patch({ fields: { bio: "x" }, dropped: ["id", "score"] }));

    await c.commitToEntry();

    expect(deps.setNotice).toHaveBeenLastCalledWith(
      "Committed — review it on Vale. Ignored 2 field(s) the model couldn't set legally: id, score.",
    );
  });

  it("falls back to \"the scene\" when the target isn't in the roster", async () => {
    const { c, deps } = reviseController(); // entryTitle → null (a scene subject)
    aiChat.mockResolvedValue(reply("{json}"));
    validatePatch.mockResolvedValue(patch({ fields: { summary: "s" } }));

    await c.commitToEntry();

    expect(deps.setNotice).toHaveBeenLastCalledWith("Committed — review it on the scene.");
  });

  it("attributes the billed finalize turn's cost, and skips it when unbilled", async () => {
    const { c, deps } = reviseController();
    aiChat.mockResolvedValue(reply("{json}", 0.05));
    validatePatch.mockResolvedValue(patch({ fields: { bio: "x" } }));
    await c.commitToEntry();
    expect(deps.addTurnCost).toHaveBeenCalledWith(0.05);

    vi.mocked(deps.addTurnCost).mockClear();
    entryBrainstorm.clear("lore-1");
    aiChat.mockResolvedValue(reply("{json}", null)); // no usage returned
    await c.commitToEntry();
    expect(deps.addTurnCost).not.toHaveBeenCalled();
  });

  it("surfaces a finalize turn that returned nothing", async () => {
    const { c, deps } = reviseController();
    aiChat.mockResolvedValue({ ...reply(""), ok: false, error: "boom" } as AIChatResponse);

    await c.commitToEntry();

    expect(deps.setError).toHaveBeenCalledWith("boom");
    expect(validatePatch).not.toHaveBeenCalled();
  });
});

describe("ChatCommitController — create mode", () => {
  beforeEach(() => vi.clearAllMocks());

  function createController(over: Partial<ChatCommitDeps> = {}) {
    const made = makeController(over);
    made.c.output = { kind: "entry_patch" };
    made.c.inputDrafts = { entry_type: "lore:character" };
    return made;
  }

  it("holds a validated draft for the review card", async () => {
    const { c } = createController();
    aiChat.mockResolvedValue(reply("{json}"));
    validateDraft.mockResolvedValue(patch({ body: "a life", fields: { name: "Vale" }, dropped: ["id"] }));

    await c.commitDraft();

    expect(validateDraft).toHaveBeenCalledWith("lore:character", "{json}");
    expect(c.draftProposal).toEqual({ body: "a life", fields: { name: "Vale" } });
    expect(c.draftDropped).toEqual(["id"]);
  });

  it("notices an empty draft and holds nothing", async () => {
    const { c, deps } = createController();
    aiChat.mockResolvedValue(reply("{}"));
    validateDraft.mockResolvedValue(patch({ body: null, fields: {} }));

    await c.commitDraft();

    expect(deps.setNotice).toHaveBeenCalledWith("The model proposed no entry to create.");
    expect(c.draftProposal).toBeNull();
  });

  it("createDraft resets only when the create succeeds", async () => {
    const { c } = createController();
    c.draftProposal = { body: "a life", fields: { name: "Vale" } };

    createFromDraft.mockResolvedValueOnce(false); // e.g. a 409 — nothing created
    await c.createDraft();
    expect(c.draftProposal).not.toBeNull(); // draft survives so it isn't lost

    createFromDraft.mockResolvedValueOnce(true);
    await c.createDraft();
    expect(createFromDraft).toHaveBeenLastCalledWith("lore:character", { body: "a life", fields: { name: "Vale" } });
    expect(c.draftProposal).toBeNull(); // cleared on success
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
