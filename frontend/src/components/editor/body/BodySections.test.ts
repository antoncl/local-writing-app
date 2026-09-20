// @vitest-environment happy-dom
// BodySections (#2009): the headed-section stack under the prose body. The
// component-test harness deliberately never mounts TipTap under happy-dom
// (#642, see ListValueEditor.test.ts) — MetadataLongTextEditor is swapped for
// a stub (BodySections.mockLongText.svelte) so this pins the markup (heading
// levels, order, `data-field-section` ids, captions) without depending on a
// real editor mounting.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@/lib/test/component";
import { createSectionRegistry } from "@/lib/editor-core/sectionKeyboardBridge";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";
// `vi.mock` calls are hoisted above every import in this file (vitest's
// static transform), so this substitution is in place before BodySections
// (imported below) resolves its own static import of MetadataLongTextEditor.
import BodySections from "./BodySections.svelte";

vi.mock("@/components/widgets/MetadataLongTextEditor.svelte", async () => {
  const stub = await import("./BodySections.mockLongText.svelte");
  return { default: stub.default };
});

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": { name: "Character", kind: "lore", fields: ["bio", "goal", "obstacle", "beats"] },
  },
  fields: {
    bio: { name: "Bio", type: "long_text", options: [] },
    goal: { name: "Goal", type: "long_text", options: [], group: "Arc" },
    obstacle: { name: "Obstacle", type: "long_text", options: [], group: "Arc" },
    // #2043: a list whose item shape carries a long_text member renders as a
    // repeating body section AFTER the long_text sections above.
    beats: {
      name: "Beats",
      type: "list",
      options: [],
      item_group: "plot_beat",
      item_scalar: false,
      item_members: [
        { key: "title", name: "Title", type: "text" },
        { key: "function", name: "Function", type: "long_text" },
      ],
    },
  },
} as unknown as MetadataSchema;

function mount(metadata: EntryMetadata = {}, readOnly = false) {
  const onMetadataChange = vi.fn();
  const { container } = render(BodySections, {
    props: {
      schema: SCHEMA,
      entryType: "lore:character",
      metadata,
      readOnly,
      onMetadataChange,
      register: createSectionRegistry(),
    },
  });
  return { container, onMetadataChange };
}

describe("BodySections", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders headings in order: H2 Bio, H2 Arc, H3 Goal, H3 Obstacle, then the Beats list section, with captions", () => {
    const { container } = mount({ beats: [{ title: "Beat one", function: "Do it." }] });
    const headings = Array.from(container.querySelectorAll("h2, h3")).map((el) => ({
      tag: el.tagName,
      text: el.textContent?.trim(),
    }));
    expect(headings.slice(0, 4)).toEqual([
      { tag: "H2", text: "Bio long text" },
      { tag: "H2", text: "Arc group" },
      { tag: "H3", text: "Goal long text" },
      { tag: "H3", text: "Obstacle long text" },
    ]);
    // #2043: the list section's H2 is appended LAST, after every long_text
    // section/group — its caption carries the item count, not "long text"/"group".
    expect(headings[4].tag).toBe("H2");
    expect(headings[4].text).toContain("Beats");
    expect(headings[4].text).toContain("list · 1 item");
    expect(container.querySelectorAll(".bs-caption")).toHaveLength(5);
  });

  it("stamps data-field-section + a section-{id} anchor on every field, including grouped ones and the list section", () => {
    const { container } = mount();
    for (const id of ["bio", "goal", "obstacle", "beats"]) {
      const section = container.querySelector(`[data-field-section="${id}"]`);
      expect(section).not.toBeNull();
      expect(section?.id).toBe(`section-${id}`);
    }
  });

  it("mounts every field's editor without throwing (a stubbed MetadataLongTextEditor per field)", () => {
    const { container } = mount({ bio: "hello" });
    expect(container.querySelectorAll('[data-testid="mock-long-text"]')).toHaveLength(3);
  });

  it("with one beat item, mounts a 4th mock editor for its prose member (list sections render after long_text sections)", () => {
    const { container } = mount({ bio: "hello", beats: [{ title: "Beat one", function: "Do it." }] });
    expect(container.querySelectorAll('[data-testid="mock-long-text"]')).toHaveLength(4);
  });

  it("readOnly renders a static display instead of the editor", () => {
    const { container } = mount({ bio: "hello" }, true);
    expect(container.querySelectorAll('[data-testid="mock-long-text"]')).toHaveLength(0);
    expect(container.querySelector(".fv-static-longtext")).not.toBeNull();
  });
});
