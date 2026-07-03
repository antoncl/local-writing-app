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
const A = (id: string, title: string, tags?: unknown): AssistantEntrySummary =>
  ({ id, title, entry_type: "assistant:assistant", metadata: tags === undefined ? {} : { tags } }) as AssistantEntrySummary;

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
