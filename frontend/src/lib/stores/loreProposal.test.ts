import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoreProposalController } from "./loreProposal.svelte";
import { loreBrainstorm } from "./loreBrainstorm.svelte";
import type { EntryPatch, MetadataSchema } from "@/lib/types";

// The controller is the entry-pane end of the ADR-0046 review: it derives which
// flips a committed patch produces off the LIVE buffer the host feeds it, and
// routes an adopt back to the host's write callbacks. These tests pin the two
// things a refactor could silently break — the long_text-only derivation (a
// structured field must not leak into the body-flip list until slice 3b) and the
// three-way adopt routing (body vs fields vs both, one PUT either way, §1).

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

  it("adopt with body + fields routes to both write callbacks, not emitChange", async () => {
    const c = loreController("e1");
    const onAdoptFields = vi.fn();
    const onAdoptBody = vi.fn();
    const onEmitChange = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onAdoptBody = onAdoptBody;
    c.onEmitChange = onEmitChange;

    await c.adopt("new body", { bio: "new bio" });
    expect(onAdoptFields).toHaveBeenCalledWith({ bio: "new bio" });
    expect(onAdoptBody).toHaveBeenCalledWith("new body");
    // The body adopt carries the coalesced save (§1) — no separate emitChange.
    expect(onEmitChange).not.toHaveBeenCalled();
  });

  it("adopt with fields but no body flushes via emitChange (still one PUT)", async () => {
    const c = loreController("e1");
    const onAdoptBody = vi.fn();
    const onEmitChange = vi.fn();
    c.onAdoptFields = vi.fn();
    c.onAdoptBody = onAdoptBody;
    c.onEmitChange = onEmitChange;

    await c.adopt(null, { bio: "new bio" });
    expect(onAdoptBody).not.toHaveBeenCalled();
    expect(onEmitChange).toHaveBeenCalledTimes(1);
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
