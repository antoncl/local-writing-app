import { describe, expect, it } from "vitest";
import { finalizeNotice } from "./finalizeNotice";

describe("finalizeNotice", () => {
  it("is empty when nothing needed rescuing", () => {
    expect(finalizeNotice({ appended_changes: [], moved_todos: 0 })).toBe("");
  });

  it("reports appended changes and moved to-dos in plain words", () => {
    expect(finalizeNotice({ appended_changes: ["A", "B"], moved_todos: 1 })).toBe(
      "Finalized. 2 changes the rewrite didn't place were added at the end. 1 to-do moved to the scene's to-do list.",
    );
  });

  it("singularises and reports either part alone", () => {
    expect(finalizeNotice({ appended_changes: ["A"], moved_todos: 0 })).toBe(
      "Finalized. 1 change the rewrite didn't place was added at the end.",
    );
    expect(finalizeNotice({ appended_changes: [], moved_todos: 3 })).toBe(
      "Finalized. 3 to-dos moved to the scene's to-do list.",
    );
  });
});
