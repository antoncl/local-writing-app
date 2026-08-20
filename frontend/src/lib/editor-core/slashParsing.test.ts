import { describe, it, expect } from "vitest";
import { slashCommandToken, parseSlashBody, filterSlashCommands } from "./slashParsing";

describe("slashCommandToken", () => {
  it("lowercases a single-word title so it round-trips its own label", () => {
    expect(slashCommandToken("Roleplay")).toBe("roleplay");
  });

  it("reduces a colon-bearing FQN-like title to the slash grammar's charset", () => {
    // The #1215 regression: the AI command autocompleted to entry_type, which
    // the FQN change (#77) turned into "prompt:general" — the colon is fatal.
    expect(slashCommandToken("prompt:general")).toBe("prompt-general");
  });

  it("hyphenates whitespace/punctuation runs and trims stray separators", () => {
    expect(slashCommandToken("  Continue Scene  ")).toBe("continue-scene");
    expect(slashCommandToken("Rewrite — tighten")).toBe("rewrite-tighten");
  });

  it("returns empty for a title with no usable characters (caller falls back to label)", () => {
    expect(slashCommandToken("!!!")).toBe("");
  });
});

describe("#1215: every autocomplete token parses (no stranded menu)", () => {
  // The bug: a colon in the completed token made parseSlashBody return null,
  // which closed the whole slash menu and stranded "/prompt:general " in prose.
  for (const title of ["Roleplay", "prompt:general", "Continue Scene", "Rewrite — tighten"]) {
    it(`"/${slashCommandToken(title)}" parses, alone and with args`, () => {
      const token = slashCommandToken(title);
      expect(parseSlashBody(token)).not.toBeNull();
      expect(parseSlashBody(`${token} `)).not.toBeNull();
      expect(parseSlashBody(`${token} Irene`)).not.toBeNull();
    });
  }

  it("regression guard: a raw FQN entry_type does NOT parse (the old, broken value)", () => {
    expect(parseSlashBody("prompt:general")).toBeNull();
    expect(parseSlashBody("prompt:general Irene")).toBeNull();
  });
});

describe("#1215: the completed token keeps its AI command visible in the filter", () => {
  const commands = [
    { label: "Roleplay", description: "Roleplay a character", group: "AI" },
    { label: "Continue Scene", description: "Keep writing", group: "AI" },
  ];

  it("single-word title still resolves after Tab-complete with args", () => {
    const token = slashCommandToken("Roleplay"); // "roleplay"
    const parsed = parseSlashBody(`${token} Irene`);
    expect(parsed).not.toBeNull();
    const matches = filterSlashCommands(commands, parsed!.command, parsed!.args.length > 0);
    expect(matches.map((c) => c.label)).toContain("Roleplay");
  });
});
