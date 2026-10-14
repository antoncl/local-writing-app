import { describe, expect, it } from "vitest";
import { contentOverrideMarks } from "@/lib/editor-core/contentOverrideMarks";

const lore = (extra: object) =>
  ({ id: "l1", title: "T", source_layer_label: "Series", ...extra }) as never;

describe("contentOverrideMarks", () => {
  it("marks an overridden title and body of a lore entry, naming the source layer", () => {
    const marks = contentOverrideMarks(
      lore({ overridden_content: ["title", "body"], inherited_title: "Old" }),
      "lore",
      true,
    );
    expect(marks.sourceLabel).toBe("Series");
    expect(marks.title?.chipText).toBe("Reset to Series");
    expect(marks.title?.tooltip).toContain('"Old"');
    expect(marks.body?.chipText).toBe("Reset to Series…");
  });

  it("shows nothing when reset is not allowed, or off the lore kind", () => {
    const scene = lore({ overridden_content: ["title", "body"] });
    expect(contentOverrideMarks(scene, "lore", false)).toMatchObject({ title: null, body: null });
    expect(contentOverrideMarks(scene, "prompt", true)).toMatchObject({ title: null, body: null });
  });

  it("falls back to 'inherited' without a source label", () => {
    expect(contentOverrideMarks(null, "lore", true).sourceLabel).toBe("inherited");
  });
});
