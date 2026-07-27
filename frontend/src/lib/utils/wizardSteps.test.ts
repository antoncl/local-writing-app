import { describe, expect, it } from "vitest";

import {
  activeSteps,
  indexOfStep,
  stepComplete,
  type WizardSnapshot,
} from "@/lib/utils/wizardSteps";

const EMPTY: WizardSnapshot = { rootFolderDraft: "", title: "", pickedFolder: "" };

describe("activeSteps", () => {
  it("includes the root-folder step only on first run", () => {
    expect(activeSteps(true).map((s) => s.id)).toEqual(["root", "location"]);
  });

  it("drops the root-folder step once a default folder is configured", () => {
    expect(activeSteps(false).map((s) => s.id)).toEqual(["location"]);
  });
});

describe("indexOfStep", () => {
  it("locates a step within the active list", () => {
    const steps = activeSteps(true);
    expect(indexOfStep(steps, "location")).toBe(1);
  });

  it("reports -1 for a step not in the active list (root, second run)", () => {
    expect(indexOfStep(activeSteps(false), "root")).toBe(-1);
  });
});

describe("stepComplete", () => {
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
});
