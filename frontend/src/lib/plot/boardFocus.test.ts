// @vitest-environment happy-dom
// The keyboard-reach focus guard's skip-list (#909) — the board must not steal focus
// from an editable/interactive control on a pointerdown, or inline editing breaks.
import { describe, expect, it } from "vitest";
import { keepsOwnFocus } from "./boardFocus";

describe("keepsOwnFocus", () => {
  it("is true for every editable / interactive control (and nested children)", () => {
    for (const tag of ["input", "textarea", "select", "button", "a"]) {
      expect(keepsOwnFocus(document.createElement(tag))).toBe(true);
    }
    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "true");
    expect(keepsOwnFocus(editable)).toBe(true);

    // A child inside a control (e.g. an icon <i> in a <button>) still counts — closest().
    const button = document.createElement("button");
    const icon = document.createElement("i");
    button.append(icon);
    expect(keepsOwnFocus(icon)).toBe(true);
  });

  it("is false for the canvas / a plain card element / nothing — the board may take focus", () => {
    expect(keepsOwnFocus(document.createElement("div"))).toBe(false);
    expect(keepsOwnFocus(document.createElement("span"))).toBe(false);
    expect(keepsOwnFocus(null)).toBe(false);
    // A non-editable contenteditable="false" is not a text field.
    const notEditable = document.createElement("div");
    notEditable.setAttribute("contenteditable", "false");
    expect(keepsOwnFocus(notEditable)).toBe(false);
  });
});
