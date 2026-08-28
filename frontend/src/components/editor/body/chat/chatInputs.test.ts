import { describe, expect, it } from "vitest";
import type { PromptEntrySummary, PromptInputDefinition } from "@/lib/types";
import {
  decodeChatInputDrafts,
  encodeChatInputDrafts,
  endsInUserTurn,
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
