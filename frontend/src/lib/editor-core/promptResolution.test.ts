import { describe, expect, it } from "vitest";
import {
  hidePromptEntries,
  promptEntriesForSurface,
  promptEntriesOfferedOn,
  promptOffersOn,
  promptOnAccept,
  type PromptResolutionContext,
} from "@/lib/editor-core/promptResolution";
import type { MetadataSchema, PromptEntrySummary } from "@/lib/types";

function prompt(id: string, entryType: string): PromptEntrySummary {
  return { id, title: id, body: "", entry_type: entryType, metadata: {}, inputs: [] };
}

// prompt:a / prompt:b emit to append_to_body; prompt:chat routes to the chat
// panel, so the surface filter partitions them and the hidden filter removes one.
const schema = {
  entry_types: {
    "prompt:a": { prompt: { context_strategy: { output: { kind: "append_to_body" } } } },
    "prompt:b": { prompt: { context_strategy: { output: { kind: "append_to_body" } } } },
    "prompt:chat": { prompt: { context_strategy: { output: { kind: "chat_panel" } } } },
  },
} as unknown as MetadataSchema;

function ctx(over: Partial<PromptResolutionContext> = {}): PromptResolutionContext {
  return {
    metadataSchema: schema,
    promptEntries: [prompt("p-a", "prompt:a"), prompt("p-b", "prompt:b")],
    loreEntries: [],
    availableScenes: [],
    ...over,
  };
}

describe("promptOnAccept — the declared accept-time mark-stamp (#954)", () => {
  // roleplay declares the capability; a roleplay sub-type inherits it (resolved
  // schema carries it); continuation declares none.
  const onAcceptSchema = {
    entry_types: {
      "prompt:continuation": { prompt: { context_strategy: { output: { kind: "append_to_body" } } } },
      "prompt:roleplay": {
        prompt: {
          context_strategy: {
            output: { kind: "append_to_body", on_accept: { mark: "character", from_input: "character" } },
          },
        },
      },
    },
  } as unknown as MetadataSchema;
  const rpCtx = (): PromptResolutionContext => ({
    metadataSchema: onAcceptSchema,
    promptEntries: [],
    loreEntries: [],
    availableScenes: [],
  });

  it("returns the declared mark + fromInput for a prompt whose type declares on_accept", () => {
    expect(promptOnAccept(rpCtx(), prompt("p", "prompt:roleplay"))).toEqual({
      mark: "character",
      fromInput: "character",
    });
  });

  it("returns null for a prompt whose type declares no on_accept", () => {
    expect(promptOnAccept(rpCtx(), prompt("p", "prompt:continuation"))).toBeNull();
    expect(promptOnAccept(rpCtx(), null)).toBeNull();
  });
});

describe("promptEntriesForSurface — hidden filter (ADR-0049 slice 3)", () => {
  it("returns every matching prompt when nothing is hidden", () => {
    expect(promptEntriesForSurface(ctx(), "append_to_body").map((e) => e.id)).toEqual([
      "p-a",
      "p-b",
    ]);
  });

  it("drops a hidden prompt from discovery", () => {
    const ids = promptEntriesForSurface(
      ctx({ hiddenPromptIds: new Set(["p-a"]) }),
      "append_to_body",
    ).map((e) => e.id);
    expect(ids).toEqual(["p-b"]);
  });

  it("an empty hidden set changes nothing", () => {
    const ids = promptEntriesForSurface(
      ctx({ hiddenPromptIds: new Set() }),
      "append_to_body",
    ).map((e) => e.id);
    expect(ids).toEqual(["p-a", "p-b"]);
  });

  // The chat "Pick a prompt" list (ChatBodyView) routes through this seam (#682),
  // so a hidden chat_panel prompt must drop out of the chat surface too.
  it("drops a hidden prompt from the chat_panel surface", () => {
    const base = ctx({ promptEntries: [prompt("p-chat", "prompt:chat")] });
    expect(promptEntriesForSurface(base, "chat_panel").map((e) => e.id)).toEqual(["p-chat"]);
    const hidden = ctx({
      promptEntries: [prompt("p-chat", "prompt:chat")],
      hiddenPromptIds: new Set(["p-chat"]),
    });
    expect(promptEntriesForSurface(hidden, "chat_panel")).toEqual([]);
  });
});

// The shared seam every prompt-discovery surface routes through (#682) —
// promptEntriesForSurface above, plus NodePicker's snippet picker directly.
describe("hidePromptEntries (ADR-0049 #682)", () => {
  const entries = [prompt("keep", "prompt:a"), prompt("gone", "prompt:a")];

  it("removes the hidden ids", () => {
    expect(hidePromptEntries(entries, new Set(["gone"])).map((e) => e.id)).toEqual(["keep"]);
  });

  it("returns the roster unchanged for an undefined or empty set", () => {
    expect(hidePromptEntries(entries, undefined)).toBe(entries);
    expect(hidePromptEntries(entries, new Set())).toBe(entries);
  });
});

// The per-node conversation filter (ADR-0054 §4/S4): the ＋New menu shows the
// chat_panel prompts whose `offer_on` allow-list admits the open node's type, so
// a lore entry offers the lore revise prompt, a plot card the plot-card one, and
// a character both the revise prompt and impersonate. `offer_on` (where a prompt
// is offered) replaces the old inference from context_pick input targets.
describe("offer_on filter (ADR-0054 §4/S4)", () => {
  const isaSchema = {
    entry_types: {
      "lore:base": {},
      "lore:character": { parent: "lore:base" },
      "plot:base": {},
      "plot:card": { parent: "plot:base" },
      "prompt:chat": { prompt: { context_strategy: { output: { kind: "chat_panel" } } } },
      "prompt:append": { prompt: { context_strategy: { output: { kind: "append_to_body" } } } },
    },
  } as unknown as MetadataSchema;

  function isaCtx(over: Partial<PromptResolutionContext> = {}): PromptResolutionContext {
    return {
      metadataSchema: isaSchema,
      promptEntries: [],
      loreEntries: [],
      availableScenes: [],
      ...over,
    };
  }

  function offered(id: string, entryType: string, offerOn: string[]): PromptEntrySummary {
    return { id, title: id, body: "", entry_type: entryType, metadata: {}, inputs: [], offer_on: offerOn };
  }

  // Chat prompts differing only by their offer_on allow-list.
  const reviseP = offered("p-lore", "prompt:chat", ["lore:base"]);
  const cardP = offered("p-card", "prompt:chat", ["plot:card"]);
  const impersonateP = offered("p-imp", "prompt:chat", ["lore:character"]);

  describe("promptOffersOn", () => {
    it("admits a subject that is-a a declared offer_on type", () => {
      expect(promptOffersOn(isaCtx(), reviseP, "lore:character")).toBe(true); // descendant
      expect(promptOffersOn(isaCtx(), cardP, "plot:card")).toBe(true); // exact
    });

    it("rejects a subject outside the allow-list", () => {
      expect(promptOffersOn(isaCtx(), reviseP, "plot:card")).toBe(false);
      // offer_on is descendant-inclusive, not ancestor: a character prompt is
      // not offered on a bare lore:base subject.
      expect(promptOffersOn(isaCtx(), impersonateP, "lore:base")).toBe(false);
    });

    it("a prompt with no offer_on is offered nowhere (opt-in, no everywhere-match)", () => {
      const none = prompt("p-none", "prompt:chat"); // offer_on undefined
      expect(promptOffersOn(isaCtx(), none, "lore:character")).toBe(false);
    });

    it("shows nothing until the subject type resolves", () => {
      expect(promptOffersOn(isaCtx(), reviseP, "")).toBe(false);
      expect(promptOffersOn(isaCtx(), reviseP, null)).toBe(false);
    });
  });

  describe("promptEntriesOfferedOn", () => {
    it("offers the chat_panel prompts whose offer_on admits the subject", () => {
      const c = isaCtx({ promptEntries: [reviseP, cardP, impersonateP] });
      // A character card offers both the revise prompt (lore:base ⊇ character)
      // and impersonate (lore:character exact) — not the plot-card one.
      expect([...promptEntriesOfferedOn(c, "lore:character")].map((e) => e.id).sort()).toEqual([
        "p-imp",
        "p-lore",
      ]);
      expect(promptEntriesOfferedOn(c, "plot:card").map((e) => e.id)).toEqual(["p-card"]);
    });

    it("excludes a non-chat_panel prompt even when its offer_on matches (eligibility axis)", () => {
      const appendP = offered("p-app", "prompt:append", ["lore:character"]);
      const c = isaCtx({ promptEntries: [appendP, impersonateP] });
      expect(promptEntriesOfferedOn(c, "lore:character").map((e) => e.id)).toEqual(["p-imp"]);
    });
  });
});
