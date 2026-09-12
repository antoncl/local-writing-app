import { describe, expect, it } from "vitest";
import { slashCommandsForKind } from "./slashMenu";

type Command = { label: string; scope?: "manuscript" };
const table: Command = { label: "Table" };
const sceneBreak: Command = { label: "Scene break", scope: "manuscript" };
const roleplay: Command = { label: "Roleplay", scope: "manuscript" };
const commands = [table, sceneBreak, roleplay];

describe("slashCommandsForKind (#1893: formatting for every body, scene verbs for a scene)", () => {
  it("a scene gets every command", () => {
    expect(slashCommandsForKind(commands, "manuscript")).toEqual(commands);
  });

  it("a lore body gets the unscoped commands only — no scene break, no roleplay", () => {
    expect(slashCommandsForKind(commands, "lore")).toEqual([table]);
  });
});
