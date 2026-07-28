import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoreProposalController } from "./loreProposal.svelte";
import { loreBrainstorm } from "./loreBrainstorm.svelte";
import type { EntryPatch, MetadataSchema } from "@/lib/types";

// The controller is the entry-pane end of the ADR-0046 review: it derives which
// flips a committed patch produces off the LIVE buffer the host feeds it, and
// owns the review as a frozen transaction — accepting a unit only accumulates
// resolution (never a write), and `commit()` issues ONE explicit post (#634).
// These tests pin what a refactor could silently break: the long_text-only
// derivation (a structured field must not leak into the body-flip list until
// slice 3b), and the transaction (accumulate → single flush on commit, no write
// on abandon, reset on a superseded proposal).

// Minimal schema: one long_text field, one structured, so the derivation has
// both to discriminate. Cast — the controller only reads `.fields[id].type/name`.
const schema = {
  entry_types: {},
  fields: {
    bio: { name: "Biography", type: "long_text", options: [] },
    allegiance: { name: "Allegiance", type: "select", options: [] },
  },
} as unknown as MetadataSchema;

const patch = (body: string | null, fields: EntryPatch["fields"] = {}): EntryPatch => ({
  body,
  fields,
});

function loreController(entryId: string): LoreProposalController {
  const c = new LoreProposalController();
  c.documentKind = "lore";
  c.sceneId = entryId;
  c.schema = schema;
  return c;
}

describe("LoreProposalController", () => {
  beforeEach(() => {
    for (const id of ["e1", "e2"]) loreBrainstorm.clear(id);
  });

  it("is gated on lore — a non-lore pane never surfaces a proposal", () => {
    loreBrainstorm.propose("e1", patch("body"));
    const c = loreController("e1");
    c.documentKind = "scene";
    expect(c.proposal).toBeNull();
    expect(c.hasReview).toBe(false);
  });

  it("derives one flip per proposed long_text field, paired with current value", () => {
    const c = loreController("e1");
    c.metadata = { bio: "old bio" };
    loreBrainstorm.propose("e1", patch(null, { bio: "new bio" }));
    expect(c.fields).toEqual([
      { fieldId: "bio", label: "Biography", currentValue: "old bio", proposedValue: "new bio" },
    ]);
  });

  it("ignores structured and unknown fields in the flip list (slice 3b renders those)", () => {
    const c = loreController("e1");
    loreBrainstorm.propose("e1", patch(null, { allegiance: "Crown", nonesuch: "x", bio: "b" }));
    expect(c.fields.map((f) => f.fieldId)).toEqual(["bio"]);
  });

  it("hasReview is true for a body-only patch and false for an all-structured one", () => {
    const bodyOnly = loreController("e1");
    loreBrainstorm.propose("e1", patch("revised", {}));
    expect(bodyOnly.hasReview).toBe(true);

    const structuredOnly = loreController("e2");
    loreBrainstorm.propose("e2", patch(null, { allegiance: "Crown" }));
    expect(structuredOnly.fields).toEqual([]);
    expect(structuredOnly.hasReview).toBe(false);
  });

  it("reacts to the live-metadata feed — the flip's current value tracks the buffer", () => {
    const c = loreController("e1");
    c.metadata = { bio: "first" };
    loreBrainstorm.propose("e1", patch(null, { bio: "proposed" }));
    expect(c.fields[0].currentValue).toBe("first");
    c.metadata = { bio: "edited since" };
    expect(c.fields[0].currentValue).toBe("edited since");
  });

  it("hasPendingChanges tracks the accumulated resolution", () => {
    const c = loreController("e1");
    expect(c.hasPendingChanges).toBe(false);
    c.setFieldResolution("bio", "adopted");
    expect(c.hasPendingChanges).toBe(true);
    c.setFieldResolution("bio", null); // declined back to current
    expect(c.hasPendingChanges).toBe(false);
    c.setBodyResolution("adopted body");
    expect(c.hasPendingChanges).toBe(true);
  });

  it("commit applies adopted body + fields and posts exactly once (one PUT)", async () => {
    const c = loreController("e1");
    const onAdoptFields = vi.fn();
    const onAdoptBody = vi.fn();
    const onFlush = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onAdoptBody = onAdoptBody;
    c.onEmitChange = vi.fn();
    c.onFlush = onFlush;
    loreBrainstorm.propose("e1", patch("new body", { bio: "new bio" }));

    c.setBodyResolution("new body");
    c.setFieldResolution("bio", "new bio");
    await c.commit();

    expect(onAdoptFields).toHaveBeenCalledWith({ bio: "new bio" });
    expect(onAdoptBody).toHaveBeenCalledWith("new body");
    // The single explicit post that ends the transaction — body + metadata land
    // in ONE lore PUT (ADR-0046 §1), not per-unit and not via a debounce.
    expect(onFlush).toHaveBeenCalledTimes(1);
    // Committing ends the review and clears the accumulation.
    expect(c.proposal).toBeNull();
    expect(c.hasPendingChanges).toBe(false);
  });

  it("commit with fields but no body still posts once", async () => {
    const c = loreController("e1");
    const onAdoptBody = vi.fn();
    const onEmitChange = vi.fn();
    const onFlush = vi.fn();
    c.onAdoptFields = vi.fn();
    c.onAdoptBody = onAdoptBody;
    c.onEmitChange = onEmitChange;
    c.onFlush = onFlush;
    loreBrainstorm.propose("e1", patch(null, { bio: "new bio" }));

    c.setFieldResolution("bio", "new bio");
    await c.commit();

    expect(onAdoptBody).not.toHaveBeenCalled();
    expect(onEmitChange).toHaveBeenCalled();
    expect(onFlush).toHaveBeenCalledTimes(1);
  });

  it("commit with nothing adopted is a plain dismiss — no write, no post", async () => {
    const c = loreController("e1");
    const onAdoptFields = vi.fn();
    const onAdoptBody = vi.fn();
    const onFlush = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onAdoptBody = onAdoptBody;
    c.onFlush = onFlush;
    loreBrainstorm.propose("e1", patch("body"));

    await c.commit(); // nothing resolved → "Close"
    expect(onAdoptFields).not.toHaveBeenCalled();
    expect(onAdoptBody).not.toHaveBeenCalled();
    expect(onFlush).not.toHaveBeenCalled();
    expect(c.proposal).toBeNull();
  });

  it("abandon discards without writing, and resets the accumulation", () => {
    const c = loreController("e1");
    const onFlush = vi.fn();
    const onAdoptBody = vi.fn();
    c.onFlush = onFlush;
    c.onAdoptBody = onAdoptBody;
    loreBrainstorm.propose("e1", patch("body"));

    c.setBodyResolution("adopted");
    c.abandon();
    expect(onFlush).not.toHaveBeenCalled();
    expect(onAdoptBody).not.toHaveBeenCalled();
    expect(c.proposal).toBeNull();
    expect(c.hasPendingChanges).toBe(false);
  });

  it("resetResolution clears adoptions so a superseded proposal starts clean", () => {
    const c = loreController("e1");
    c.setBodyResolution("x");
    c.setFieldResolution("bio", "y");
    c.resetResolution();
    expect(c.hasPendingChanges).toBe(false);
  });

  it("currentBody reads the host buffer via the callback, empty when unwired", () => {
    const c = loreController("e1");
    expect(c.currentBody()).toBe("");
    c.readCurrentBody = () => "live buffer text";
    expect(c.currentBody()).toBe("live buffer text");
  });

  it("clear drops the proposal so the review closes", () => {
    const c = loreController("e1");
    loreBrainstorm.propose("e1", patch("body"));
    expect(c.hasReview).toBe(true);
    c.clear();
    expect(c.proposal).toBeNull();
    expect(c.hasReview).toBe(false);
  });
});
