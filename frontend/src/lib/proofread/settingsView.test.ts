import { describe, expect, it } from "vitest";
import type { RuleGroup } from "./findings";
import { changedRuleNames, filterGroups, inheritedDialect, inheritedRule } from "./settingsView";
import type { ProofreadingLayer, ProofreadingSetup } from "@/lib/types";

const layer = (id: string, label: string, own: Partial<ProofreadingLayer> = {}): ProofreadingLayer => ({
  id,
  label,
  is_machine: id === "machine",
  is_library: id === "lib",
  is_root: id === "book",
  words: [],
  rules: {},
  dialect: null,
  ...own,
});

function setupOf(layers: ProofreadingLayer[]): ProofreadingSetup {
  return { words: [], word_layers: {}, rules: {}, rule_layers: {}, dialect: "american", layers, ignored: {} };
}

describe("inheritedRule", () => {
  it("is Harper's default when no layer before sets the rule", () => {
    const setup = setupOf([layer("lib", "Library"), layer("machine", "Machine"), layer("book", "Book 1")]);
    expect(inheritedRule(setup, "book", "Hedging", true)).toEqual({ value: true, from: "Harper's default" });
  });

  it("takes the nearest layer before the selected one, and says who", () => {
    const setup = setupOf([
      layer("lib", "Library", { rules: { Hedging: false } }),
      layer("machine", "Machine", { rules: { Hedging: true } }),
      layer("book", "Book 1"),
    ]);
    expect(inheritedRule(setup, "book", "Hedging", false)).toEqual({ value: true, from: "Machine" });
    expect(inheritedRule(setup, "machine", "Hedging", true)).toEqual({ value: false, from: "Library" });
  });

  it("is not affected by a layer nearer than the selected one", () => {
    const setup = setupOf([
      layer("lib", "Library", { rules: { Hedging: false } }),
      layer("machine", "Machine"),
      layer("book", "Book 1", { rules: { Hedging: true } }),
    ]);
    expect(inheritedRule(setup, "machine", "Hedging", true)).toEqual({ value: false, from: "Library" });
  });

  it("the Library inherits nothing but Harper's default", () => {
    const setup = setupOf([layer("lib", "Library", { rules: { Hedging: false } }), layer("machine", "Machine")]);
    expect(inheritedRule(setup, "lib", "Hedging", true)).toEqual({ value: true, from: "Harper's default" });
  });
});

describe("inheritedDialect", () => {
  it("is American, Harper's default, when no outer layer sets one", () => {
    const setup = setupOf([layer("lib", "Library"), layer("book", "Book 1", { dialect: "british" })]);
    expect(inheritedDialect(setup, "book")).toEqual({ dialect: "american", from: "Harper's default" });
  });

  it("takes the nearest outer layer's dialect", () => {
    const setup = setupOf([
      layer("lib", "Library", { dialect: "canadian" }),
      layer("machine", "Machine", { dialect: "british" }),
      layer("book", "Book 1"),
    ]);
    expect(inheritedDialect(setup, "book")).toEqual({ dialect: "british", from: "Machine" });
  });
});

describe("changedRuleNames", () => {
  it("is the union of every layer's rules", () => {
    const setup = setupOf([
      layer("lib", "Library", { rules: { A: false } }),
      layer("machine", "Machine", { rules: { B: true } }),
      layer("book", "Book 1", { rules: { A: true } }),
    ]);
    expect([...changedRuleNames(setup)].sort()).toEqual(["A", "B"]);
  });
});

describe("filterGroups", () => {
  const rule = (name: string, label: string, description = "") => ({ name, label, description, default: true });
  const groups: RuleGroup[] = [
    { label: "Style", description: "", rules: [rule("OxfordComma", "Oxford comma", "Use the serial comma"), rule("Hedging", "Hedging")] },
    { label: "Spelling", description: "", rules: [rule("SpellCheck", "Spell check")] },
  ];

  it("returns every group untouched without a query or the changed filter", () => {
    expect(filterGroups(groups, "  ", false, new Set())).toBe(groups);
  });

  it("matches label, name and description in any case, and drops empty groups", () => {
    expect(filterGroups(groups, "SERIAL", false, new Set()).map((g) => g.rules.map((r) => r.name))).toEqual([["OxfordComma"]]);
    expect(filterGroups(groups, "spellcheck", false, new Set()).map((g) => g.label)).toEqual(["Spelling"]);
    expect(filterGroups(groups, "nothing", false, new Set())).toEqual([]);
  });

  it("changed-only keeps just the rules some layer sets", () => {
    const out = filterGroups(groups, "", true, new Set(["Hedging"]));
    expect(out).toEqual([{ label: "Style", description: "", rules: [rule("Hedging", "Hedging")] }]);
  });
});
