// mergeStructuredFields — the ADR-0077 §4/§5 field-level three-way merge for a
// document's structured (non-body) fields. Disjoint fields/keys merge silently;
// the same field/key changed to different values on both sides conflicts.
import { describe, expect, it } from "vitest";
import { mergeStructuredFields, promptFieldsDiffer } from "./editorPaneModel";
import type { DraftFields } from "./editorPaneModel";
import type { EditableDocument, PromptInputDefinition } from "@/lib/types";

// A minimal DraftFields bundle, overridable per test.
function draft(overrides: Partial<DraftFields> = {}): DraftFields {
  return {
    draftTitle: "A",
    draftStatus: "draft",
    draftEntryType: "manuscript:scene",
    draftMetadata: {},
    draftInputs: [],
    draftOfferOn: [],
    draftContextStrategy: null,
    ...overrides,
  };
}

// A minimal doc, overridable per test — only the fields the merge reads.
function doc(overrides: Record<string, unknown> = {}): EditableDocument {
  return {
    id: "doc_1",
    title: "A",
    body: "b",
    revision: "r1",
    entry_type: "manuscript:scene",
    metadata: {},
    ...overrides,
  } as unknown as EditableDocument;
}

describe("mergeStructuredFields", () => {
  it("merges disjoint scalar fields: local changed title, remote changed status", () => {
    const base = doc({ status: "draft" });
    const remote = doc({ status: "revised" });
    const local = draft({ draftTitle: "New title" });

    const { fields, conflict } = mergeStructuredFields(base, remote, local);

    expect(conflict).toBe(false);
    expect(fields.draftTitle).toBe("New title");
    expect(fields.draftStatus).toBe("revised");
  });

  it("conflicts when both sides change the same field to different values", () => {
    const base = doc({ title: "A" });
    const remote = doc({ title: "C" });
    const local = draft({ draftTitle: "B" });

    const { conflict } = mergeStructuredFields(base, remote, local);

    expect(conflict).toBe(true);
  });

  it("does not conflict when both sides make the same change", () => {
    const base = doc({ title: "A" });
    const remote = doc({ title: "B" });
    const local = draft({ draftTitle: "B" });

    const { fields, conflict } = mergeStructuredFields(base, remote, local);

    expect(conflict).toBe(false);
    expect(fields.draftTitle).toBe("B");
  });

  it("merges disjoint metadata keys per-key", () => {
    const base = doc({ metadata: { a: 1, b: 2 } });
    const remote = doc({ metadata: { a: 1, b: 8 } });
    const local = draft({ draftMetadata: { a: 9, b: 2 } });

    const { fields, conflict } = mergeStructuredFields(base, remote, local);

    expect(conflict).toBe(false);
    expect(fields.draftMetadata).toEqual({ a: 9, b: 8 });
  });

  it("conflicts when both sides change the same metadata key differently", () => {
    const base = doc({ metadata: { a: 1 } });
    const remote = doc({ metadata: { a: 3 } });
    const local = draft({ draftMetadata: { a: 2 } });

    const { conflict } = mergeStructuredFields(base, remote, local);

    expect(conflict).toBe(true);
  });

  it("omits a metadata key deleted on one side and untouched on the other", () => {
    const base = doc({ metadata: { a: 1, b: 2 } });
    const remote = doc({ metadata: { a: 1, b: 2 } });
    const local = draft({ draftMetadata: { b: 2 } });

    const { fields, conflict } = mergeStructuredFields(base, remote, local);

    expect(conflict).toBe(false);
    expect(fields.draftMetadata).toEqual({ b: 2 });
  });

  it("is a no-op when base, local, and remote all agree", () => {
    const base = doc({ title: "A", status: "draft", metadata: { a: 1 } });
    const remote = doc({ title: "A", status: "draft", metadata: { a: 1 } });
    const local = draft({ draftTitle: "A", draftStatus: "draft", draftMetadata: { a: 1 } });

    const { fields, conflict } = mergeStructuredFields(base, remote, local);

    expect(conflict).toBe(false);
    expect(fields.draftTitle).toBe("A");
    expect(fields.draftStatus).toBe("draft");
    expect(fields.draftMetadata).toEqual({ a: 1 });
  });

  it("merges prompt inputs disjoint from a metadata change", () => {
    const baseInputs: PromptInputDefinition[] = [{ name: "x", type: "text", label: "X" }];
    const editedInputs: PromptInputDefinition[] = [{ name: "x", type: "text", label: "X (edited)" }];
    const base = doc({ metadata: { a: 1 }, inputs: baseInputs });
    const remote = doc({ metadata: { a: 1 }, inputs: editedInputs });
    const local = draft({ draftMetadata: { a: 9 }, draftInputs: baseInputs });

    const { fields, conflict } = mergeStructuredFields(base, remote, local);

    expect(conflict).toBe(false);
    expect(fields.draftInputs).toEqual(editedInputs);
    expect(fields.draftMetadata).toEqual({ a: 9 });
  });
});

describe("promptFieldsDiffer", () => {
  const inputs = [{ name: "x", type: "text" }] as unknown as PromptInputDefinition[];

  it("is true when the prompt inputs differ between the two docs", () => {
    expect(promptFieldsDiffer(doc({ inputs: [] }), doc({ inputs }))).toBe(true);
  });

  it("is true when offer_on or context_strategy differ", () => {
    expect(promptFieldsDiffer(doc({ offer_on: [] }), doc({ offer_on: ["lore:character"] }))).toBe(true);
    expect(promptFieldsDiffer(doc({ context_strategy: null }), doc({ context_strategy: { mode: "append" } }))).toBe(true);
  });

  it("is false when the prompt fields match (and for a plain doc that carries none)", () => {
    expect(promptFieldsDiffer(doc({ inputs, offer_on: ["a"] }), doc({ inputs, offer_on: ["a"] }))).toBe(false);
    expect(promptFieldsDiffer(doc(), doc())).toBe(false);
  });
});
