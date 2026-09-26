// Pure unit tests for the ADR-0095 §8 stop-edit gate.
import { describe, expect, it } from "vitest";
import { stopEditingEngaged, stopFieldEditable, stopFieldTargetable, type StopFieldEditContext } from "./stopFieldEditable";
import type { MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": { name: "Character", kind: "lore", fields: ["eye_color", "cost", "kin", "allies"] },
  },
  fields: {
    eye_color: { name: "Eye colour", type: "text", options: [] },
    cost: { name: "Cost", type: "computed", options: [], computed: { fn: "cost" } },
    kin: {
      name: "Kin",
      type: "list",
      options: [],
      item_scalar: false,
      item_members: [{ key: "to", name: "To", type: "entity_ref" }],
    },
    allies: { name: "Allies", type: "entity_ref_list", options: [] },
  },
} as unknown as MetadataSchema;

function baseCtx(overrides: Partial<StopFieldEditContext> = {}): StopFieldEditContext {
  return {
    scrubbed: true,
    snapshotParked: false,
    reviewing: false,
    inheritedReadOnly: false,
    documentKind: "lore",
    schema: SCHEMA,
    entryType: "lore:character",
    ...overrides,
  };
}

describe("stopEditingEngaged", () => {
  it("is true only when scrubbed and no other read-only axis is active", () => {
    expect(stopEditingEngaged(baseCtx())).toBe(true);
    expect(stopEditingEngaged(baseCtx({ scrubbed: false }))).toBe(false);
    expect(stopEditingEngaged(baseCtx({ snapshotParked: true }))).toBe(false);
    expect(stopEditingEngaged(baseCtx({ reviewing: true }))).toBe(false);
    expect(stopEditingEngaged(baseCtx({ inheritedReadOnly: true }))).toBe(false);
  });

  it("an inherited prompt stays editable — the inheritance lock is scene/lore-only", () => {
    expect(stopEditingEngaged(baseCtx({ inheritedReadOnly: true, documentKind: "prompt" }))).toBe(true);
  });
});

describe("stopFieldTargetable / stopFieldEditable", () => {
  it("a plain text field is targetable", () => {
    expect(stopFieldTargetable("eye_color", SCHEMA, "lore:character")).toBe(true);
    expect(stopFieldEditable("eye_color", baseCtx())).toBe(true);
  });

  it("the intrinsic title is always targetable", () => {
    expect(stopFieldTargetable("title", SCHEMA, "lore:character")).toBe(true);
  });

  it("the body is NEVER targetable, even though a mutation can append to it", () => {
    expect(stopFieldTargetable("body", SCHEMA, "lore:character")).toBe(false);
    expect(stopFieldEditable("body", baseCtx())).toBe(false);
  });

  it("a computed field is not targetable", () => {
    expect(stopFieldTargetable("cost", SCHEMA, "lore:character")).toBe(false);
  });

  it("a reference-keyed list IS targetable (§8's collection/keyed branches)", () => {
    expect(stopFieldTargetable("kin", SCHEMA, "lore:character")).toBe(true);
  });

  it("a plain entity_ref_list collection is targetable too", () => {
    expect(stopFieldTargetable("allies", SCHEMA, "lore:character")).toBe(true);
  });

  it("stopFieldEditable is false when the gate isn't engaged, regardless of the field", () => {
    expect(stopFieldEditable("eye_color", baseCtx({ reviewing: true }))).toBe(false);
  });
});
