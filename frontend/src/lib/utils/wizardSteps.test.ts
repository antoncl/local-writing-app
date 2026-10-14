import { describe, expect, it } from "vitest";

import {
  activeSteps,
  indexOfStep,
  stepComplete,
  type WizardSnapshot,
} from "@/lib/utils/wizardSteps";

const EMPTY: WizardSnapshot = { rootFolderDraft: "", title: "", pickedFolder: "", openProjectPath: "" };

describe("activeSteps", () => {
  it("includes the root-folder step only on first run", () => {
    expect(activeSteps(true).map((s) => s.id)).toEqual([
      "start",
      "root",
      "location",
      "ai",
      "review",
      "describe",
    ]);
  });

  it("collapses to start + open_root while opening an existing project", () => {
    expect(activeSteps(true, true).map((s) => s.id)).toEqual(["start", "open_root"]);
  });

  it("keeps the open flow's steps after the root save flips needsRootFolder", () => {
    expect(activeSteps(false, true).map((s) => s.id)).toEqual(["start", "open_root"]);
  });

  it("keeps start (but not root) when a first-run session's root is already saved", () => {
    expect(activeSteps(false, false, true).map((s) => s.id)).toEqual([
      "start",
      "location",
      "ai",
      "review",
      "describe",
    ]);
  });

  it("never offers start or open_root on a plain returning-user run", () => {
    expect(activeSteps(false).map((s) => s.id)).toEqual(["location", "ai", "review", "describe"]);
  });

  it("drops the root-folder step once a default folder is configured", () => {
    expect(activeSteps(false).map((s) => s.id)).toEqual(["location", "ai", "review", "describe"]);
  });

  it("places the ai step immediately after location", () => {
    const ids = activeSteps(false).map((s) => s.id);
    expect(ids.indexOf("ai")).toBe(ids.indexOf("location") + 1);
  });

  it("ends on describe, with review just before it — Create is the last action", () => {
    const ids = activeSteps(false).map((s) => s.id);
    expect(ids[ids.length - 1]).toBe("describe");
    expect(ids.indexOf("review")).toBe(ids.indexOf("describe") - 1);
  });
});

describe("indexOfStep", () => {
  it("locates a step within the active list", () => {
    const steps = activeSteps(true);
    expect(indexOfStep(steps, "location")).toBe(2);
  });

  it("reports -1 for a step not in the active list (root, second run)", () => {
    expect(indexOfStep(activeSteps(false), "root")).toBe(-1);
  });
});

describe("stepComplete", () => {
  it("never completes the start step (it advances through its two choices)", () => {
    expect(stepComplete("start", { ...EMPTY, rootFolderDraft: "D:/writing" })).toBe(false);
  });

  it("gates open_root on a root that contains the project", () => {
    const base = { ...EMPTY, openProjectPath: "D:/Books/Saga" };
    expect(stepComplete("open_root", base)).toBe(false);
    expect(stepComplete("open_root", { ...base, rootFolderDraft: "D:/Books" })).toBe(true);
    expect(stepComplete("open_root", { ...base, rootFolderDraft: "D:/Other" })).toBe(false);
  });

  it("gates the root step on a chosen folder", () => {
    expect(stepComplete("root", EMPTY)).toBe(false);
    expect(stepComplete("root", { ...EMPTY, rootFolderDraft: "  " })).toBe(false);
    expect(stepComplete("root", { ...EMPTY, rootFolderDraft: "D:\\writing" })).toBe(true);
  });

  it("gates the location step on both a title and a folder", () => {
    expect(stepComplete("location", { ...EMPTY, title: "My Book" })).toBe(false);
    expect(stepComplete("location", { ...EMPTY, pickedFolder: "D:\\writing" })).toBe(false);
    expect(
      stepComplete("location", { ...EMPTY, title: "My Book", pickedFolder: "D:\\writing" }),
    ).toBe(true);
  });

  it("does not gate the location step on inheritance (zero ticks is a flat project)", () => {
    // A complete location step carries straight through to Create — there is no
    // separate inheritance gate.
    expect(
      stepComplete("location", { ...EMPTY, title: "Standalone", pickedFolder: "D:\\writing" }),
    ).toBe(true);
  });

  it("never gates the ai step (Off is a legal terminal policy)", () => {
    // The policy slider always holds a value, so the step is always consistent.
    expect(stepComplete("ai", EMPTY)).toBe(true);
  });

  it("never gates the review or describe steps (defaulted-and-shown / skippable)", () => {
    // Every review field inherits or defaults, and the description is optional,
    // so neither step can be internally inconsistent.
    expect(stepComplete("review", EMPTY)).toBe(true);
    expect(stepComplete("describe", EMPTY)).toBe(true);
  });
});
