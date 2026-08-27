import { describe, it, expect, beforeEach } from "vitest";
import { setPalette } from "@/lib/utils/colors";
import { tagColorMap, tagHexResolver } from "@/lib/utils/tags";
import type { ScopedTag } from "@/lib/types";

const scope = { sources: [] };
const tags: ScopedTag[] = [
  { name: "Protagonist", scope, color: "slate-blue" },
  { name: "shifter", scope, color: null }, // no colour spent
  { name: "POV", scope, color: "amber" },
];

describe("tagColorMap", () => {
  it("maps only coloured tags, lowercased name → swatch id", () => {
    const map = tagColorMap(tags);
    expect(map.get("protagonist")).toBe("slate-blue");
    expect(map.get("pov")).toBe("amber");
    expect(map.has("shifter")).toBe(false); // colour: null → omitted
  });
});

describe("tagHexResolver", () => {
  beforeEach(() =>
    setPalette([
      { id: "slate-blue", label: "Slate blue", hex: "#5b5ca8" },
      { id: "amber", label: "Amber", hex: "#c8794a" },
    ]),
  );

  it("resolves a coloured tag to its swatch hex, case-insensitively", () => {
    const hex = tagHexResolver(tags);
    expect(hex("protagonist")).toBe("#5b5ca8");
    expect(hex("PROTAGONIST")).toBe("#5b5ca8");
    expect(hex("POV")).toBe("#c8794a");
  });

  it("returns null for an uncoloured or unknown tag", () => {
    const hex = tagHexResolver(tags);
    expect(hex("shifter")).toBeNull(); // colour: null
    expect(hex("nonexistent")).toBeNull(); // not in the vocabulary
  });

  it("returns null when the tag's swatch id isn't in the palette", () => {
    setPalette([]); // a stale swatch id no longer in the machine palette
    const hex = tagHexResolver(tags);
    expect(hex("protagonist")).toBeNull();
  });
});
