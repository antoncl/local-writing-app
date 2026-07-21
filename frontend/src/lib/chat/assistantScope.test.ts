import { describe, expect, it } from "vitest";
import type { AssistantEntrySummary, PromptEntrySummary } from "@/lib/types";
import {
  assistantScopeTags,
  assistantTitle,
  partitionAssistants,
  scopedDefaultAssistantId,
  topmostMatchingAssistant,
} from "@/lib/chat/assistantScope";

// Roster in manual (drag) order. "b" and "d" carry the "summary" tag.
//
// Every entry is stamped LISTED. The scope helpers range over the active roster
// only (ADR-0024 Amendment 1), and the backend stamps this pair on every
// assistant it returns — a summary without it is not a shape the API produces.
// `listed: "unlisted"` is exercised deliberately in the amendment's own tests.
const A = (id: string, title: string, tags?: unknown, listed = "listed"): AssistantEntrySummary =>
  ({
    id,
    title,
    entry_type: "assistant:assistant",
    metadata: tags === undefined ? {} : { tags },
    computed_metadata: { listed, position: 0 },
  }) as AssistantEntrySummary;

const ROSTER = [
  A("a", "Main"),
  A("b", "Summarizer", ["summary"]),
  A("c", "Coder"),
  A("d", "Recap", "summary, terse"), // CSV form
];

const prompt = (assistant_tags?: unknown): PromptEntrySummary =>
  ({ id: "p", title: "P", entry_type: "prompt:continuation", metadata: assistant_tags === undefined ? {} : { assistant_tags } }) as PromptEntrySummary;

describe("assistantScopeTags", () => {
  it("reads array and CSV forms; empty when absent", () => {
    expect(assistantScopeTags(prompt(["summary"]))).toEqual(["summary"]);
    expect(assistantScopeTags(prompt("summary, draft"))).toEqual(["summary", "draft"]);
    expect(assistantScopeTags(prompt())).toEqual([]);
    expect(assistantScopeTags(null)).toEqual([]);
  });
});

describe("partitionAssistants (soft partition)", () => {
  it("no scope → everything in rest, manual order preserved", () => {
    const { matching, rest } = partitionAssistants(ROSTER, "", []);
    expect(matching).toEqual([]);
    expect(rest.map((a) => a.id)).toEqual(["a", "b", "c", "d"]);
  });
  it("scope → matching first (manual order), rest below", () => {
    const { matching, rest } = partitionAssistants(ROSTER, "", ["summary"]);
    expect(matching.map((a) => a.id)).toEqual(["b", "d"]);
    expect(rest.map((a) => a.id)).toEqual(["a", "c"]);
  });
  it("search filters both partitions", () => {
    const { matching, rest } = partitionAssistants(ROSTER, "reca", ["summary"]);
    expect(matching.map((a) => a.id)).toEqual(["d"]);
    expect(rest).toEqual([]);
  });
});

describe("dynamic default (ADR-0024)", () => {
  it("topmost matching the scope", () => {
    expect(topmostMatchingAssistant(ROSTER, ["summary"])?.id).toBe("b");
    expect(scopedDefaultAssistantId(ROSTER, ["summary"], "a")).toBe("b");
  });
  it("falls back to topmost overall when nothing matches or no scope", () => {
    expect(scopedDefaultAssistantId(ROSTER, ["nope"], "a")).toBe("a");
    expect(scopedDefaultAssistantId(ROSTER, [], "a")).toBe("a");
  });
});

describe("assistantTitle", () => {
  it("empty selection resolves to the scoped default", () => {
    expect(assistantTitle("", ROSTER, "b")).toBe("Default (Summarizer)");
  });
  it("explicit selection shows its title", () => {
    expect(assistantTitle("c", ROSTER, "b")).toBe("Coder");
  });
});

// ADR-0024 Amendment 1 (#333): membership is a precondition on the set the
// dynamic default and the picker range over — not another fallback step.
describe("un-listed assistants are out of the picker and never the default", () => {
  const MIXED = [
    A("gone", "Aardvark", ["summary"], "unlisted"), // sorts first, tagged, un-listed
    A("keep", "Zebra", ["summary"]),
  ];

  it("a tag-scoped default skips an un-listed match", () => {
    // Pre-amendment this returned `gone`: un-listing was a way to make the app
    // START using something, since the un-listed row still sorts first.
    expect(topmostMatchingAssistant(MIXED, ["summary"])?.id).toBe("keep");
    expect(scopedDefaultAssistantId(MIXED, ["summary"], "")).toBe("keep");
  });

  it("the picker omits un-listed assistants entirely, not below a divider", () => {
    const { matching, rest } = partitionAssistants(MIXED, "", ["summary"]);
    expect(matching.map((a) => a.id)).toEqual(["keep"]);
    expect(rest).toEqual([]);
  });

  it("an emptied roster yields an empty picker rather than a guess", () => {
    const none = [A("x", "X", undefined, "unlisted")];
    expect(partitionAssistants(none, "", [])).toEqual({ matching: [], rest: [] });
    expect(scopedDefaultAssistantId(none, ["summary"], "")).toBe("");
  });
});
