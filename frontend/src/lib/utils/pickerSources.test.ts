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
          { kind: "manuscript" },
          { kind: "lore", expr: { type: "lore:character" } },
          { view: "act-2-cast" },
        ],
      };
      expect(pickerMembership(config)).toEqual({
        kinds: ["manuscript", "lore"],
        entryTypes: { lore: ["lore:character"] },
        families: {},
      });
    });

    it("records a `descendants_of` leaf as a FAMILY scope (#1947)", () => {
      const config: NodePickerConfig = {
        sources: [{ kind: "lore", expr: { descendants_of: "lore:character" } }],
      };
      // The fqn is in entryTypes (so "is this in scope" consumers still see it)
      // AND in families (marking it is-a, self + subtypes).
      expect(pickerMembership(config)).toEqual({
        kinds: ["lore"],
        entryTypes: { lore: ["lore:character"] },
        families: { lore: ["lore:character"] },
      });
    });

    it("splits a MIXED union — one kind can hold exact and family leaves", () => {
      const config: NodePickerConfig = {
        sources: [
          {
            kind: "lore",
            expr: { union: [{ type: "lore:item" }, { descendants_of: "lore:character" }] },
          },
        ],
      };
      const m = pickerMembership(config);
      expect(m.entryTypes.lore.sort()).toEqual(["lore:character", "lore:item"]);
      expect(m.families).toEqual({ lore: ["lore:character"] });
    });

    it("treats a non-degenerate expr as kind-only (no entry_type constraint)", () => {
      const config: NodePickerConfig = {
        sources: [{ kind: "lore", expr: { intersect: [{ type: "lore:character" }, { tagged: "t1" }] } }],
      };
      expect(pickerMembership(config)).toEqual({ kinds: ["lore"], entryTypes: {}, families: {} });
    });
  });

  describe("membershipToSources", () => {
    it("encodes kind-only, single-leaf, and union-of-leaves shapes", () => {
      const sources = membershipToSources(
        ["manuscript"],
        { lore: ["lore:character", "lore:location"] },
        {},
      );
      expect(sources).toEqual([
        { kind: "manuscript" },
        { kind: "lore", expr: { union: [{ type: "lore:character" }, { type: "lore:location" }] } },
      ]);
    });

    it("emits `{descendants_of}` for a FAMILY fqn and round-trips through pickerMembership (#1947)", () => {
      const sources = membershipToSources(["lore"], { lore: ["lore:character"] }, { lore: ["lore:character"] });
      expect(sources).toEqual([{ kind: "lore", expr: { descendants_of: "lore:character" } }]);
      // Round-trip: reading it back yields the same family membership.
      expect(pickerMembership({ sources })).toEqual({
        kinds: ["lore"],
        entryTypes: { lore: ["lore:character"] },
        families: { lore: ["lore:character"] },
      });
    });

    it("lowers a mixed exact+family kind to a stable-sorted heterogeneous union", () => {
      // fqns sorted so equal membership is byte-equal (change-detection relies on it).
      const sources = membershipToSources(
        ["lore"],
        { lore: ["lore:item", "lore:character"] },
        { lore: ["lore:character"] },
      );
      expect(sources).toEqual([
        {
          kind: "lore",
          expr: { union: [{ descendants_of: "lore:character" }, { type: "lore:item" }] },
        },
      ]);
    });

    it("preserves saved-view refs when re-encoding the degenerate part", () => {
      const existing: ViewSource[] = [
        { kind: "lore", expr: { type: "lore:character" } },
        { view: "act-2-cast" },
      ];
      const next = membershipToSources(
        ["lore"],
        { lore: ["lore:character", "lore:location"] },
        {},
        existing,
      );
      expect(next).toContainEqual({ view: "act-2-cast" } satisfies ViewRef);
      expect(next).toContainEqual({
        kind: "lore",
        expr: { union: [{ type: "lore:character" }, { type: "lore:location" }] },
      });
      expect(isViewRef(next[next.length - 1])).toBe(true);
    });

    it("preserves a view-ref even when membership empties to nothing", () => {
      const existing: ViewSource[] = [
        { kind: "lore", expr: { type: "lore:character" } },
        { view: "act-2-cast" },
      ];
      const next = membershipToSources([], {}, {}, existing);
      expect(next).toEqual([{ view: "act-2-cast" }]);
    });

    it("preserves a genuinely non-degenerate inline expr the tree can't represent (#94)", () => {
      // An `intersect` (not a bare type/descendants_of/union) can't be reduced to
      // membership, so the checkbox re-encode must carry it through verbatim. (A
      // `descendants_of` leaf, by contrast, is NOW authored — rebuilt from
      // membership, #1947 — so it is not in this preserved set.)
      const existing: ViewSource[] = [
        { kind: "lore", expr: { type: "lore:character" } },
        { kind: "lore", expr: { intersect: [{ type: "lore:character" }, { tagged: "t1" }] } },
      ];
      const next = membershipToSources(["lore"], { lore: ["lore:character"] }, {}, existing);
      expect(next).toContainEqual({ kind: "lore", expr: { intersect: [{ type: "lore:character" }, { tagged: "t1" }] } });
      expect(next).toContainEqual({ kind: "lore", expr: { type: "lore:character" } });
    });

    it("preserves multiple view-refs in order", () => {
      const existing: ViewSource[] = [{ kind: "manuscript" }, { view: "a" }, { view: "b" }];
      const next = membershipToSources(["manuscript"], {}, {}, existing);
      expect(next).toEqual([{ kind: "manuscript" }, { view: "a" }, { view: "b" }]);
    });
  });
});
