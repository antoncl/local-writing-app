// @vitest-environment happy-dom
// The persisted rail-section collapse store (#1444). Locks its contract: the
// caller's default when nothing is stored, toggle against that default, a
// round-trip through localStorage that survives a "reload" (a fresh instance),
// and defensive handling of non-boolean / corrupt stored values.
import { describe, it, expect, beforeEach } from "vitest";
import { RailSectionCollapse } from "./railSectionCollapse.svelte";

const KEY = "lwa.railSectionCollapse";

describe("railSectionCollapse", () => {
  beforeEach(() => localStorage.clear());

  it("returns the caller's default when nothing is stored", () => {
    const s = new RailSectionCollapse();
    expect(s.isExpanded("references", false)).toBe(false);
    expect(s.isExpanded("conversations", true)).toBe(true);
  });

  it("toggles against the given default", () => {
    const s = new RailSectionCollapse();
    s.toggle("references", false); // default false → true
    expect(s.isExpanded("references", false)).toBe(true);
    s.toggle("references", false); // true → false
    expect(s.isExpanded("references", false)).toBe(false);
  });

  it("persists across a reload — a fresh instance reads the stored state", () => {
    const s1 = new RailSectionCollapse();
    s1.set("conversations", false);
    s1.set("field:related_entries", true);

    const s2 = new RailSectionCollapse(); // simulates a page reload
    expect(s2.isExpanded("conversations", true)).toBe(false);
    expect(s2.isExpanded("field:related_entries", false)).toBe(true);
    // An untouched key still falls back to its own default.
    expect(s2.isExpanded("staged-changes", true)).toBe(true);
  });

  it("writes one JSON blob and ignores non-boolean stored values on load", () => {
    localStorage.setItem(KEY, JSON.stringify({ references: true, junk: "nope", n: 5 }));
    const s = new RailSectionCollapse();
    expect(s.isExpanded("references", false)).toBe(true);
    expect(s.isExpanded("junk", false)).toBe(false); // non-boolean dropped → default

    s.set("conversations", false);
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "null");
    expect(raw).toMatchObject({ references: true, conversations: false });
    expect(raw.junk).toBeUndefined();
  });

  it("falls back cleanly on a corrupt stored blob", () => {
    localStorage.setItem(KEY, "{not json");
    const s = new RailSectionCollapse();
    expect(s.isExpanded("references", false)).toBe(false); // no throw, uses default
  });
});
