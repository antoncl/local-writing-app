// #2437: the reset gesture on a non-empty list field always asks first.
import { describe, expect, it } from "vitest";
import { listClearPrompt } from "./listClearConfirm";

const titles: Record<string, string> = { tag_a: "Mara", tag_b: "Backstory" };
const labelOf = (id: string) => titles[id] ?? null;

describe("listClearPrompt", () => {
  it("asks before clearing a non-empty list, naming every member", () => {
    expect(listClearPrompt("Tags", ["tag_a", "tag_b", "raw"], labelOf)).toEqual({
      title: "Clear Tags",
      message: "Remove all 3 values from Tags?",
      details: ["Mara", "Backstory", "raw"],
    });
  });

  it("asks for a single-member list too", () => {
    expect(listClearPrompt("Tags", ["tag_a"], labelOf)?.message).toBe("Remove 1 value from Tags?");
  });

  it("says 'replace with inherited' when the clear reverts a cascade override", () => {
    expect(listClearPrompt("Tags", ["tag_a", "tag_b"], labelOf, true)).toEqual({
      title: "Reset Tags",
      message: "Replace the 2 values set here with the inherited Tags?",
      details: ["Mara", "Backstory"],
    });
  });

  it("caps the listed members", () => {
    const many = Array.from({ length: 13 }, (_, i) => `m${i}`);
    const details = listClearPrompt("Kin", many, labelOf)!.details;
    expect(details).toHaveLength(11);
    expect(details.at(-1)).toBe("…and 3 more");
  });

  it("does not ask for a scalar or an empty list", () => {
    expect(listClearPrompt("Status", "draft", labelOf)).toBeNull();
    expect(listClearPrompt("Tags", [], labelOf)).toBeNull();
    expect(listClearPrompt("Tags", undefined, labelOf)).toBeNull();
  });
});
