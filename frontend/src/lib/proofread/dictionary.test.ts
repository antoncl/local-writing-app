// Proofreading (ADR-0102 §5): the auto-dictionary — every lore name's words,
// with possessives, whatever the entry's context policy.
import { describe, expect, it } from "vitest";
import type { LoreEntrySummary } from "@/lib/types";
import { autoDictionary, nameWords, withPossessives } from "./dictionary";

const entry = (title: string, metadata: Record<string, unknown> = {}, entryType = "lore:character"): LoreEntrySummary =>
  ({ id: `lore_${title}`, title, metadata, entry_type: entryType }) as unknown as LoreEntrySummary;

const onlyCharacters = (entryType: string) => entryType === "lore:character";

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

  it("keeps a title case-sensitive and makes an alias case-insensitive", () => {
    const words = autoDictionary([entry("Skyglass", { aliases: ["Glassfire"] })]);
    expect(words).toContain("Skyglass");
    expect(words).not.toContain("skyglass");
    expect(words).not.toContain("skyglass's");
    expect(words).toContain("glassfire");
    expect(words).toContain("glassfire's");
  });

  it("also lowercases a title whose type is not a proper noun, and keeps a proper one as written", () => {
    const words = autoDictionary([entry("Katadesis", {}, "lore:note"), entry("Kael")], [], onlyCharacters);
    expect(words).toContain("Katadesis");
    expect(words).toContain("katadesis");
    expect(words).toContain("katadesis's");
    expect(words).toContain("Kael");
    expect(words).not.toContain("kael");
  });

  it("leaves aliases any-case whatever the type", () => {
    const words = autoDictionary([entry("Kael", { aliases: ["the Wren"] })], [], onlyCharacters);
    expect(words).toContain("wren");
    expect(words).not.toContain("kael");
  });

  it("settles a scene name set's title by its entry's type; an unknown id is proper", () => {
    const words = autoDictionary(
      [entry("Katadesis", {}, "lore:note"), entry("Kael")],
      [
        ["lore_Katadesis", ["Nyx"]],
        ["lore_Kael", ["Ashcombe"]],
        ["lore_unknown", ["Ghost"]],
      ],
      onlyCharacters,
    );
    expect(words).toContain("nyx");
    expect(words).toContain("Nyx");
    expect(words).toContain("Ashcombe");
    expect(words).not.toContain("ashcombe");
    expect(words).toContain("Ghost");
    expect(words).not.toContain("ghost");
  });

  it("reads a scene's name sets as title first, then aliases", () => {
    const words = autoDictionary([entry("Kael")], [["lore_Ashcombe", ["Ashcombe", "the Lady"]]]);
    expect(words).toContain("Ashcombe");
    expect(words).not.toContain("ashcombe");
    expect(words).toContain("lady");
  });

  it("deduplicates and sorts", () => {
    const words = autoDictionary([entry("Kael")], [["lore_Kael", ["Kael"]]]);
    expect(words.filter((w) => w === "Kael")).toHaveLength(1);
    expect([...words].sort()).toEqual(words);
  });
});
