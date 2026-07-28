import { describe, expect, it } from "vitest";

import { PromptInputDraftsController } from "./promptInputDrafts.svelte";
import type { EditableDocument, PromptInputDefinition } from "@/lib/types";

// The declaration-side of prompt inputs, extracted from NodeEditor (#631). These
// tests pin the behaviour a refactor could silently break: the seed-on-scene-
// change gating (prompt-only, once per entry id, no fight with in-flight edits),
// the canonical serialization for save (type-matched defaults, select options,
// ref `target` passthrough), and the shared id/slug factories.

// A prompt entry masquerading as an EditableDocument — reseed only reads `.id`
// and `.inputs`, so a cast keeps the fixture minimal.
function promptScene(id: string, inputs: PromptInputDefinition[]): EditableDocument {
  return { id, inputs } as unknown as EditableDocument;
}

describe("PromptInputDraftsController", () => {
  describe("reseed", () => {
    it("seeds drafts from the entry's inputs when a prompt opens", () => {
      const c = new PromptInputDraftsController();
      c.reseed(promptScene("p1", [{ name: "tone", type: "text", label: "Tone" }]), "prompt");
      expect(c.drafts).toHaveLength(1);
      expect(c.drafts[0]).toMatchObject({ name: "tone", type: "text", label: "Tone" });
      expect(c.drafts[0].clientId).toMatch(/^__input_\d+$/);
    });

    it("re-seeds only when the entry id changes — not on every render", () => {
      const c = new PromptInputDraftsController();
      const scene = promptScene("p1", [{ name: "tone", type: "text" }]);
      c.reseed(scene, "prompt");
      const firstDrafts = c.drafts;
      // Same id, even a fresh object reference — must NOT clobber local edits.
      c.reseed(promptScene("p1", [{ name: "tone", type: "text" }]), "prompt");
      expect(c.drafts).toBe(firstDrafts);
      // A different id re-seeds.
      c.reseed(promptScene("p2", [{ name: "mood", type: "text" }]), "prompt");
      expect(c.drafts).not.toBe(firstDrafts);
      expect(c.drafts[0].name).toBe("mood");
    });

    it("does not seed for non-prompt kinds, and re-arms so the prompt seeds again", () => {
      const c = new PromptInputDraftsController();
      c.reseed(promptScene("p1", [{ name: "tone", type: "text" }]), "prompt");
      // A lore entry passes through untouched...
      c.reseed(promptScene("p1", [{ name: "tone", type: "text" }]), "lore");
      // ...and clears the seed key, so returning to the SAME prompt id re-seeds
      // rather than being skipped as "already seeded".
      c.reseed(promptScene("p1", [{ name: "mood", type: "text" }]), "prompt");
      expect(c.drafts[0].name).toBe("mood");
    });

    it("clears the seed key when the scene goes null", () => {
      const c = new PromptInputDraftsController();
      c.reseed(promptScene("p1", [{ name: "tone", type: "text" }]), "prompt");
      c.reseed(null, "prompt");
      // Re-opening the same id must seed again.
      c.reseed(promptScene("p1", [{ name: "mood", type: "text" }]), "prompt");
      expect(c.drafts[0].name).toBe("mood");
    });
  });

  describe("toCanonical", () => {
    it("round-trips a text input's name / label / required", () => {
      const c = new PromptInputDraftsController();
      c.reseed(
        promptScene("p1", [{ name: "tone", type: "text", label: "Tone", required: true }]),
        "prompt",
      );
      expect(c.toCanonical()).toEqual([
        { name: "tone", type: "text", label: "Tone", required: true },
      ]);
    });

    it("drops nameless drafts", () => {
      const c = new PromptInputDraftsController();
      c.reseed(promptScene("p1", [{ name: "", type: "text" }]), "prompt");
      expect(c.toCanonical()).toEqual([]);
    });

    it("persists a type-matched default (boolean / number), omitting empty", () => {
      const c = new PromptInputDraftsController();
      c.reseed(
        promptScene("p1", [
          { name: "flag", type: "boolean", default: true },
          { name: "count", type: "number", default: 3 },
          { name: "note", type: "text" },
        ]),
        "prompt",
      );
      const out = c.toCanonical();
      expect(out[0]).toEqual({ name: "flag", type: "boolean", default: true });
      expect(out[1]).toEqual({ name: "count", type: "number", default: 3 });
      // No default set → no `default` key at all (#24).
      expect(out[2]).toEqual({ name: "note", type: "text" });
    });

    it("emits SelectOption objects for a select, dropping blank values", () => {
      const c = new PromptInputDraftsController();
      c.reseed(
        promptScene("p1", [
          {
            name: "mood",
            type: "select",
            options: [
              { value: "calm", label: "Calm", color: "#0af" },
              { value: "", label: "blank" },
            ],
          },
        ]),
        "prompt",
      );
      expect(c.toCanonical()[0]).toEqual({
        name: "mood",
        type: "select",
        options: [{ value: "calm", label: "Calm", color: "#0af" }],
      });
    });

    it("passes a ref input's picker config through as `target`, skipping default/options", () => {
      const c = new PromptInputDraftsController();
      const target = { kinds: ["lore"], presets: [] };
      c.reseed(
        promptScene("p1", [
          { name: "who", type: "entity_ref", target: target as never, default: "ignored" },
        ]),
        "prompt",
      );
      const out = c.toCanonical()[0];
      expect(out).toEqual({ name: "who", type: "entity_ref", target });
      expect(out).not.toHaveProperty("default");
    });
  });

  describe("factories", () => {
    it("nextDraftId is monotonic and unique", () => {
      const c = new PromptInputDraftsController();
      const a = c.nextDraftId();
      const b = c.nextDraftId();
      expect(a).not.toBe(b);
      expect(a).toMatch(/^__input_\d+$/);
    });

    it("nextDraftId keeps `this` when detached (passed as a prop)", () => {
      const c = new PromptInputDraftsController();
      const mint = c.nextDraftId; // detach, as CodeBodyView receives it
      expect(() => mint()).not.toThrow();
      expect(mint()).toMatch(/^__input_\d+$/);
    });

    it("slugify lowercases, underscores separators, and prefixes a leading digit", () => {
      const c = new PromptInputDraftsController();
      expect(c.slugify("Point of View")).toBe("point_of_view");
      expect(c.slugify("  Trim Me  ")).toBe("trim_me");
      expect(c.slugify("3rd person")).toBe("input_3rd_person");
    });
  });
});
