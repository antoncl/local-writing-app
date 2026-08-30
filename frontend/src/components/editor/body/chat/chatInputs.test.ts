import { describe, expect, it } from "vitest";
import type { PromptEntrySummary, PromptInputDefinition } from "@/lib/types";
import {
  decodeChatInputDrafts,
  displayInputValues,
  encodeChatInputDrafts,
  endsInUserTurn,
  seedPickInput,
  seedPickInputDraft,
  seedSubjectEntryInput,
  ttlChipsFor,
} from "./chatInputs";
import { isInputMissing } from "@/lib/utils/promptInputs";

// Minimal input factory — only the fields the helpers read.
const input = (type: PromptInputDefinition["type"], extra: Partial<PromptInputDefinition> = {}): PromptInputDefinition =>
  ({ name: "x", type, ...extra }) as PromptInputDefinition;

// A prompt carrying a single `entry` input of the given type (or none).
const promptWithEntry = (type: PromptInputDefinition["type"] | null): PromptEntrySummary =>
  ({ id: "p", title: "P", inputs: type ? [{ name: "entry", type }] : [] }) as PromptEntrySummary;

const SUBJECT = { id: "plot_abc", kind: "plot" as const, title: "Rescue arc", entryType: "plot:plotline" };

// coerceChatInputValue is gone (#1482) — chat coerces through the shared
// coerceInputValue; its behavior (incl. keeping context_pick values as the
// encoded wire string) is covered in lib/utils/promptInputs.test.ts.

describe("isInputMissing", () => {
  it("scalar types: missing when blank/whitespace only", () => {
    expect(isInputMissing(input("text"), undefined)).toBe(true);
    expect(isInputMissing(input("text"), "")).toBe(true);
    expect(isInputMissing(input("text"), "   ")).toBe(true);
    expect(isInputMissing(input("text"), "hi")).toBe(false);
  });

  it("list types: missing when empty array, absent, or unparseable", () => {
    expect(isInputMissing(input("context_pick"), undefined)).toBe(true);
    expect(isInputMissing(input("context_pick"), "[]")).toBe(true);
    expect(isInputMissing(input("context_pick"), "garbage")).toBe(true);
    expect(isInputMissing(input("context_pick"), '[{"id":"a","kind":"lore"}]')).toBe(false);
    // An item without `kind` was never a real pick — the shared codec (#1482)
    // filters it, so the value reads as empty.
    expect(isInputMissing(input("context_pick"), '[{"id":"a"}]')).toBe(true);
    expect(isInputMissing(input("entity_ref_list"), "[]")).toBe(true);
    expect(isInputMissing(input("entity_ref_list"), '["a"]')).toBe(false);
  });

  it("list types: a non-array JSON value counts as missing", () => {
    expect(isInputMissing(input("context_pick"), '{"id":"a"}')).toBe(true);
  });
});

describe("seedSubjectEntryInput (#1094)", () => {
  it("context_pick target: seeds an array-shaped NodePickerRef, not a bare id", () => {
    expect(seedSubjectEntryInput(promptWithEntry("context_pick"), SUBJECT)).toEqual([
      { id: "plot_abc", kind: "plot", title: "Rescue arc", entry_type: "plot:plotline" },
    ]);
  });

  it("context_pick seed survives isInputMissing where a bare id did not", () => {
    // The bug: a bare id string made JSON.parse throw → read as missing → a
    // required plotline target failed "Missing required" on send.
    expect(isInputMissing(input("context_pick"), "plot_abc")).toBe(true);
    const seeded = seedSubjectEntryInput(promptWithEntry("context_pick"), SUBJECT);
    // The launch path persists the natural value; ChatBodyView decodes it to a
    // draft string (JSON.stringify). That draft must read as present.
    const draft = decodeChatInputDrafts({ entry: seeded }).entry;
    expect(isInputMissing(input("context_pick"), draft)).toBe(false);
  });

  it("omits entry_type from the ref when the subject has none", () => {
    const { entryType: _drop, ...noType } = SUBJECT;
    expect(seedSubjectEntryInput(promptWithEntry("context_pick"), noType)).toEqual([
      { id: "plot_abc", kind: "plot", title: "Rescue arc" },
    ]);
  });

  it("entity_ref_list target: seeds a bare-id array", () => {
    expect(seedSubjectEntryInput(promptWithEntry("entity_ref_list"), SUBJECT)).toEqual(["plot_abc"]);
  });

  it("scalar target or no `entry` input: falls back to the bare id (unchanged)", () => {
    expect(seedSubjectEntryInput(promptWithEntry("entity_ref"), SUBJECT)).toBe("plot_abc");
    expect(seedSubjectEntryInput(promptWithEntry(null), SUBJECT)).toBe("plot_abc");
  });
});

describe("seedPickInput / seedPickInputDraft — bare-id seeds erased to \"[]\" (#1485)", () => {
  // A prompt whose `as_of` input is a context_pick — impersonate's time-travel
  // anchor. The old launcher seeded a bare scene id, which the wire coercion
  // erased to "[]" → entry(…, at=[]) read the character at BOOK-START and the
  // slider was silently ignored.
  const promptWithAsOf = (type: PromptInputDefinition["type"] | null): PromptEntrySummary =>
    ({ id: "p", title: "P", inputs: type ? [{ name: "as_of", type }] : [] }) as PromptEntrySummary;
  const SCENE = { id: "scene_9", kind: "manuscript" as const, title: "scene_9", entryType: "manuscript:scene" };

  it("seeds a context_pick as_of as an array-shaped ref that survives coercion", () => {
    const seeded = seedPickInput(promptWithAsOf("context_pick"), "as_of", SCENE);
    expect(seeded).toEqual([{ id: "scene_9", kind: "manuscript", title: "scene_9", entry_type: "manuscript:scene" }]);
    const draft = decodeChatInputDrafts({ as_of: seeded }).as_of;
    expect(isInputMissing(input("context_pick"), draft)).toBe(false);
  });

  it("a scalar as_of (scene_ref) or a prompt without the input keeps the bare id", () => {
    expect(seedPickInput(promptWithAsOf("scene_ref"), "as_of", SCENE)).toBe("scene_9");
    expect(seedPickInput(promptWithAsOf(null), "as_of", SCENE)).toBe("scene_9");
  });

  it("the draft form encodes a context_pick as the wire string (the create→revise handoff)", () => {
    // Site 2: onCreated wrote a bare id into the context_pick `entry` DRAFT —
    // the tolerant reader flipped to revise mode while the send path shipped
    // "[]" and the template took the create branch. The draft seed must be the
    // encoded ref string, which BOTH readers agree on.
    const draft = seedPickInputDraft(promptWithEntry("context_pick"), "entry", SUBJECT);
    expect(typeof draft).toBe("string");
    expect(JSON.parse(draft)).toEqual([
      { id: "plot_abc", kind: "plot", title: "Rescue arc", entry_type: "plot:plotline" },
    ]);
    expect(isInputMissing(input("context_pick"), draft)).toBe(false);
  });

  it("the draft form keeps a bare id for a scalar target", () => {
    expect(seedPickInputDraft(promptWithEntry("entity_ref"), "entry", SUBJECT)).toBe("plot_abc");
  });
});

describe("chat input drafts round-trip (#654)", () => {
  it("encode is a verbatim copy of the draft strings", () => {
    const drafts = { entry: "lore_abc", entry_type: "lore:character", note: "" };
    expect(encodeChatInputDrafts(drafts)).toEqual(drafts);
  });

  it("decode(encode(x)) reproduces the drafts exactly, for every input shape", () => {
    // A bare context_pick id (a revise brainstorm's commit target), a hidden
    // launch-set entry_type, a JSON-array list draft, a number/boolean draft,
    // and an empty field — the shapes coercion would mangle.
    const drafts = {
      entry: "lore_abc", // would coerce to [] and be lost if we coerced
      entry_type: "lore:character",
      aliases: '["The Grey","Wanderer"]',
      age: "0",
      deceased: "false",
      blank: "",
    };
    expect(decodeChatInputDrafts(encodeChatInputDrafts(drafts))).toEqual(drafts);
  });

  it("decode tolerates a typed seed the launch path wrote (non-string values)", () => {
    // openChatFromPromptEntry persists the natural typed object before the first
    // ChatBodyView persist; decode JSON-encodes non-strings into draft form.
    const seeded = decodeChatInputDrafts({
      entry_type: "lore:character",
      picks: ["a", "b"],
      count: 3,
      flag: true,
    });
    expect(seeded).toEqual({
      entry_type: "lore:character",
      picks: '["a","b"]',
      count: "3",
      flag: "true",
    });
  });

  it("decode treats absent/null inputs as no drafts", () => {
    expect(decodeChatInputDrafts(undefined)).toEqual({});
    expect(decodeChatInputDrafts(null)).toEqual({});
    expect(decodeChatInputDrafts({})).toEqual({});
  });
});

describe("endsInUserTurn (#1436 — self-submittable prompt)", () => {
  it("is true when the last rendered turn is a user message", () => {
    expect(endsInUserTurn([{ role: "system" }, { role: "user" }])).toBe(true);
  });

  it("is false when the last turn is not user (system-only, or ends in assistant)", () => {
    expect(endsInUserTurn([{ role: "system" }])).toBe(false);
    expect(endsInUserTurn([{ role: "user" }, { role: "assistant" }])).toBe(false);
  });

  it("is false for an empty, null, or undefined conversation", () => {
    expect(endsInUserTurn([])).toBe(false);
    expect(endsInUserTurn(null)).toBe(false);
    expect(endsInUserTurn(undefined)).toBe(false);
  });
});

describe("ttlChipsFor", () => {
  it("returns [] for empty/absent maps", () => {
    expect(ttlChipsFor({}, 0)).toEqual([]);
    expect(ttlChipsFor(undefined as unknown as Record<string, string>, 0)).toEqual([]);
  });

  it("system slot uses the 1h TTL and formats remaining minutes", () => {
    const writtenAt = new Date(Date.now() - 60_000).toISOString(); // 1 min ago
    const [chip] = ttlChipsFor({ system: writtenAt }, 0);
    expect(chip.slot).toBe("system");
    expect(chip.label).toBe("System"); // capitalized
    expect(chip.ttlLabel).toBe("1h"); // 3600s → "1h"
    expect(chip.expired).toBe(false);
    expect(chip.formatted).toMatch(/m$/); // ~59m remaining → minutes
    // The raw number rides along so consumers never parse `formatted` back
    // (ADR-0076 S1 review) — ~59m remaining, allow scheduling slack.
    expect(chip.remainingSec).toBeGreaterThan(3500);
    expect(chip.remainingSec).toBeLessThanOrEqual(3540);
  });

  it("unknown slot defaults to 5m TTL and can expire", () => {
    const long_ago = new Date(Date.now() - 10 * 60_000).toISOString(); // 10 min ago
    const [chip] = ttlChipsFor({ lore: long_ago }, 0);
    expect(chip.ttlLabel).toBe("5m");
    expect(chip.expired).toBe(true);
    expect(chip.formatted).toBe("expired");
  });

  it("formats sub-minute remaining in seconds", () => {
    // 5m TTL slot written 4m30s ago → ~30s remaining
    const writtenAt = new Date(Date.now() - (4 * 60 + 30) * 1000).toISOString();
    const [chip] = ttlChipsFor({ lore: writtenAt }, 0);
    expect(chip.expired).toBe(false);
    expect(chip.formatted).toMatch(/^\d+s$/);
  });

  it("treats a malformed timestamp as expired (no 'NaNs' chip)", () => {
    const [chip] = ttlChipsFor({ system: "" }, 0);
    expect(chip.expired).toBe(true);
    expect(chip.formatted).toBe("expired");
  });
});

describe("displayInputValues (ADR-0076 S2 — Context door's locked-inputs section)", () => {
  const titleFor = (id: string) => (id === "lore_known" ? "Known Lore" : id === "scene_known" ? "Known Scene" : null);
  const lookup = { titleFor };

  it("skips hidden inputs", () => {
    const inputs = [input("text", { name: "secret", hidden: true }), input("text", { name: "visible" })];
    const drafts = { secret: "shh", visible: "shown" };
    expect(displayInputValues(inputs, drafts, lookup)).toEqual([{ name: "visible", label: "visible", value: "shown" }]);
  });

  it("skips empty/whitespace-only drafts", () => {
    const inputs = [input("text", { name: "a" }), input("text", { name: "b" })];
    const drafts = { a: "", b: "   " };
    expect(displayInputValues(inputs, drafts, lookup)).toEqual([]);
  });

  it("context_pick: joins ref titles, falling back to titleFor(id) then the id", () => {
    const inputs = [input("context_pick", { name: "picks" })];
    const draft = JSON.stringify([
      { id: "lore_a", kind: "lore", title: "Own Title" },
      { id: "lore_known", kind: "lore", title: "" },
      { id: "lore_unknown", kind: "lore", title: "" },
    ]);
    expect(displayInputValues(inputs, { picks: draft }, lookup)).toEqual([
      { name: "picks", label: "picks", value: "Own Title · Known Lore · lore_unknown" },
    ]);
  });

  it("context_pick: a legacy bare-id draft falls back to the raw id, titled when known (S2 review)", () => {
    // The #1094/#1482 live shape: a revise brainstorm's `entry` seeded as a
    // bare id. decodePickerValue yields [] — the row must not vanish.
    const inputs = [input("context_pick", { name: "entry" })];
    expect(displayInputValues(inputs, { entry: "lore_known" }, lookup)).toEqual([
      { name: "entry", label: "entry", value: "Known Lore" },
    ]);
    expect(displayInputValues(inputs, { entry: "lore_gone" }, lookup)).toEqual([
      { name: "entry", label: "entry", value: "lore_gone" },
    ]);
  });

  it("entity_ref_list: joins titleFor(id) ?? id, and tolerates non-JSON", () => {
    const inputs = [input("entity_ref_list", { name: "refs" })];
    expect(displayInputValues(inputs, { refs: JSON.stringify(["lore_known", "lore_x"]) }, lookup)).toEqual([
      { name: "refs", label: "refs", value: "Known Lore · lore_x" },
    ]);
    // A non-JSON list draft coerces via the shared comma-split, not verbatim.
    expect(displayInputValues(inputs, { refs: "lore_known, lore_x" }, lookup)).toEqual([
      { name: "refs", label: "refs", value: "Known Lore · lore_x" },
    ]);
  });

  it("list-shaped types (tags/multi_select) never leak the JSON wire form (S2 review)", () => {
    const inputs = [input("tags", { name: "senses" })];
    expect(displayInputValues(inputs, { senses: '["sight","sound"]' }, lookup)).toEqual([
      { name: "senses", label: "senses", value: "sight · sound" },
    ]);
  });

  it("entity_ref / scene_ref: titleFor(draft) ?? draft", () => {
    const inputs = [input("entity_ref", { name: "ref" }), input("scene_ref", { name: "scene" })];
    const drafts = { ref: "lore_known", scene: "scene_unknown" };
    expect(displayInputValues(inputs, drafts, lookup)).toEqual([
      { name: "ref", label: "ref", value: "Known Lore" },
      { name: "scene", label: "scene", value: "scene_unknown" },
    ]);
  });

  it("everything else: the draft string verbatim", () => {
    const inputs = [input("text", { name: "note" }), input("boolean", { name: "flag" })];
    const drafts = { note: "hello", flag: "true" };
    expect(displayInputValues(inputs, drafts, lookup)).toEqual([
      { name: "note", label: "note", value: "hello" },
      { name: "flag", label: "flag", value: "true" },
    ]);
  });

  it("label falls back to input.name when no label is set", () => {
    const inputs = [input("text", { name: "x", label: "Focus" }), input("text", { name: "y" })];
    const drafts = { x: "a", y: "b" };
    expect(displayInputValues(inputs, drafts, lookup)).toEqual([
      { name: "x", label: "Focus", value: "a" },
      { name: "y", label: "y", value: "b" },
    ]);
  });
});
