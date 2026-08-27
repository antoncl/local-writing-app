import { describe, expect, it } from "vitest";
import {
  isSearchActive,
  matchesEntry,
  parseSearchQuery,
  readAliases,
  readTags,
} from "./entrySearch";

describe("parseSearchQuery (#1468)", () => {
  it("treats a leading # as the tag-restrictor", () => {
    expect(parseSearchQuery("#heist")).toEqual({ needle: "heist", tagOnly: true });
  });
  it("lower-cases and trims", () => {
    expect(parseSearchQuery("  #Heist  ")).toEqual({ needle: "heist", tagOnly: true });
    expect(parseSearchQuery("  Mara  ")).toEqual({ needle: "mara", tagOnly: false });
  });
  it("a bare # is tagOnly with an empty needle", () => {
    expect(parseSearchQuery("#")).toEqual({ needle: "", tagOnly: true });
  });
  it("empty / nullish → inactive plain query", () => {
    expect(parseSearchQuery("")).toEqual({ needle: "", tagOnly: false });
    expect(parseSearchQuery(null)).toEqual({ needle: "", tagOnly: false });
  });
});

describe("isSearchActive", () => {
  it("is false for blank, true once anything (even #) is typed", () => {
    expect(isSearchActive("")).toBe(false);
    expect(isSearchActive("   ")).toBe(false);
    expect(isSearchActive("#")).toBe(true);
    expect(isSearchActive("a")).toBe(true);
  });
});

describe("readTags / readAliases", () => {
  it("reads a tags array", () => {
    expect(readTags({ tags: ["heist", " thread "] })).toEqual(["heist", "thread"]);
  });
  it("reads a comma-joined tag string", () => {
    expect(readTags({ tags: "heist, thread ,," })).toEqual(["heist", "thread"]);
  });
  it("returns [] for missing/odd tags", () => {
    expect(readTags({})).toEqual([]);
    expect(readTags(null)).toEqual([]);
    expect(readTags({ tags: 42 })).toEqual([]);
  });
  it("reads aliases only from an array", () => {
    expect(readAliases({ aliases: ["the counter", " "] })).toEqual(["the counter"]);
    expect(readAliases({ aliases: "not-an-array" })).toEqual([]);
    expect(readAliases({})).toEqual([]);
  });
});

describe("matchesEntry", () => {
  const parse = parseSearchQuery;
  it("empty needle matches everything", () => {
    expect(matchesEntry({ title: "anything" }, parse(""))).toBe(true);
  });
  it("plain query matches title, tags, or aliases", () => {
    const fields = { title: "Mara Voss", tags: ["heist"], aliases: ["the counter"] };
    expect(matchesEntry(fields, parse("mara"))).toBe(true); // title
    expect(matchesEntry(fields, parse("heist"))).toBe(true); // tag
    expect(matchesEntry(fields, parse("counter"))).toBe(true); // alias
    expect(matchesEntry(fields, parse("dragon"))).toBe(false);
  });
  it("#query restricts to tags — title/alias hits do not count", () => {
    const fields = { title: "Heist Master", tags: ["thread"], aliases: ["heist"] };
    expect(matchesEntry(fields, parse("#heist"))).toBe(false); // title+alias have it, tags don't
    expect(matchesEntry(fields, parse("#thread"))).toBe(true); // tag match
  });
  it("missing tag/alias fields are treated as empty, not a crash", () => {
    expect(matchesEntry({ title: "Solo" }, parse("solo"))).toBe(true);
    expect(matchesEntry({ title: "Solo" }, parse("#x"))).toBe(false);
  });
});
