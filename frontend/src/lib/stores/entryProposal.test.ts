import { beforeEach, describe, expect, it, vi } from "vitest";

// Mocked so the round 2 (Y1/Y8) host-simulation tests can control
// `api.createTagEntry` without hitting the network — the controller itself
// never imports `@/lib/api` (writes route through host callbacks), so this
// mock only matters to the tests that stub a host's `onAdoptFields`.
const { listTagEntries, createTagEntry } = vi.hoisted(() => ({
  listTagEntries: vi.fn(),
  createTagEntry: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ api: { listTagEntries, createTagEntry } }));

import { EntryProposalController } from "./entryProposal.svelte";
import { entryBrainstorm } from "./entryBrainstorm.svelte";
import { clearTagNodes, resolveAdoptedTagFieldValue, tagNodesStore } from "./tagNodes";
import { createTargetFor } from "@/lib/utils/pickerCreate";
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
    aliases: { name: "Aliases", type: "multi_select", options: [] },
    status: { name: "Status", type: "select", options: [] },
    title: { name: "Title", type: "text", intrinsic: true, options: [] },
    secret: { name: "Secret", type: "text", hidden: true, options: [] },
    entry_type: { name: "Type", type: "text", intrinsic: true, options: [] },
    id: { name: "ID", type: "text", intrinsic: true, hidden: true, options: [] },
    mentor: { name: "Mentor", type: "entity_ref", options: [] },
    score: { name: "Score", type: "computed", options: [] },
  },
} as unknown as MetadataSchema;

// A tag-vocabulary entity_ref_list (`create_missing` resolving to exactly one
// concrete `tag:*` type, ADR-0082 §2) alongside a plain reference list, so the
// carve-out's schema-driven predicate (`isTagVocabularyField`) has both a
// field that should flip and one that must stay excluded like any other
// `entity_ref_list`.
const tagSchema = {
  entry_types: {
    "tag:tag": { name: "Tag", kind: "tag" },
  },
  fields: {
    tags: {
      name: "Tags",
      type: "entity_ref_list",
      options: [],
      picker_config: {
        create_missing: true,
        sources: [{ kind: "tag", expr: { type: "tag:tag" } }],
      },
    },
    refs: {
      name: "Related",
      type: "entity_ref_list",
      options: [],
      picker_config: { sources: [{ kind: "lore" }] },
    },
  },
} as unknown as MetadataSchema;

const patch = (body: string | null, fields: EntryPatch["fields"] = {}): EntryPatch => ({
  body,
  fields,
});

function entryController(nodeId: string): EntryProposalController {
  const c = new EntryProposalController();
  c.nodeId = nodeId;
  c.schema = schema;
  return c;
}

describe("EntryProposalController", () => {
  beforeEach(() => {
    for (const id of ["e1", "e2"]) entryBrainstorm.clear(id);
  });

  it("is kind-agnostic — surfaces the proposal for whatever node id it is fed", () => {
    // The controller no longer gates on kind (ADR-0048 §5): it reviews whatever
    // proposal exists for its node id, and *which* kinds may launch a brainstorm
    // is the host's (NodeEditor's) policy. So it surfaces a proposal when its id
    // has one, and nothing when its id has none — regardless of the node's kind.
    entryBrainstorm.propose("e1", patch("body"));
    expect(entryController("e1").hasReview).toBe(true);
    const none = entryController("e2");
    expect(none.proposal).toBeNull();
    expect(none.hasReview).toBe(false);
  });

  it("derives one flip per proposed long_text field, paired with current value", () => {
    const c = entryController("e1");
    c.metadata = { bio: "old bio" };
    entryBrainstorm.propose("e1", patch(null, { bio: "new bio" }));
    expect(c.fields).toEqual([
      { fieldId: "bio", label: "Biography", currentValue: "old bio", proposedValue: "new bio" },
    ]);
  });

  it("keeps structured and unknown fields out of the long_text flip list", () => {
    const c = entryController("e1");
    entryBrainstorm.propose("e1", patch(null, { allegiance: "Crown", nonesuch: "x", bio: "b" }));
    expect(c.fields.map((f) => f.fieldId)).toEqual(["bio"]);
  });

  it("hasReview is true for a body-only patch AND for an all-structured one (3b)", () => {
    const bodyOnly = entryController("e1");
    entryBrainstorm.propose("e1", patch("revised", {}));
    expect(bodyOnly.hasReview).toBe(true);

    // A structured-only patch has no long_text flip, but it IS reviewable now:
    // its structured flip renders in the rail (slice 3b), so hasReview holds.
    const structuredOnly = entryController("e2");
    entryBrainstorm.propose("e2", patch(null, { allegiance: "Crown" }));
    expect(structuredOnly.fields).toEqual([]);
    expect(structuredOnly.structuredFlips.map((f) => f.fieldId)).toEqual(["allegiance"]);
    expect(structuredOnly.hasReview).toBe(true);
  });

  it("reacts to the live-metadata feed — the flip's current value tracks the buffer", () => {
    const c = entryController("e1");
    c.metadata = { bio: "first" };
    entryBrainstorm.propose("e1", patch(null, { bio: "proposed" }));
    expect(c.fields[0].currentValue).toBe("first");
    c.metadata = { bio: "edited since" };
    expect(c.fields[0].currentValue).toBe("edited since");
  });

  it("hasPendingChanges tracks the accumulated resolution", () => {
    const c = entryController("e1");
    expect(c.hasPendingChanges).toBe(false);
    c.setFieldResolution("bio", "adopted");
    expect(c.hasPendingChanges).toBe(true);
    c.setFieldResolution("bio", null); // declined back to current
    expect(c.hasPendingChanges).toBe(false);
    c.setBodyResolution("adopted body");
    expect(c.hasPendingChanges).toBe(true);
  });

  it("commit applies adopted body + fields and posts exactly once (one PUT)", async () => {
    const c = entryController("e1");
    const onAdoptFields = vi.fn();
    const onAdoptBody = vi.fn();
    const onFlush = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onAdoptBody = onAdoptBody;
    c.onEmitChange = vi.fn();
    c.onFlush = onFlush;
    entryBrainstorm.propose("e1", patch("new body", { bio: "new bio" }));

    c.setBodyResolution("new body");
    c.setFieldResolution("bio", "new bio");
    await c.commit();

    expect(onAdoptFields).toHaveBeenCalledWith({ bio: "new bio" });
    expect(onAdoptBody).toHaveBeenCalledWith("new body");
    // The single explicit post that ends the transaction — body + metadata land
    // in ONE PUT (ADR-0046 §1), not per-unit and not via a debounce.
    expect(onFlush).toHaveBeenCalledTimes(1);
    // Committing ends the review and clears the accumulation.
    expect(c.proposal).toBeNull();
    expect(c.hasPendingChanges).toBe(false);
  });

  it("keeps the review open when the post fails — no dropped patch", async () => {
    const c = entryController("e1");
    c.onAdoptBody = vi.fn();
    c.onEmitChange = vi.fn();
    c.onFlush = vi.fn().mockResolvedValue(false); // e.g. a changed-on-disk 409
    entryBrainstorm.propose("e1", patch("new body"));

    c.setBodyResolution("new body");
    const ok = await c.commit();

    expect(ok).toBe(false);
    // The transaction isn't "done" until the write lands — the proposal and its
    // adoption stay so the author can retry, instead of losing the patch.
    expect(c.proposal).not.toBeNull();
    expect(c.hasPendingChanges).toBe(true);
  });

  it("commit with fields but no body still posts once", async () => {
    const c = entryController("e1");
    const onAdoptBody = vi.fn();
    const onEmitChange = vi.fn();
    const onFlush = vi.fn();
    c.onAdoptFields = vi.fn();
    c.onAdoptBody = onAdoptBody;
    c.onEmitChange = onEmitChange;
    c.onFlush = onFlush;
    entryBrainstorm.propose("e1", patch(null, { bio: "new bio" }));

    c.setFieldResolution("bio", "new bio");
    await c.commit();

    expect(onAdoptBody).not.toHaveBeenCalled();
    expect(onEmitChange).toHaveBeenCalled();
    expect(onFlush).toHaveBeenCalledTimes(1);
  });

  it("acceptFields adopts only the shown long_text fields — never body or structured (S5-next replace)", async () => {
    // The `replace` review (ReplaceReviewCard) renders only the long_text `fields`.
    // acceptFields is what its Replace button drives, and it must commit EXACTLY
    // those — so a whole-field replace can't write a value the author never saw:
    // not the body (a scene's manuscript prose), not an unshown structured flip.
    const c = entryController("e1");
    c.metadata = { bio: "old bio", allegiance: "order" };
    const onAdoptFields = vi.fn();
    const onAdoptBody = vi.fn();
    const onFlush = vi.fn().mockResolvedValue(true);
    c.onAdoptFields = onAdoptFields;
    c.onAdoptBody = onAdoptBody;
    c.onEmitChange = vi.fn();
    c.onFlush = onFlush;
    // A patch proposing a body, a long_text field, AND a structured field — the
    // shape a non-compliant `replace` model could return.
    entryBrainstorm.propose("e1", patch("REWRITTEN PROSE", { bio: "new bio", allegiance: "chaos" }));

    c.acceptFields();
    await c.commit();

    // Only the long_text `bio` (shown in the card) is written; the body and the
    // structured `allegiance` are dropped.
    expect(onAdoptFields).toHaveBeenCalledWith({ bio: "new bio" });
    expect(onAdoptBody).not.toHaveBeenCalled();
    expect(onFlush).toHaveBeenCalledTimes(1);
    expect(c.proposal).toBeNull();
  });

  it("commit with nothing adopted is a plain dismiss — no write, no post", async () => {
    const c = entryController("e1");
    const onAdoptFields = vi.fn();
    const onAdoptBody = vi.fn();
    const onFlush = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onAdoptBody = onAdoptBody;
    c.onFlush = onFlush;
    entryBrainstorm.propose("e1", patch("body"));

    await c.commit(); // nothing resolved → "Close"
    expect(onAdoptFields).not.toHaveBeenCalled();
    expect(onAdoptBody).not.toHaveBeenCalled();
    expect(onFlush).not.toHaveBeenCalled();
    expect(c.proposal).toBeNull();
  });

  it("abandon discards without writing, and resets the accumulation", () => {
    const c = entryController("e1");
    const onFlush = vi.fn();
    const onAdoptBody = vi.fn();
    c.onFlush = onFlush;
    c.onAdoptBody = onAdoptBody;
    entryBrainstorm.propose("e1", patch("body"));

    c.setBodyResolution("adopted");
    c.abandon();
    expect(onFlush).not.toHaveBeenCalled();
    expect(onAdoptBody).not.toHaveBeenCalled();
    expect(c.proposal).toBeNull();
    expect(c.hasPendingChanges).toBe(false);
  });

  it("resetResolution clears adoptions so a superseded proposal starts clean", () => {
    const c = entryController("e1");
    c.setBodyResolution("x");
    c.setFieldResolution("bio", "y");
    c.resetResolution();
    expect(c.hasPendingChanges).toBe(false);
  });

  it("currentBody reads the host buffer via the callback, empty when unwired", () => {
    const c = entryController("e1");
    expect(c.currentBody()).toBe("");
    c.readCurrentBody = () => "live buffer text";
    expect(c.currentBody()).toBe("live buffer text");
  });

  it("clear drops the proposal so the review closes", () => {
    const c = entryController("e1");
    entryBrainstorm.propose("e1", patch("body"));
    expect(c.hasReview).toBe(true);
    c.clear();
    expect(c.proposal).toBeNull();
    expect(c.hasReview).toBe(false);
  });
});

describe("EntryProposalController — structured field flips (slice 3b)", () => {
  beforeEach(() => {
    for (const id of ["e1", "e2"]) entryBrainstorm.clear(id);
  });

  it("derives one atomic flip per structured field, was=proposed / now=current", () => {
    const c = entryController("e1");
    c.metadata = { allegiance: "Rebels", active: false };
    entryBrainstorm.propose("e1", patch(null, { allegiance: "Crown", active: true, aliases: ["A"] }));
    expect(c.structuredFlips).toEqual([
      { fieldId: "allegiance", was: "Crown", now: "Rebels" },
      { fieldId: "active", was: true, now: false },
      // A field absent from current metadata reads `now: null`, not undefined.
      { fieldId: "aliases", was: ["A"], now: null },
    ]);
  });

  it("excludes body/long_text, computed, entity_ref, hidden, id/entry_type, and unknown", () => {
    const c = entryController("e1");
    entryBrainstorm.propose(
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
    const c = entryController("e1");
    // The host folds title/status into the metadata view, so the flip's `now`
    // reads the entry's real title even though title lives off `metadata`.
    c.metadata = { title: "Old Name" };
    entryBrainstorm.propose("e1", patch(null, { title: "New Name" }));
    expect(c.structuredFlips).toEqual([{ fieldId: "title", was: "New Name", now: "Old Name" }]);
    expect(c.hasReview).toBe(true);
  });

  it("structuredCompareFields mirrors the flips as MetadataPanel's {was,now} map", () => {
    const c = entryController("e1");
    c.metadata = { allegiance: "Rebels" };
    entryBrainstorm.propose("e1", patch(null, { allegiance: "Crown" }));
    expect(c.structuredCompareFields).toEqual({ allegiance: { was: "Crown", now: "Rebels" } });
  });

  it("toggleStructured flips adoption and hasPendingChanges tracks it", () => {
    const c = entryController("e1");
    entryBrainstorm.propose("e1", patch(null, { allegiance: "Crown" }));
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
    const c = entryController("e1");
    const onAdoptFields = vi.fn();
    const onFlush = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onEmitChange = vi.fn();
    c.onFlush = onFlush;
    entryBrainstorm.propose("e1", patch(null, { allegiance: "Crown", active: true }));

    c.toggleStructured("allegiance"); // adopt one, leave `active` declined
    await c.commit();

    expect(onAdoptFields).toHaveBeenCalledWith({ allegiance: "Crown" });
    expect(onFlush).toHaveBeenCalledTimes(1);
    expect(c.proposal).toBeNull();
  });

  it("adopting a proposal that CLEARS a field writes the null (boolean resolution)", async () => {
    const c = entryController("e1");
    const onAdoptFields = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onEmitChange = vi.fn();
    c.onFlush = vi.fn();
    c.metadata = { allegiance: "Rebels" };
    entryBrainstorm.propose("e1", patch(null, { allegiance: null }));

    c.toggleStructured("allegiance");
    await c.commit();
    // The adoption is a boolean, so a proposed `null` still writes — it is not
    // mistaken for "declined" the way a null-valued resolution would be.
    expect(onAdoptFields).toHaveBeenCalledWith({ allegiance: null });
  });

  it("commit coalesces long_text + structured into ONE onAdoptFields call", async () => {
    const c = entryController("e1");
    const onAdoptFields = vi.fn();
    const onFlush = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onAdoptBody = vi.fn();
    c.onEmitChange = vi.fn();
    c.onFlush = onFlush;
    entryBrainstorm.propose("e1", patch("new body", { bio: "new bio", allegiance: "Crown" }));

    c.setBodyResolution("new body");
    c.setFieldResolution("bio", "new bio");
    c.toggleStructured("allegiance");
    await c.commit();

    expect(onAdoptFields).toHaveBeenCalledTimes(1);
    expect(onAdoptFields).toHaveBeenCalledWith({ bio: "new bio", allegiance: "Crown" });
    expect(onFlush).toHaveBeenCalledTimes(1);
  });

  it("reads the current side of off-metadata fields (status) from the fed view", () => {
    const c = entryController("e1");
    // NodeEditor feeds `{ ...metadata, title, status }`; a status flip's `now`
    // must reflect that, not read as unset (the bug the review caught).
    c.metadata = { status: "draft" };
    entryBrainstorm.propose("e1", patch(null, { status: "published" }));
    expect(c.structuredFlips).toEqual([{ fieldId: "status", was: "published", now: "draft" }]);
  });

  it("commit folds an adopted title/status into the fields patch (host routes them out)", async () => {
    const c = entryController("e1");
    const onAdoptFields = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onEmitChange = vi.fn();
    c.onFlush = vi.fn();
    c.metadata = { title: "Old", status: "draft" };
    entryBrainstorm.propose("e1", patch(null, { title: "New", status: "published" }));

    c.toggleStructured("title");
    c.toggleStructured("status");
    await c.commit();
    // The controller just passes them through; NodeEditor's onAdoptFields routes
    // title/status to their shell state so the save's rename/status apply.
    expect(onAdoptFields).toHaveBeenCalledWith({ title: "New", status: "published" });
  });

  it("resetResolution clears structured adoptions so a superseded proposal is clean", () => {
    const c = entryController("e1");
    entryBrainstorm.propose("e1", patch(null, { allegiance: "Crown" }));
    c.toggleStructured("allegiance");
    c.resetResolution();
    expect(c.isStructuredAdopted("allegiance")).toBe(false);
    expect(c.hasPendingChanges).toBe(false);
  });
});

describe("EntryProposalController — tag-vocabulary flip (ADR-0082 §2 / #1797)", () => {
  beforeEach(() => {
    for (const id of ["e1", "e2"]) entryBrainstorm.clear(id);
  });

  function tagController(nodeId: string): EntryProposalController {
    const c = new EntryProposalController();
    c.nodeId = nodeId;
    c.schema = tagSchema;
    return c;
  }

  it("renders a tags flip, its value possibly MIXING ids and unresolved titles — a plain ref list stays excluded", () => {
    // The backend only resolves a title matching an EXISTING tag; an unknown
    // one rides through as a plain string (never minted at validation) — the
    // controller passes it through untouched either way, agnostic to which.
    const c = tagController("e1");
    c.metadata = { tags: ["tag_old"], refs: ["lore_x"] };
    entryBrainstorm.propose("e1", patch(null, { tags: ["tag_new1", "Brand New Title"], refs: ["lore_y"] }));
    expect(c.structuredFlips).toEqual([
      { fieldId: "tags", was: ["tag_new1", "Brand New Title"], now: ["tag_old"] },
    ]);
  });

  it("adopting a tags flip hands the host the value AS-IS — the controller never resolves/mints", async () => {
    // Resolving a still-bare title to an id (finding or minting) is the
    // HOST's job on ACCEPT (`onAdoptFields`, NodeEditor.svelte /
    // `resolveAdoptedTagFieldValue`, tagNodes.ts) — the controller only
    // accumulates the resolution and hands off the raw proposed value.
    const c = tagController("e1");
    const onAdoptFields = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onEmitChange = vi.fn();
    c.onFlush = vi.fn();
    entryBrainstorm.propose("e1", patch(null, { tags: ["tag_new1", "Brand New Title"] }));

    c.toggleStructured("tags");
    await c.commit();

    expect(onAdoptFields).toHaveBeenCalledWith({ tags: ["tag_new1", "Brand New Title"] });
  });

  it("commit awaits an async onAdoptFields before flushing — so a resolve-then-mint step lands first", async () => {
    const c = tagController("e1");
    const order: string[] = [];
    c.onAdoptFields = async () => {
      order.push("adopt-start");
      await Promise.resolve();
      order.push("adopt-end");
    };
    c.onEmitChange = () => order.push("emit");
    c.onFlush = async () => {
      order.push("flush");
      return true;
    };
    entryBrainstorm.propose("e1", patch(null, { tags: ["Brand New Title"] }));
    c.toggleStructured("tags");
    await c.commit();
    expect(order).toEqual(["adopt-start", "adopt-end", "emit", "flush"]);
  });

  it("proposesTagField flags a proposal touching a tag-vocabulary field, not a plain ref list", () => {
    const plainRef = tagController("e1");
    entryBrainstorm.propose("e1", patch(null, { refs: ["lore_y"] }));
    expect(plainRef.proposesTagField).toBe(false);

    const tagField = tagController("e2");
    entryBrainstorm.propose("e2", patch(null, { tags: ["tag_new1"] }));
    expect(tagField.proposesTagField).toBe(true);
  });

  it("proposesTagField is false with no proposal", () => {
    expect(tagController("e1").proposesTagField).toBe(false);
  });

  it("Y1: a failed onAdoptFields keeps the review open, writes nothing, and surfaces the error", async () => {
    const c = tagController("e1");
    const onEmitChange = vi.fn();
    const onFlush = vi.fn();
    c.onAdoptFields = vi.fn().mockRejectedValue(new Error("network down"));
    c.onEmitChange = onEmitChange;
    c.onFlush = onFlush;
    entryBrainstorm.propose("e1", patch(null, { tags: ["A", "B", "C"] }));
    c.toggleStructured("tags");

    const ok = await c.commit();

    expect(ok).toBe(false);
    // The whole commit aborts at the failed step — no emit, no flush (a tag
    // that DID mint before the failure is still a real node; there's simply
    // no PUT for this field's value).
    expect(onEmitChange).not.toHaveBeenCalled();
    expect(onFlush).not.toHaveBeenCalled();
    expect(c.commitError).toBe("network down");
    // The review stays open with the flip still pending, so a retry is just
    // clicking Done again.
    expect(c.proposal).not.toBeNull();
    expect(c.isStructuredAdopted("tags")).toBe(true);
  });

  it("commitError clears on a fresh commit attempt and on resetResolution", async () => {
    const c = tagController("e1");
    c.onAdoptFields = vi.fn().mockRejectedValue(new Error("boom"));
    c.onEmitChange = vi.fn();
    c.onFlush = vi.fn();
    entryBrainstorm.propose("e1", patch(null, { tags: ["A"] }));
    c.toggleStructured("tags");
    await c.commit();
    expect(c.commitError).toBe("boom");

    c.resetResolution();
    expect(c.commitError).toBeNull();
  });
});

describe("EntryProposalController — host accept/reject rule (ADR-0082 §2, round 2 Y8)", () => {
  // A minimal stand-in for NodeEditor.svelte's `onAdoptFields` (#1797): for
  // each field whose picker_config is a tag vocabulary, resolve its value
  // through the SAME `resolveAdoptedTagFieldValue` the real host calls. Not a
  // mock of the host — the real resolve/mint function, with only `api`
  // mocked underneath — so this proves the CONTRACT (reject creates nothing,
  // accept mints once per new title) end to end from the controller's own
  // commit(), not just that a stub was invoked.
  function wireHost(c: EntryProposalController, schema: MetadataSchema, createLayerId: string | null): void {
    c.onAdoptFields = async (fields) => {
      const next = { ...fields };
      for (const fieldId of Object.keys(next)) {
        const field = schema.fields[fieldId];
        const target = field ? createTargetFor(field.picker_config, schema) : null;
        if (target?.kind !== "tag") continue;
        next[fieldId] = await resolveAdoptedTagFieldValue(next[fieldId], target.entryType, createLayerId);
      }
    };
  }

  function tagController(nodeId: string): EntryProposalController {
    const c = new EntryProposalController();
    c.nodeId = nodeId;
    c.schema = tagSchema;
    return c;
  }

  beforeEach(() => {
    for (const id of ["e1", "e2"]) entryBrainstorm.clear(id);
    listTagEntries.mockReset();
    createTagEntry.mockReset();
    clearTagNodes();
  });

  it("rejecting a tag flip never calls api.createTagEntry", async () => {
    const c = tagController("e1");
    wireHost(c, tagSchema, null);
    c.onEmitChange = vi.fn();
    c.onFlush = vi.fn();
    entryBrainstorm.propose("e1", patch(null, { tags: ["Brand New Title"] }));
    // Deliberately NOT toggled adopted — "Close"/discard, not accept.

    await c.commit();

    expect(createTagEntry).not.toHaveBeenCalled();
  });

  it("accepting a tag flip mints once per new title, resolving an already-known id without a call", async () => {
    // Seed the roster with an already-resolved id (the validator's own kind
    // of resolution, from an EXISTING tag) alongside two bare new titles.
    tagNodesStore.set([{ id: "tag_known", title: "Known", entry_type: "tag:tag", metadata: {} }]);
    const c = tagController("e1");
    wireHost(c, tagSchema, "layer_1");
    c.onEmitChange = vi.fn();
    c.onFlush = vi.fn();
    createTagEntry
      .mockResolvedValueOnce({ id: "tag_a", title: "Alpha", entry_type: "tag:tag", metadata: {} })
      .mockResolvedValueOnce({ id: "tag_b", title: "Beta", entry_type: "tag:tag", metadata: {} });
    entryBrainstorm.propose("e1", patch(null, { tags: ["tag_known", "Alpha", "Beta"] }));
    c.toggleStructured("tags");

    const ok = await c.commit();

    expect(ok).toBe(true);
    expect(createTagEntry).toHaveBeenCalledTimes(2);
    expect(createTagEntry).toHaveBeenNthCalledWith(1, "Alpha", "tag:tag", null, "layer_1");
    expect(createTagEntry).toHaveBeenNthCalledWith(2, "Beta", "tag:tag", null, "layer_1");
  });
});

describe("EntryProposalController — judge axis + whole-version decide (#710)", () => {
  beforeEach(() => {
    for (const id of ["e1", "e2"]) entryBrainstorm.clear(id);
  });

  it("opens on the interleaved diff and toggles a single whole version", () => {
    const c = entryController("e1");
    expect(c.view).toBe("both");
    c.setView("was");
    expect(c.view).toBe("was");
    c.setView("now");
    expect(c.view).toBe("now");
  });

  it("toggleView flips a version against Both — one gesture in and out", () => {
    const c = entryController("e1");
    c.toggleView("was"); // into the proposed whole
    expect(c.view).toBe("was");
    c.toggleView("was"); // same key leaves it
    expect(c.view).toBe("both");
    c.toggleView("now"); // the other whole
    expect(c.view).toBe("now");
    c.toggleView("was"); // switching wholes does not pass through Both
    expect(c.view).toBe("was");
  });

  it("resets the view to Both when a proposal is superseded", () => {
    const c = entryController("e1");
    c.setView("was");
    c.resetResolution();
    expect(c.view).toBe("both");
  });

  it("fieldSide picks the rail's whole side — 'was' only in the Proposed view", () => {
    // The structured rail follows the toggle (#710): reading Current or Both
    // shows the entry's own values ('now'); only Proposed shows the AI's ('was').
    const c = entryController("e1");
    expect(c.fieldSide()).toBe("now"); // both
    c.setView("now");
    expect(c.fieldSide()).toBe("now");
    c.setView("was");
    expect(c.fieldSide()).toBe("was");
  });

  it("acceptAll marks the body, every long_text, and every structured flip adopted", () => {
    const c = entryController("e1");
    c.metadata = { bio: "old bio", allegiance: "Rebels" };
    entryBrainstorm.propose(
      "e1",
      patch("new body", { bio: "new bio", allegiance: "Crown" }),
    );
    expect(c.hasPendingChanges).toBe(false);

    c.acceptAll();

    expect(c.resolvedBody).toBe("new body");
    expect(c.resolvedText).toEqual({ bio: "new bio" });
    expect(c.isStructuredAdopted("allegiance")).toBe(true);
    expect(c.hasPendingChanges).toBe(true);
  });

  it("acceptAll leaves resolvedBody null for a fields-only patch", () => {
    const c = entryController("e1");
    entryBrainstorm.propose("e1", patch(null, { allegiance: "Crown" }));
    c.acceptAll();
    expect(c.resolvedBody).toBeNull();
    expect(c.isStructuredAdopted("allegiance")).toBe(true);
  });

  it("acceptAll then commit writes the WHOLE candidate in one PUT", async () => {
    const c = entryController("e1");
    const onAdoptFields = vi.fn();
    const onAdoptBody = vi.fn();
    const onFlush = vi.fn();
    c.onAdoptFields = onAdoptFields;
    c.onAdoptBody = onAdoptBody;
    c.onEmitChange = vi.fn();
    c.onFlush = onFlush;
    c.metadata = { bio: "old", allegiance: "Rebels" };
    entryBrainstorm.propose("e1", patch("new body", { bio: "new bio", allegiance: "Crown" }));

    c.acceptAll();
    await c.commit();

    // The whole-adopt lands as the SAME single flush as a hand-picked commit —
    // body + every field in one PUT, not a bespoke bulk-write path.
    expect(onAdoptBody).toHaveBeenCalledWith("new body");
    expect(onAdoptFields).toHaveBeenCalledTimes(1);
    expect(onAdoptFields).toHaveBeenCalledWith({ bio: "new bio", allegiance: "Crown" });
    expect(onFlush).toHaveBeenCalledTimes(1);
    expect(c.proposal).toBeNull();
  });

  it("acceptAll is a no-op with no proposal (nothing to take)", () => {
    const c = entryController("e2");
    c.acceptAll();
    expect(c.hasPendingChanges).toBe(false);
  });
});
