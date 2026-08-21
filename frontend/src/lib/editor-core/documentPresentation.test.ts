import { describe, expect, it } from "vitest";
import { deriveBodyShape, documentLabelFor } from "./documentPresentation";
import type { EntryTypeDefinition } from "@/lib/types";

const def = (over: Partial<EntryTypeDefinition>) => over as EntryTypeDefinition;

describe("deriveBodyShape", () => {
  it("prefers an explicit body_shape", () => {
    expect(deriveBodyShape(def({ body_shape: "code" }))).toBe("code");
    expect(deriveBodyShape(def({ body_shape: "none", has_body: true }))).toBe("none");
  });

  it("falls back through the legacy has_body / body_editor pair", () => {
    expect(deriveBodyShape(def({ has_body: false }))).toBe("none");
    expect(deriveBodyShape(def({ body_editor: "code" }))).toBe("code");
  });

  it("defaults to prose (incl. null/undefined)", () => {
    expect(deriveBodyShape(def({}))).toBe("prose");
    expect(deriveBodyShape(null)).toBe("prose");
    expect(deriveBodyShape(undefined)).toBe("prose");
  });
});

describe("documentLabelFor", () => {
  it("maps each known kind to its friendly noun", () => {
    expect(documentLabelFor("lore")).toBe("Entry");
    expect(documentLabelFor("plot_card")).toBe("Card");
    expect(documentLabelFor("prompt")).toBe("Prompt");
  });

  it("defaults unknown kinds to Scene", () => {
    expect(documentLabelFor("scene")).toBe("Scene");
    expect(documentLabelFor("totally-unknown")).toBe("Scene");
  });
});
