import { describe, expect, it } from "vitest";
import type { NodePickerConfig, ViewRef, ViewSource } from "@/lib/types";
import { isViewRef, membershipToSources, pickerMembership } from "./pickerSources";

describe("pickerSources", () => {
  describe("isViewRef", () => {
    it("distinguishes a view-ref from an inline ViewSpec", () => {
      expect(isViewRef({ view: "v1" })).toBe(true);
      expect(isViewRef({ kind: "lore" })).toBe(false);
      expect(isViewRef({ kind: "lore", expr: { type: "lore:character" } })).toBe(false);
    });
  });

  describe("pickerMembership", () => {
    it("reduces degenerate sources and ignores view-refs", () => {
      const config: NodePickerConfig = {
        sources: [
          { kind: "scene" },
          { kind: "lore", expr: { type: "lore:character" } },
          { view: "act-2-cast" },
        ],
      };
      expect(pickerMembership(config)).toEqual({
        kinds: ["scene", "lore"],
        entryTypes: { lore: ["lore:character"] },
      });
    });
  });

  describe("membershipToSources", () => {
    it("encodes kind-only, single-leaf, and union-of-leaves shapes", () => {
      const sources = membershipToSources(
        ["scene"],
        { lore: ["lore:character", "lore:location"] },
      );
      expect(sources).toEqual([
        { kind: "scene" },
        { kind: "lore", expr: { union: [{ type: "lore:character" }, { type: "lore:location" }] } },
      ]);
    });

    it("preserves saved-view refs when re-encoding the degenerate part", () => {
      // The scenario the checkbox tree hits: an author added a view-ref, then
      // toggles a type checkbox. writeSelection re-encodes membership wholesale
      // via membershipToSources(existing = config.sources) — the view-ref must
      // survive (#82 / ADR-0023).
      const existing: ViewSource[] = [
        { kind: "lore", expr: { type: "lore:character" } },
        { view: "act-2-cast" },
      ];
      // Toggle adds lore:location; existing carries the view-ref through.
      const next = membershipToSources(
        ["lore"],
        { lore: ["lore:character", "lore:location"] },
        existing,
      );
      expect(next).toContainEqual({ view: "act-2-cast" } satisfies ViewRef);
      // And the degenerate part reflects the new membership.
      expect(next).toContainEqual({
        kind: "lore",
        expr: { union: [{ type: "lore:character" }, { type: "lore:location" }] },
      });
      // View-ref stays last (after the degenerate sources).
      expect(isViewRef(next[next.length - 1])).toBe(true);
    });

    it("preserves a view-ref even when membership empties to nothing", () => {
      // Unchecking the last type must not take the view-ref down with it.
      const existing: ViewSource[] = [
        { kind: "lore", expr: { type: "lore:character" } },
        { view: "act-2-cast" },
      ];
      const next = membershipToSources([], {}, existing);
      expect(next).toEqual([{ view: "act-2-cast" }]);
    });

    it("drops nothing but also adds nothing when there are no refs to preserve", () => {
      const next = membershipToSources(["scene"], {}, [{ kind: "scene" }]);
      expect(next).toEqual([{ kind: "scene" }]);
    });

    it("preserves multiple view-refs in order", () => {
      const existing: ViewSource[] = [
        { kind: "scene" },
        { view: "a" },
        { view: "b" },
      ];
      const next = membershipToSources(["scene"], {}, existing);
      expect(next).toEqual([{ kind: "scene" }, { view: "a" }, { view: "b" }]);
    });
  });
});
