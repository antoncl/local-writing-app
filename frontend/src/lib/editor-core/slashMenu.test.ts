import { describe, expect, it } from "vitest";
import { SLASH_PAGE_STEP, slashCommandsForKind, slashJumpIndex } from "./slashMenu";

type Command = { label: string; scope?: "manuscript" };
const table: Command = { label: "Table" };
const sceneBreak: Command = { label: "Scene break", scope: "manuscript" };
const roleplay: Command = { label: "Roleplay", scope: "manuscript" };
const commands = [table, sceneBreak, roleplay];

describe("slashCommandsForKind (#1893: unscoped for every body, scene verbs for a scene)", () => {
  it("a scene gets every command", () => {
    expect(slashCommandsForKind(commands, "manuscript")).toEqual(commands);
  });

  it("a lore body gets the unscoped commands only — no scene break, no roleplay", () => {
    expect(slashCommandsForKind(commands, "lore")).toEqual([table]);
  });
});

describe("slashJumpIndex (#2454: Page/Home/End walk the menu without wrapping)", () => {
  const key = (k: string, mods: Partial<KeyboardEvent> = {}) =>
    ({ key: k, shiftKey: false, ctrlKey: false, metaKey: false, altKey: false, ...mods });

  it("pages by SLASH_PAGE_STEP and clamps at both ends", () => {
    expect(slashJumpIndex(key("PageDown"), 0, 20)).toBe(SLASH_PAGE_STEP);
    expect(slashJumpIndex(key("PageDown"), 18, 20)).toBe(19);
    expect(slashJumpIndex(key("PageUp"), 2, 20)).toBe(0);
  });

  it("Home and End land on the first and last row", () => {
    expect(slashJumpIndex(key("Home"), 7, 9)).toBe(0);
    expect(slashJumpIndex(key("End"), 0, 9)).toBe(8);
  });

  it("leaves modified presses, other keys and an empty list to the editor", () => {
    expect(slashJumpIndex(key("Home", { shiftKey: true }), 3, 9)).toBeNull();
    expect(slashJumpIndex(key("End", { ctrlKey: true }), 3, 9)).toBeNull();
    expect(slashJumpIndex(key("ArrowDown"), 3, 9)).toBeNull();
    expect(slashJumpIndex(key("End"), 0, 0)).toBeNull();
  });
});
