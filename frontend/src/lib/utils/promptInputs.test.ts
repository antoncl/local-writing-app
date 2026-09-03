import { describe, it, expect } from "vitest";
import {
  coerceInputValue,
  decodePickerValue,
  encodePickerValue,
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
    for (const t of ["multi_select", "list"] as const) {
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
  it("parses multi_select / list JSON to an array (like entity_ref_list)", () => {
    for (const t of ["multi_select", "list"] as const) {
      expect(coerceInputValue(JSON.stringify(["a", "b"]), t)).toEqual(["a", "b"]);
    }
  });

  it("treats empty as unset (null) so the template can guard `is defined`", () => {
    expect(coerceInputValue("", "multi_select")).toBeNull();
    expect(coerceInputValue("   ", "multi_select")).toBeNull();
  });

  it("coerces an untouched scalar/comma default to a list (DefaultValueEditor emits a bare value)", () => {
    // A multi_select default is stored as the bare option value "sight" and
    // seeded via String(); it must still reach the template as ["sight"], not
    // be dropped by a strict JSON.parse. A comma-string default splits.
    expect(coerceInputValue("sight", "multi_select")).toEqual(["sight"]);
    expect(coerceInputValue("a, b", "multi_select")).toEqual(["a", "b"]);
  });

  it("leaves scalar types (select / color) as trimmed strings", () => {
    expect(coerceInputValue(" sight ", "select")).toBe("sight");
    expect(coerceInputValue("#ff0000", "color")).toBe("#ff0000");
    expect(isListShapedInputType("color")).toBe(false);
    expect(isListShapedInputType("multi_select")).toBe(true);
  });
});

// #1482: the ONE NodePickerRef[] ⇄ wire-string codec. Everything that reads or
// writes a context_pick value routes through these two.
describe("context_pick value codec (#1482)", () => {
  const REFS = [
    { id: "act_1", kind: "manuscript", title: "Act I", entry_type: "manuscript:act" },
    { id: "lore_a", kind: "lore", title: "Annie", entry_type: "lore:character" },
  ];

  it("round-trips: decode(encode(refs)) === refs", () => {
    expect(decodePickerValue(encodePickerValue(REFS as never))).toEqual(REFS);
  });

  it("decodes an already-decoded array (persisted chat seeds) as-is", () => {
    expect(decodePickerValue(REFS)).toEqual(REFS);
  });

  it("unreadable input decodes to [] — empty, garbage, non-array JSON", () => {
    expect(decodePickerValue("")).toEqual([]);
    expect(decodePickerValue("   ")).toEqual([]);
    expect(decodePickerValue("not json")).toEqual([]);
    expect(decodePickerValue('{"id":"a","kind":"lore"}')).toEqual([]);
    expect(decodePickerValue(undefined)).toEqual([]);
    expect(decodePickerValue(42)).toEqual([]);
  });

  it("drops items that are not ref-shaped (id + kind required)", () => {
    expect(decodePickerValue('[{"id":"a"}, {"kind":"lore"}, "a", null, {"id":"b","kind":"lore"}]')).toEqual([
      { id: "b", kind: "lore" },
    ]);
  });
});

describe("coerceInputValue — context_pick stays the encoded wire STRING (#1482)", () => {
  // The regression this guards: chat's forked coercer pre-decoded picks to an
  // array, and the backend's bind layer (preview.py::_coerce_input_value)
  // short-circuits on non-strings — so a chat prompt picking an act/chapter
  // silently skipped ADR-0074 S4 container expansion. The wire contract is the
  // STRING; the backend parses it, expands containers, and wraps EntryRefs.
  const ACT_PICK = '[{"id":"act_1","kind":"manuscript","title":"Act I","entry_type":"manuscript:act"}]';

  it("a container pick ships as a string, byte-stable through coercion", () => {
    const coerced = coerceInputValue(ACT_PICK, "context_pick");
    expect(typeof coerced).toBe("string");
    expect(coerced).toBe(ACT_PICK);
  });

  it("empty is a defined, EMPTY pick list — never #24-unset", () => {
    // Create-mode brainstorms branch on `entry(inputs.entry)` being falsy
    // (revise-entry.md); an unset pick reaching the template as an undefined
    // name would kill them under StrictUndefined.
    expect(coerceInputValue("", "context_pick")).toBe("[]");
    expect(coerceInputValue("   ", "context_pick")).toBe("[]");
    expect(coerceInputValue("[]", "context_pick")).toBe("[]");
  });

  it("normalizes stray shapes through the codec instead of shipping garbage", () => {
    expect(coerceInputValue('[{"id":"a"},{"id":"b","kind":"lore"}]', "context_pick")).toBe(
      '[{"id":"b","kind":"lore"}]',
    );
    expect(coerceInputValue("not json", "context_pick")).toBe("[]");
  });
});
