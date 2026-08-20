import { describe, it, expect } from "vitest";
import {
  coerceInputValue,
  isListShapedInputType,
  promptInputTypeLabel,
  PROMPT_INPUT_TYPE_CHOICES,
} from "./promptInputs";
import { FIELD_TYPE_CHOICES, fieldTypeLabel } from "./fieldIcons";

// #1225: prompt inputs offer the same authorable value types as metadata fields
// (one catalog, so they can't drift), minus computed/date, plus the two
// prompt-only invocation types.
describe("PROMPT_INPUT_TYPE_CHOICES — one catalog with the field types", () => {
  it("carries every metadata value type except computed (date is already excluded)", () => {
    for (const t of FIELD_TYPE_CHOICES) {
      if (t === "computed") expect(PROMPT_INPUT_TYPE_CHOICES).not.toContain(t);
      else expect(PROMPT_INPUT_TYPE_CHOICES).toContain(t);
    }
    expect(PROMPT_INPUT_TYPE_CHOICES).not.toContain("date");
  });

  it("adds the newly-unified list types and the prompt-only invocation types", () => {
    for (const t of ["multi_select", "tags", "list"] as const) {
      expect(PROMPT_INPUT_TYPE_CHOICES).toContain(t);
    }
    expect(PROMPT_INPUT_TYPE_CHOICES).toContain("context_pick");
    expect(PROMPT_INPUT_TYPE_CHOICES).toContain("scene_ref");
  });

  it("labels shared types from the field label source, and names the prompt-only ones", () => {
    expect(promptInputTypeLabel("multi_select")).toBe(fieldTypeLabel("multi_select"));
    expect(promptInputTypeLabel("list")).toBe(fieldTypeLabel("list"));
    expect(promptInputTypeLabel("context_pick")).toBe("Context Picker");
    expect(promptInputTypeLabel("scene_ref")).toBe("Scene Reference");
  });
});

describe("coerceInputValue — the new list-shaped types parse to real arrays", () => {
  it("parses multi_select / tags / list JSON to an array (like entity_ref_list)", () => {
    for (const t of ["multi_select", "tags", "list"] as const) {
      expect(coerceInputValue(JSON.stringify(["a", "b"]), t)).toEqual(["a", "b"]);
    }
  });

  it("treats empty as unset (null) so the template can guard `is defined`", () => {
    expect(coerceInputValue("", "multi_select")).toBeNull();
    expect(coerceInputValue("   ", "tags")).toBeNull();
  });

  it("coerces an untouched scalar/comma default to a list (DefaultValueEditor emits a bare value)", () => {
    // A multi_select default is stored as the bare option value "sight" and
    // seeded via String(); it must still reach the template as ["sight"], not
    // be dropped by a strict JSON.parse. A comma-string default splits.
    expect(coerceInputValue("sight", "multi_select")).toEqual(["sight"]);
    expect(coerceInputValue("a, b", "tags")).toEqual(["a", "b"]);
  });

  it("leaves scalar types (select / color) as trimmed strings", () => {
    expect(coerceInputValue(" sight ", "select")).toBe("sight");
    expect(coerceInputValue("#ff0000", "color")).toBe("#ff0000");
    expect(isListShapedInputType("color")).toBe(false);
    expect(isListShapedInputType("multi_select")).toBe(true);
  });
});
