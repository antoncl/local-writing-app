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

  it("does not ask for a scalar or an empty list", () => {
    expect(listClearPrompt("Status", "draft", labelOf)).toBeNull();
    expect(listClearPrompt("Tags", [], labelOf)).toBeNull();
    expect(listClearPrompt("Tags", undefined, labelOf)).toBeNull();
  });
});
