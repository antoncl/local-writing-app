// Proofreading (ADR-0102 §5): the auto-dictionary — every lore name's words,
// with possessives, whatever the entry's context policy.
import { describe, expect, it } from "vitest";
import type { LoreEntrySummary } from "@/lib/types";
import { autoDictionary, nameWords, withPossessives } from "./dictionary";

const entry = (title: string, metadata: Record<string, unknown> = {}): LoreEntrySummary =>
  ({ id: `lore_${title}`, title, metadata, entry_type: "lore:character" }) as unknown as LoreEntrySummary;

describe("nameWords", () => {
  it("splits on spaces and hyphens and trims edge punctuation, keeping inner apostrophes", () => {
    expect(nameWords("Dr. Kael Vashti-Orr")).toEqual(["Dr", "Kael", "Vashti", "Orr"]);
    expect(nameWords("O'Brien")).toEqual(["O'Brien"]);
    expect(nameWords("  — 7 ")).toEqual([]);
  });
});

describe("withPossessives", () => {
  it("adds 's with both apostrophes", () => {
    expect(withPossessives("Kael")).toEqual(["Kael", "Kael's", "Kael’s"]);
  });

  it("adds the bare apostrophe after a final s", () => {
    expect(withPossessives("Ares")).toEqual(["Ares", "Ares's", "Ares’s", "Ares'", "Ares’"]);
  });
});

describe("autoDictionary", () => {
  it("takes titles and aliases, including entries kept out of context", () => {
    const words = autoDictionary([
      entry("Kael", { aliases: ["the Wren"] }),
      entry("Skyglass", { context_policy: "never" }),
    ]);
    expect(words).toContain("Kael");
    expect(words).toContain("Wren’s");
    expect(words).toContain("Skyglass's");
  });

  it("adds a scene's as-of-scene names, deduplicated and sorted", () => {
    const words = autoDictionary([entry("Kael")], ["Kael", "Ashcombe"]);
    expect(words.filter((w) => w === "Kael")).toHaveLength(1);
    expect(words).toContain("Ashcombe");
    expect([...words].sort()).toEqual(words);
  });
});
