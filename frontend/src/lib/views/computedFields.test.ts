import { describe, expect, it } from "vitest";
import { liftFieldByKey, liftFieldsForKind } from "@/lib/views/computedFields";

// The registry that lets the view designer's field picker offer lift-synthesized
// fields — the fields a pane stamps into `metadata` but the schema never declares
// (#960). Without a registry entry the picker (schema-only) can't surface them, so a
// built-in view could filter on a field a user cannot pick.
describe("computedFields registry (#960)", () => {
  it("offers `disposition` for prompt views", () => {
    const [field] = liftFieldsForKind("prompt");
    expect(field.key).toBe("disposition");
    expect(field.def.type).toBe("select");
    expect(field.def.category).toBe("computed");
    expect(liftFieldByKey("prompt", "disposition")).toEqual(field.def);
  });

  it("offers `seed_disposition` for chat views", () => {
    const [field] = liftFieldsForKind("chat");
    expect(field.key).toBe("seed_disposition");
    expect(field.def.category).toBe("computed");
    expect(liftFieldByKey("chat", "seed_disposition")).toEqual(field.def);
  });

  it("has no computed fields for a kind that stamps none", () => {
    expect(liftFieldsForKind("lore")).toEqual([]);
    expect(liftFieldByKey("lore", "disposition")).toBeNull();
    // A key that isn't the kind's computed field resolves to null.
    expect(liftFieldByKey("chat", "disposition")).toBeNull();
    expect(liftFieldByKey("prompt", "seed_disposition")).toBeNull();
  });

  it("hands out a fresh descriptor per call (pickers may copy/mutate)", () => {
    expect(liftFieldsForKind("prompt")[0].def).not.toBe(liftFieldsForKind("prompt")[0].def);
  });
});
