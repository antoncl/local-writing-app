import { describe, expect, it } from "vitest";
import { proofreadable } from "@/lib/proofread/surfaces";

describe("proofreadable", () => {
  it.each(["chat", "prompt", "snippet", "assistant", "view"] as const)("leaves %s unchecked", (kind) => {
    expect(proofreadable(kind)).toBe(false);
  });

  it.each(["manuscript", "lore", "research", "project", "structure_node", "tag"] as const)("checks %s", (kind) => {
    expect(proofreadable(kind)).toBe(true);
  });
});
