import { CompletionContext, type CompletionResult } from "@codemirror/autocomplete";
import { EditorState } from "@codemirror/state";
import { describe, expect, it } from "vitest";

import { makePromptCompletionSource } from "./promptCompletion";
import type { PromptInputDefinition } from "./types";

const input = (name: string): PromptInputDefinition => ({ name }) as unknown as PromptInputDefinition;

function run(doc: string, opts: { inputs?: PromptInputDefinition[]; explicit?: boolean } = {}): CompletionResult | null {
  const state = EditorState.create({ doc });
  const context = new CompletionContext(state, doc.length, opts.explicit ?? false);
  // The source is synchronous; CompletionSource's type permits a Promise, so narrow.
  return makePromptCompletionSource(() => opts.inputs ?? [])(context) as CompletionResult | null;
}

const labels = (result: CompletionResult | null): string[] => (result ? result.options.map((o) => o.label) : []);

describe("makePromptCompletionSource", () => {
  it("offers nothing outside an expression or tag", () => {
    expect(run("plain prose, not a {{ closed }} block ")).toBeNull();
  });

  it("offers variables and helpers for a bare identifier in an expression", () => {
    const result = labels(run("{{ en"));
    expect(result).toContain("entry");
    expect(result).toContain("scene");
    expect(result).toContain("use");
    // filters and tags are not offered as bare identifiers
    expect(result).not.toContain("json");
    expect(result).not.toContain("role");
  });

  it("completes declared input names after `inputs.`", () => {
    const result = run("{{ inputs.", { inputs: [input("character"), input("tone")] });
    expect(labels(result)).toEqual(["character", "tone"]);
    // replaces only the part after the dot
    expect(result?.from).toBe("{{ inputs.".length);
  });

  it("completes inputs inside entry(inputs.…) too", () => {
    expect(labels(run("{% do use(inputs.", { inputs: [input("pick")] }))).toEqual(["pick"]);
  });

  it("offers tag names while the tag keyword is being typed", () => {
    const result = labels(run("{% ro"));
    expect(result).toContain("role");
    expect(result).toContain("do");
    expect(result).toContain("include");
  });

  it("offers the role values inside {% role %}, not the whole vocabulary", () => {
    const result = labels(run("{% role ", { explicit: true }));
    expect(result).toEqual(['"system"', '"user"', '"assistant"']);
    expect(result).not.toContain("entry");
  });

  it("replaces from the opening quote when a role value is being typed", () => {
    const result = run('{% role "us');
    expect(labels(result)).toContain('"user"');
    // replaces the `"us` the author started, rather than appending
    expect(result?.from).toBe("{% role ".length);
  });

  it("completes an expression inside {% do %} (it wraps an expression)", () => {
    const result = labels(run("{% do us"));
    expect(result).toContain("use");
    expect(result).toContain("entry");
  });

  it("offers nothing manifest-driven in a non-expression tag argument", () => {
    expect(run("{% include ", { explicit: true })).toBeNull();
  });

  it("offers filters after a pipe", () => {
    expect(labels(run("{{ value | js"))).toContain("json");
  });

  it("declines member access (schema field names are a follow-up)", () => {
    expect(run("{{ scene.")).toBeNull();
    expect(run("{{ entry(x).ho")).toBeNull();
  });

  it("stays quiet at an empty expression position unless explicitly invoked", () => {
    expect(run("{{ ")).toBeNull();
    expect(labels(run("{{ ", { explicit: true }))).toContain("entry");
  });
});
