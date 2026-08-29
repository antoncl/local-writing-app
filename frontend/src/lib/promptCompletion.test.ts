import { CompletionContext, type CompletionResult } from "@codemirror/autocomplete";
import { EditorState } from "@codemirror/state";
import { describe, expect, it, vi } from "vitest";

import { makePromptCompletionSource } from "./promptCompletion";
import type { MetadataSchema, PromptInputDefinition } from "./types";

// `entry(inputs.x)` resolution goes through pickerMembership; mock it so the test
// controls which entry_type(s) an input's target declares.
const hoisted = vi.hoisted(() => ({ entryTypes: {} as Record<string, string[]> }));
vi.mock("@/lib/utils/pickerSources", () => ({
  pickerMembership: () => ({ kinds: [], entryTypes: hoisted.entryTypes }),
}));

const SCHEMA = {
  version: 1,
  entry_types: {
    "manuscript:scene": { fields: ["summary", "pov", "internal"] },
    "project:project": { fields: ["spelling"] },
    "lore:character": { fields: ["goal", "secret"] },
  },
  fields: {
    summary: { name: "Summary", type: "text" },
    pov: { name: "POV", type: "entity_ref", picker_config: {} },
    internal: { name: "Internal", type: "text", hidden: true },
    spelling: { name: "Spelling", type: "text" },
    goal: { name: "Goal", type: "text" },
    secret: { name: "Secret", type: "computed" },
  },
} as unknown as MetadataSchema;

const input = (name: string, target?: unknown): PromptInputDefinition =>
  ({ name, target: target ?? null }) as unknown as PromptInputDefinition;

function run(
  doc: string,
  opts: { inputs?: PromptInputDefinition[]; explicit?: boolean; schema?: MetadataSchema | null } = {},
): CompletionResult | null {
  const state = EditorState.create({ doc });
  const context = new CompletionContext(state, doc.length, opts.explicit ?? false);
  const schema = opts.schema === undefined ? SCHEMA : opts.schema;
  // The source is synchronous; CompletionSource's type permits a Promise, so narrow.
  return makePromptCompletionSource(() => opts.inputs ?? [], () => schema)(context) as CompletionResult | null;
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

  it("completes an expression inside control-flow tags (if / for / set)", () => {
    expect(labels(run("{% if sc"))).toContain("scene");
    expect(labels(run("{% for x in fu"))).toContain("full_outline");
    expect(labels(run("{% set y = en"))).toContain("entry");
  });

  it("offers filters after a pipe", () => {
    expect(labels(run("{{ value | js"))).toContain("json");
  });

  it("completes scene fields (plus intrinsics), filtering hidden and computed", () => {
    const result = labels(run("{{ scene."));
    expect(result).toContain("summary");
    expect(result).toContain("pov");
    expect(result).not.toContain("internal"); // hidden
    expect(result).toContain("title"); // intrinsic
    expect(result).toContain("body");
    expect(run("{{ scene.")?.from).toBe("{{ scene.".length);
  });

  it("completes project fields after project.", () => {
    expect(labels(run("{{ project."))).toContain("spelling");
  });

  it("resolves entry(inputs.x) fields via the input's declared target type", () => {
    hoisted.entryTypes = { lore: ["lore:character"] };
    const result = labels(run("{{ entry(inputs.hero).", { inputs: [input("hero", {})] }));
    expect(result).toContain("goal");
    expect(result).not.toContain("secret"); // computed
    expect(result).toContain("title"); // intrinsic
  });

  it("follows an entity_ref hop — scene.pov.<field> offers the target's fields (#1294)", () => {
    hoisted.entryTypes = { lore: ["lore:character"] };
    const result = labels(run("{{ scene.pov."));
    expect(result).toContain("goal"); // a character field
    expect(result).not.toContain("secret"); // computed, filtered
    expect(result).toContain("title"); // the target's intrinsic
    expect(result).not.toContain("summary"); // NOT the scene's own fields
    expect(run("{{ scene.pov.")?.from).toBe("{{ scene.pov.".length);
  });

  it("declines member access it cannot resolve to a single type", () => {
    hoisted.entryTypes = { lore: ["lore:character", "lore:place"] };
    expect(run("{{ entry(inputs.hero).", { inputs: [input("hero", {})] })).toBeNull(); // ambiguous
    expect(run("{{ entry(inputs.hero).", { inputs: [input("hero")] })).toBeNull(); // untyped input
    expect(run('{{ entry("honor").ho')).toBeNull(); // literal id — needs the node index
    expect(run("{{ scene.pov.ti")).toBeNull(); // ambiguous ref hop (two target types)
    expect(run("{{ scene.summary.x")).toBeNull(); // hop through a non-ref (text) field
    expect(run("{{ foo.bar")).toBeNull(); // unknown base
    expect(run("{{ scene.", { schema: null })).toBeNull(); // no schema loaded
  });

  it("stays quiet at an empty expression position unless explicitly invoked", () => {
    expect(run("{{ ")).toBeNull();
    expect(labels(run("{{ ", { explicit: true }))).toContain("entry");
  });
});
