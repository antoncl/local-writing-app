import { describe, expect, it } from "vitest";
import type { PromptInputDefinition } from "@/lib/types";
import { coerceChatInputValue, isInputMissing, ttlChipsFor } from "./chatInputs";

// Minimal input factory — only the fields the helpers read.
const input = (type: PromptInputDefinition["type"], extra: Partial<PromptInputDefinition> = {}): PromptInputDefinition =>
  ({ name: "x", type, ...extra }) as PromptInputDefinition;

describe("coerceChatInputValue", () => {
  it("trims plain text", () => {
    expect(coerceChatInputValue("  hi  ", "text")).toBe("hi");
  });

  it("number: parses finite, null on empty, keeps unparseable as trimmed string", () => {
    expect(coerceChatInputValue("42", "number")).toBe(42);
    expect(coerceChatInputValue("  3.5 ", "number")).toBe(3.5);
    expect(coerceChatInputValue("", "number")).toBeNull();
    expect(coerceChatInputValue("   ", "number")).toBeNull();
    expect(coerceChatInputValue("abc", "number")).toBe("abc");
  });

  it("boolean: only literal 'true' (case-insensitive) is true", () => {
    expect(coerceChatInputValue("true", "boolean")).toBe(true);
    expect(coerceChatInputValue(" TRUE ", "boolean")).toBe(true);
    expect(coerceChatInputValue("false", "boolean")).toBe(false);
    expect(coerceChatInputValue("", "boolean")).toBe(false);
    expect(coerceChatInputValue("yes", "boolean")).toBe(false);
  });

  it("context_pick: empty → [], valid array passes through, junk → []", () => {
    expect(coerceChatInputValue("", "context_pick")).toEqual([]);
    expect(coerceChatInputValue('[{"id":"a"}]', "context_pick")).toEqual([{ id: "a" }]);
    expect(coerceChatInputValue("not json", "context_pick")).toEqual([]);
    expect(coerceChatInputValue('{"id":"a"}', "context_pick")).toEqual([]);
  });

  it("entity_ref_list: empty → null, valid array passes through, junk → null", () => {
    expect(coerceChatInputValue("", "entity_ref_list")).toBeNull();
    expect(coerceChatInputValue('["a","b"]', "entity_ref_list")).toEqual(["a", "b"]);
    expect(coerceChatInputValue("nope", "entity_ref_list")).toBeNull();
    expect(coerceChatInputValue('{"id":"a"}', "entity_ref_list")).toBeNull();
  });
});

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
    expect(isInputMissing(input("context_pick"), '[{"id":"a"}]')).toBe(false);
    expect(isInputMissing(input("entity_ref_list"), "[]")).toBe(true);
    expect(isInputMissing(input("entity_ref_list"), '["a"]')).toBe(false);
  });

  it("list types: a non-array JSON value counts as missing", () => {
    expect(isInputMissing(input("context_pick"), '{"id":"a"}')).toBe(true);
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
