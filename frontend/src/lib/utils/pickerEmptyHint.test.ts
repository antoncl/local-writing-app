// #2215: the picker's empty state must point where the targets can actually
// be set — a group-applied field has no definition of its own.
import { describe, expect, it } from "vitest";
import { railFieldEmptyHint } from "./pickerEmptyHint";
import type { MetadataSchema } from "@/lib/types";

const schema = { groups: { connections: { name: "Connections", members: [] } } } as unknown as MetadataSchema;

describe("railFieldEmptyHint", () => {
  it("points an ordinary field at its own definition", () => {
    const hint = railFieldEmptyHint({ name: "Home Place", group_origin: null }, schema);
    expect(hint.detail).toContain("the field's definition");
  });

  it("points a field from an applied group at the group member", () => {
    const hint = railFieldEmptyHint({ name: "Met at", group_origin: "connections" }, schema);
    expect(hint.detail).toContain("Reusable groups → Connections → Met at");
    expect(hint.detail).not.toContain("the field's definition");
  });
});
