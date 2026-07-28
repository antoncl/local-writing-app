import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoreProposalController } from "./loreProposal.svelte";
import { loreBrainstorm } from "./loreBrainstorm.svelte";
import type { EntryPatch, MetadataSchema } from "@/lib/types";

// The controller is the entry-pane end of the ADR-0046 review: it derives which
// flips a committed patch produces off the LIVE buffer the host feeds it, and
// owns the review as a frozen transaction — accepting a unit only accumulates
// resolution (never a write), and `commit()` issues ONE explicit post (#634).
// These tests pin what a refactor could silently break: the split derivation
// (long_text → prose run-diff `fields`; structured → atomic `structuredFlips`,
// slice 3b), the exclusions (body/computed/refs/intrinsic never flip as
// structured), and the transaction (accumulate → single flush on commit, no
// write on abandon, reset on a superseded proposal).

// Minimal schema spanning the dispatch: a long_text (prose run-diff), several
// structured types (atomic flip), the adoptable intrinsic `title`, and each
// exclusion (computed / entity_ref / hidden / structural id+entry_type). Cast —
// the controller only reads `.fields[id].type/name/hidden`.
const schema = {
  entry_types: {},
  fields: {
    bio: { name: "Biography", type: "long_text", options: [] },
    allegiance: { name: "Allegiance", type: "select", options: [] },
    active: { name: "Active", type: "boolean", options: [] },
    aliases: { name: "Aliases", type: "tags", options: [] },
    status: { name: "Status", type: "select", options: [] },
    title: { name: "Title", type: "text", intrinsic: true, options: [] },
    secret: { name: "Secret", type: "text", hidden: true, options: [] },
    entry_type: { name: "Type", type: "text", intrinsic: true, options: [] },
    id: { name: "ID", type: "text", intrinsic: true, hidden: true, options: [] },
    mentor: { name: "Mentor", type: "entity_ref", options: [] },
    score: { name: "Score", type: "computed", options: [] },
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

  it("keeps structured and unknown fields out of the long_text flip list", () => {
    const c = loreController("e1");
    loreBrainstorm.propose("e1", patch(null, { allegiance: "Crown", nonesuch: "x", bio: "b" }));
    expect(c.fields.map((f) => f.fieldId)).toEqual(["bio"]);
  });

  it("hasReview is true for a body-only patch AND for an all-structured one (3b)", () => {
    const bodyOnly = loreController("e1");
    loreBrainstorm.propose("e1", patch("revised", {}));
    expect(bodyOnly.hasReview).toBe(true);

    // A structured-only patch has no long_text flip, but it IS reviewable now:
    // its structured flip renders in the rail (slice 3b), so hasReview holds.
    const structuredOnly = loreController("e2");
    loreBrainstorm.propose("e2", patch(null, { allegiance: "Crown" }));
    expect(structuredOnly.fields).toEqual([]);
    expect(structuredOnly.structuredFlips.map((f) => f.fieldId)).toEqual(["allegiance"]);
    expect(structuredOnly.hasReview).toBe(true);
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

  it("keeps the review open when the post fails — no dropped patch", async () => {
    const c = loreController("e1");
    c.onAdoptBody = vi.fn();
    c.onEmitChange = vi.fn();
    c.onFlush = vi.fn().mockResolvedValue(false); // e.g. a changed-on-disk 409
    loreBrainstorm.propose("e1", patch("new body"));

    c.setBodyResolution("new body");
    const ok = await c.commit();

    expect(ok).toBe(false);
    // The transaction isn't "done" until the write lands — the proposal and its
    // adoption stay so the author can retry, instead of losing the patch.
    expect(c.proposal).not.toBeNull();
    expect(c.hasPendingChanges).toBe(true);
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

describe("LoreProposalController — structured field flips (slice 3b)", () => {
  beforeEach(() => {
    for (const id of ["e1", "e2"]) loreBrainstorm.clear(id);
  });

  it("derives one atomic flip per structured field, was=proposed / now=current", () => {
    const c = loreController("e1");
    c.metadata = { allegiance: "Rebels", active: false };
    loreBrainstorm.propose("e1", patch(null, { allegiance: "Crown", active: true, aliases: ["A"] }));
    expect(c.structuredFlips).toEqual([
      { fieldId: "allegiance", was: "Crown", now: "Rebels" },
      { fieldId: "active", was: true, now: false },
      // A field absent from current metadata reads `now: null`, not undefined.
      { fieldId: "aliases", was: ["A"], now: null },
    ]);
  });

  it("excludes body/long_text, computed, entity_ref, hidden, id/entry_type, and unknown", () => {
    const c = loreController("e1");
    loreBrainstorm.propose(
      "e1",
      patch("a body", {
        bio: "prose",
        score: 9,
        mentor: "id-1",
        secret: "leak",
        id: "x1",
        entry_type: "villain",
        nonesuch: "x",
        allegiance: "Crown",
      }),
    );
    // Only the real structured field survives; long_text stays in `fields`.
    expect(c.structuredFlips.map((f) => f.fieldId)).toEqual(["allegiance"]);
    expect(c.fields.map((f) => f.fieldId)).toEqual(["bio"]);
  });

  it("flips an AI-proposed title rename (intrinsic but adoptable), now=current", () => {
    const c = loreController("e1");
    // The host folds title/status into the metadata view, so the flip's `now`
    // reads the entry's real title even though title lives off `metadata`.
    c.metadata = { title: "Old Name" };
    loreBrainstorm.propose("e1", patch(null, { title: "New Name" }));
    expect(c.structuredFlips).toEqual([{ fieldId: "title", was: "New Name", now: "Old Name" }]);
    expect(c.hasReview).toBe(true);
  });

  it("structuredCompareFields mirrors the flips as MetadataPanel's {was,now} map", () => {
    const c = loreController("e1");
    c.metadata = { allegiance: "Rebels" };
    loreBrainstorm.propose("e1", patch(null, { allegiance: "Crown" }));
    expect(c.structuredCompareFields).toEqual({ allegiance: { was: "Crown", now: "Rebels" } });
  });

  it("toggleStructured flips adoption and hasPendingChanges tracks it", () => {
    const c = loreController("e1");
    loreBrainstorm.propose("e1", patch(null, { allegiance: "Crown" }));
    expect(c.isStructuredAdopted("allegiance")).toBe(false);
    expect(c.hasPendingChanges).toBe(false);

    c.toggleStructured("allegiance");
    expect(c.isStructuredAdopted("allegiance")).toBe(true);
    expect(c.hasPendingChanges).toBe(true);

    c.toggleStructured("allegiance"); // declined back
    expect(c.isStructuredAdopted("allegiance")).toBe(false);
    expect(c.hasPendingChanges).toBe(false);
  });

  it("commit folds only ADOPTED structured values into the one fields patch", async () => {
    const c = loreController("e1");
    const onAdoptFields = vi.fn();
    const onFlush = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onEmitChange = vi.fn();
    c.onFlush = onFlush;
    loreBrainstorm.propose("e1", patch(null, { allegiance: "Crown", active: true }));

    c.toggleStructured("allegiance"); // adopt one, leave `active` declined
    await c.commit();

    expect(onAdoptFields).toHaveBeenCalledWith({ allegiance: "Crown" });
    expect(onFlush).toHaveBeenCalledTimes(1);
    expect(c.proposal).toBeNull();
  });

  it("adopting a proposal that CLEARS a field writes the null (boolean resolution)", async () => {
    const c = loreController("e1");
    const onAdoptFields = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onEmitChange = vi.fn();
    c.onFlush = vi.fn();
    c.metadata = { allegiance: "Rebels" };
    loreBrainstorm.propose("e1", patch(null, { allegiance: null }));

    c.toggleStructured("allegiance");
    await c.commit();
    // The adoption is a boolean, so a proposed `null` still writes — it is not
    // mistaken for "declined" the way a null-valued resolution would be.
    expect(onAdoptFields).toHaveBeenCalledWith({ allegiance: null });
  });

  it("commit coalesces long_text + structured into ONE onAdoptFields call", async () => {
    const c = loreController("e1");
    const onAdoptFields = vi.fn();
    const onFlush = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onAdoptBody = vi.fn();
    c.onEmitChange = vi.fn();
    c.onFlush = onFlush;
    loreBrainstorm.propose("e1", patch("new body", { bio: "new bio", allegiance: "Crown" }));

    c.setBodyResolution("new body");
    c.setFieldResolution("bio", "new bio");
    c.toggleStructured("allegiance");
    await c.commit();

    expect(onAdoptFields).toHaveBeenCalledTimes(1);
    expect(onAdoptFields).toHaveBeenCalledWith({ bio: "new bio", allegiance: "Crown" });
    expect(onFlush).toHaveBeenCalledTimes(1);
  });

  it("reads the current side of off-metadata fields (status) from the fed view", () => {
    const c = loreController("e1");
    // NodeEditor feeds `{ ...metadata, title, status }`; a status flip's `now`
    // must reflect that, not read as unset (the bug the review caught).
    c.metadata = { status: "draft" };
    loreBrainstorm.propose("e1", patch(null, { status: "published" }));
    expect(c.structuredFlips).toEqual([{ fieldId: "status", was: "published", now: "draft" }]);
  });

  it("commit folds an adopted title/status into the fields patch (host routes them out)", async () => {
    const c = loreController("e1");
    const onAdoptFields = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onEmitChange = vi.fn();
    c.onFlush = vi.fn();
    c.metadata = { title: "Old", status: "draft" };
    loreBrainstorm.propose("e1", patch(null, { title: "New", status: "published" }));

    c.toggleStructured("title");
    c.toggleStructured("status");
    await c.commit();
    // The controller just passes them through; NodeEditor's onAdoptFields routes
    // title/status to their shell state so the save's rename/status apply.
    expect(onAdoptFields).toHaveBeenCalledWith({ title: "New", status: "published" });
  });

  it("resetResolution clears structured adoptions so a superseded proposal is clean", () => {
    const c = loreController("e1");
    loreBrainstorm.propose("e1", patch(null, { allegiance: "Crown" }));
    c.toggleStructured("allegiance");
    c.resetResolution();
    expect(c.isStructuredAdopted("allegiance")).toBe(false);
    expect(c.hasPendingChanges).toBe(false);
  });
});
