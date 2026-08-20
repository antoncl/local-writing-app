import { describe, expect, it } from "vitest";

import { promptPreviewDrafts } from "./promptPreviewDrafts.svelte";

// ADR-0062 Amendment 2 / D1. The prompt author-preview's input values + render
// state moved out of PromptPreviewPane into this per-document store so a DETACHED
// preview — a second component instance for the same prompt — shares one record
// instead of starting empty and wiping the author's typed inputs. These tests pin
// that invariant: same id ⇒ same record; different ids stay isolated; a fresh
// record is empty and un-seeded. Distinct ids per test keep the app-wide singleton
// from leaking state between cases.

describe("promptPreviewDrafts", () => {
  it("returns the SAME record for the same document id — the detach invariant", () => {
    const docked = promptPreviewDrafts.entryFor("doc-same");
    const detached = promptPreviewDrafts.entryFor("doc-same");
    expect(detached).toBe(docked);
  });

  it("isolates records across document ids", () => {
    const a = promptPreviewDrafts.entryFor("doc-x");
    const b = promptPreviewDrafts.entryFor("doc-y");
    a.inputDrafts.tone = "warm";
    expect(b.inputDrafts.tone).toBeUndefined();
  });

  it("preserves typed drafts + scene for a second reader of the same id (docked→detached)", () => {
    const first = promptPreviewDrafts.entryFor("doc-detach");
    first.seededEntryId = "doc-detach";
    first.inputDrafts.character = "Ada";
    first.sceneId = "scene-3";

    // The detached instance keys to the same id: it sees the record already
    // seeded, so it reuses the drafts rather than re-seeding (which would wipe
    // them — the bug this slice fixes).
    const second = promptPreviewDrafts.entryFor("doc-detach");
    expect(second.seededEntryId).toBe("doc-detach");
    expect(second.inputDrafts.character).toBe("Ada");
    expect(second.sceneId).toBe("scene-3");
  });

  it("starts a fresh record empty and un-seeded", () => {
    const r = promptPreviewDrafts.entryFor("doc-fresh");
    expect(r.seededEntryId).toBeNull();
    expect(r.inputDrafts).toEqual({});
    expect(r.sceneId).toBe("");
    expect(r.result).toBeNull();
    expect(r.error).toBeNull();
    expect(r.conflicts).toEqual([]);
  });
});
