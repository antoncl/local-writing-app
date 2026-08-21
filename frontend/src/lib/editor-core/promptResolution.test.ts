import { describe, expect, it } from "vitest";
import {
  dependencyAdvisoryText,
  hidePromptEntries,
  inheritedInputsFrom,
  promptEntriesForSurface,
  promptEntriesOfferedOn,
  promptOffersOn,
  promptOnAccept,
  resolvePromptPositionalArgs,
  type PromptResolutionContext,
} from "@/lib/editor-core/promptResolution";
import type {
  LoreEntrySummary,
  MetadataSchema,
  PromptContextStrategy,
  PromptEntrySummary,
  PromptInputDefinition,
} from "@/lib/types";

// ADR-0065 S3: invocability + surface are the INSTANCE's own `context_strategy`,
// never a schema-type lookup — so a fixture prompt carries its strategy directly.
function prompt(
  id: string,
  entryType: string,
  contextStrategy?: PromptContextStrategy | null,
): PromptEntrySummary {
  return {
    id,
    title: id,
    body: "",
    entry_type: entryType,
    metadata: {},
    inputs: [],
    context_strategy: contextStrategy ?? null,
  };
}

// A placeholder, non-null schema — `metadataSchema` only gates filterPromptRoster's
// "no schema yet" short-circuit here; surface/invocability no longer reads it.
const schema = { entry_types: {}, fields: {} } as unknown as MetadataSchema;

function ctx(over: Partial<PromptResolutionContext> = {}): PromptResolutionContext {
  return {
    metadataSchema: schema,
    promptEntries: [
      prompt("p-a", "prompt:general", { output: { handler: "inline" } }),
      prompt("p-b", "prompt:general", { output: { handler: "inline" } }),
    ],
    loreEntries: [],
    availableScenes: [],
    ...over,
  };
}

describe("promptOnAccept — the declared accept-time mark-stamp (#954)", () => {
  // roleplay declares the capability on its own instance; a plain inline prompt
  // (was "continuation") declares none.
  it("returns the declared mark + fromInput for a prompt whose instance declares on_accept", () => {
    const roleplay = prompt("p", "prompt:general", {
      output: { handler: "inline", on_accept: { mark: "character", from_input: "character" } },
    });
    expect(promptOnAccept(ctx(), roleplay)).toEqual({
      mark: "character",
      fromInput: "character",
    });
  });

  it("returns null for a prompt whose instance declares no on_accept", () => {
    const plainInline = prompt("p", "prompt:general", { output: { handler: "inline" } });
    expect(promptOnAccept(ctx(), plainInline)).toBeNull();
    expect(promptOnAccept(ctx(), null)).toBeNull();
  });
});

describe("promptEntriesForSurface — hidden filter (ADR-0049 slice 3)", () => {
  it("returns every matching prompt when nothing is hidden", () => {
    expect(promptEntriesForSurface(ctx(), "cursor").map((e) => e.id)).toEqual([
      "p-a",
      "p-b",
    ]);
  });

  it("drops a hidden prompt from discovery", () => {
    const ids = promptEntriesForSurface(
      ctx({ hiddenPromptIds: new Set(["p-a"]) }),
      "cursor",
    ).map((e) => e.id);
    expect(ids).toEqual(["p-b"]);
  });

  it("an empty hidden set changes nothing", () => {
    const ids = promptEntriesForSurface(
      ctx({ hiddenPromptIds: new Set() }),
      "cursor",
    ).map((e) => e.id);
    expect(ids).toEqual(["p-a", "p-b"]);
  });

  // The chat "Pick a prompt" list (ChatBodyView) routes through this seam (#682),
  // so a hidden conversation prompt must drop out of the conversation surface too.
  it("drops a hidden prompt from the conversation surface", () => {
    const base = ctx({ promptEntries: [prompt("p-chat", "prompt:chat")] });
    expect(promptEntriesForSurface(base, "conversation").map((e) => e.id)).toEqual(["p-chat"]);
    const hidden = ctx({
      promptEntries: [prompt("p-chat", "prompt:chat")],
      hiddenPromptIds: new Set(["p-chat"]),
    });
    expect(promptEntriesForSurface(hidden, "conversation")).toEqual([]);
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
// conversation prompts whose `offer_on` allow-list admits the open node's type, so
// a lore entry offers the lore revise prompt, a plot card the plot-card one, and
// a character both the revise prompt and impersonate. `offer_on` (where a prompt
// is offered) replaces the old inference from context_pick input targets.
describe("offer_on filter (ADR-0054 §4/S4)", () => {
  // Only the SUBJECT types need ancestry here (entryTypeIsA walks these) — the
  // prompts' own invocation surface is now instance-driven (ADR-0065 S3), set
  // directly on each `offered()` fixture below.
  const isaSchema = {
    entry_types: {
      "lore:base": {},
      "lore:character": { parent: "lore:base" },
      "plot:base": {},
      "plot:card": { parent: "plot:base" },
      "plot:plotline": { parent: "plot:base" },
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

  function offered(
    id: string,
    entryType: string,
    offerOn: string[],
    contextStrategy?: PromptContextStrategy | null,
  ): PromptEntrySummary {
    return {
      id,
      title: id,
      body: "",
      entry_type: entryType,
      metadata: {},
      inputs: [],
      offer_on: offerOn,
      context_strategy: contextStrategy ?? null,
    };
  }

  // Chat prompts differing only by their offer_on allow-list.
  const reviseP = offered("p-lore", "prompt:chat", ["lore:base"]);
  const cardP = offered("p-card", "prompt:chat", ["plot:card"]);
  const plotlineP = offered("p-plotline", "prompt:chat", ["plot:plotline"]);
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
    it("offers the conversation prompts whose offer_on admits the subject", () => {
      const c = isaCtx({ promptEntries: [reviseP, cardP, impersonateP] });
      // A character card offers both the revise prompt (lore:base ⊇ character)
      // and impersonate (lore:character exact) — not the plot-card one.
      expect([...promptEntriesOfferedOn(c, "lore:character")].map((e) => e.id).sort()).toEqual([
        "p-imp",
        "p-lore",
      ]);
      expect(promptEntriesOfferedOn(c, "plot:card").map((e) => e.id)).toEqual(["p-card"]);
    });

    it("offers the plotline prompt on a plotline subject, not the card one (S7b)", () => {
      const c = isaCtx({ promptEntries: [cardP, plotlineP] });
      // revise-plotline is offered on plot:plotline; the plot-card prompt is not.
      expect(promptEntriesOfferedOn(c, "plot:plotline").map((e) => e.id)).toEqual(["p-plotline"]);
      expect(promptEntriesOfferedOn(c, "plot:card").map((e) => e.id)).toEqual(["p-card"]);
    });

    it("excludes an inline (non-conversation) prompt even when its offer_on matches (eligibility axis)", () => {
      const appendP = offered("p-app", "prompt:general", ["lore:character"], {
        output: { handler: "inline" },
      });
      const c = isaCtx({ promptEntries: [appendP, impersonateP] });
      expect(promptEntriesOfferedOn(c, "lore:character").map((e) => e.id)).toEqual(["p-imp"]);
    });
  });
});

describe("dependencyAdvisoryText — the snippet dependency alert line (ADR-0061 §5)", () => {
  it("names both counts, pluralized", () => {
    expect(dependencyAdvisoryText({ prompt_count: 2, chat_count: 3 })).toBe("2 prompts / 3 chats");
  });

  it("uses the singular for a count of one", () => {
    expect(dependencyAdvisoryText({ prompt_count: 1, chat_count: 1 })).toBe("1 prompt / 1 chat");
  });

  it("omits a zero half rather than saying '0 chats'", () => {
    expect(dependencyAdvisoryText({ prompt_count: 2, chat_count: 0 })).toBe("2 prompts");
    expect(dependencyAdvisoryText({ prompt_count: 0, chat_count: 4 })).toBe("4 chats");
  });

  it("is empty when there are no dependents, so the editor renders no note", () => {
    expect(dependencyAdvisoryText({ prompt_count: 0, chat_count: 0 })).toBe("");
    expect(dependencyAdvisoryText(null)).toBe("");
    expect(dependencyAdvisoryText(undefined)).toBe("");
  });
});

describe("resolvePromptPositionalArgs — slash positional args (#1276)", () => {
  // A roleplay-style prompt: one required context_pick input targeting lore
  // characters. `target` is the NodePickerConfig `{ sources }` shape the runtime
  // picker filters on (typed loosely on the input, cast at the read seam).
  const characterInput = {
    name: "character",
    type: "context_pick",
    required: true,
    target: { sources: [{ kind: "lore", expr: { type: "lore:character" } }] },
  } as unknown as PromptInputDefinition;

  const roleplay = (): PromptEntrySummary => ({
    ...prompt("rp", "prompt:general", { output: { handler: "inline" } }),
    inputs: [characterInput],
  });

  const lore = (id: string, title: string, entryType: string): LoreEntrySummary => ({
    id,
    title,
    body: "",
    entry_type: entryType,
    metadata: {},
  });

  it("resolves an unquoted multi-word name — the sole input absorbs both tokens", () => {
    const c = ctx({ loreEntries: [lore("lore_1", "Annie Oakley", "lore:character")] });
    const res = resolvePromptPositionalArgs(c, roleplay(), ["Annie", "Oakley"]);
    expect(res.satisfied).toBe(true);
    expect(res.unresolved).toEqual([]);
    expect(JSON.parse(res.inputs!.character as string)).toEqual([
      { id: "lore_1", kind: "lore", title: "Annie Oakley", entry_type: "lore:character" },
    ]);
  });

  it("still resolves a single-token name", () => {
    const c = ctx({ loreEntries: [lore("lore_2", "Bob", "lore:character")] });
    expect(resolvePromptPositionalArgs(c, roleplay(), ["Bob"]).satisfied).toBe(true);
  });

  it("gates by the target entry_type — a same-named non-character lore entry does not match (#1276 dead gating)", () => {
    const c = ctx({ loreEntries: [lore("loc_1", "Annie Oakley", "lore:location")] });
    const res = resolvePromptPositionalArgs(c, roleplay(), ["Annie", "Oakley"]);
    expect(res.satisfied).toBe(false);
    expect(res.unresolved.map((u) => u.token)).toEqual(["Annie Oakley"]);
  });

  it("disambiguates two same-named entries by the target entry_type", () => {
    const c = ctx({
      loreEntries: [
        lore("loc_1", "Annie Oakley", "lore:location"),
        lore("char_1", "Annie Oakley", "lore:character"),
      ],
    });
    const res = resolvePromptPositionalArgs(c, roleplay(), ["Annie", "Oakley"]);
    expect(res.satisfied).toBe(true);
    expect(JSON.parse(res.inputs!.character as string)[0].id).toBe("char_1");
  });

  it("maps earlier slots 1:1 and only a final context_pick input absorbs the rest", () => {
    const twoInput = {
      ...roleplay(),
      inputs: [{ name: "tone", type: "text", required: false }, characterInput],
    } as unknown as PromptEntrySummary;
    const c = ctx({ loreEntries: [lore("char_1", "Annie Oakley", "lore:character")] });
    const res = resolvePromptPositionalArgs(c, twoInput, ["gruff", "Annie", "Oakley"]);
    expect(res.satisfied).toBe(true);
    expect(res.inputs!.tone).toBe("gruff");
    expect(JSON.parse(res.inputs!.character as string)[0].id).toBe("char_1");
  });

  it("a final scalar input does NOT absorb trailing tokens (takes one, ignores extra)", () => {
    const numPrompt = {
      ...prompt("np", "prompt:general", { output: { handler: "inline" } }),
      inputs: [{ name: "count", type: "number", required: true }],
    } as unknown as PromptEntrySummary;
    const res = resolvePromptPositionalArgs(ctx(), numPrompt, ["5", "6"]);
    // Joining would make "5 6" → invalid number → unresolved; single-token wins.
    expect(res.satisfied).toBe(true);
    expect(res.unresolved).toEqual([]);
  });
});

describe("inheritedInputsFrom — the editor's inherited tier (ADR-0061 S3b)", () => {
  const roster: PromptEntrySummary[] = [
    { id: "villain", title: "Villain Voice", body: "", entry_type: "prompt:snippet", metadata: {}, inputs: [] },
  ];
  const menace: PromptInputDefinition = { name: "menace", type: "select" };
  const subject: PromptInputDefinition = { name: "subject", type: "text" };

  it("keeps only snippet-contributed inputs, tagged with the source title", () => {
    const result = inheritedInputsFrom([subject, menace], { menace: "villain" }, roster);
    // `subject` is own (absent from provenance) → excluded; `menace` is inherited.
    expect(result).toEqual([
      { definition: menace, sourceId: "villain", sourceTitle: "Villain Voice" },
    ]);
  });

  it("falls back to the raw id when the source is not in the roster", () => {
    const result = inheritedInputsFrom([menace], { menace: "ghost" }, roster);
    expect(result[0].sourceTitle).toBe("ghost");
  });

  it("is empty when nothing is inherited", () => {
    expect(inheritedInputsFrom([subject], {}, roster)).toEqual([]);
  });
});
