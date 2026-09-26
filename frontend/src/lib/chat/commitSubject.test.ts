import { describe, expect, it } from "vitest";
import { resolveCommitSubject, type CommitSubjectRosters } from "./commitSubject";
import type { StructureDocument } from "@/lib/types";

const STRUCTURE = {
  root: { id: "root", title: "Book", children: [{ id: "n1", scene_id: "scene_1", title: "Opening", children: [] }] },
} as unknown as StructureDocument;

const ROSTERS: CommitSubjectRosters = {
  lore: [{ id: "lore_1", title: "Elara" }],
  plotlines: [{ id: "plot_line", title: "The Girl in the Ghost" }],
  cards: [{ id: "plot_card", title: "The Toll" }],
  structure: STRUCTURE,
  schema: null,
};

// A class like the real host (`editorPanes`): each opener reads `this`, so a
// detached call throws instead of passing (#2251 — the bare vi.fn fakes this
// replaced never noticed the resolver dropping the receiver).
class Openers {
  calls: Record<string, string[]> = { openLore: [], openPlotline: [], openPlotCard: [], openScene: [] };
  async openLore(id: string) { this.calls.openLore.push(id); }
  async openPlotline(id: string) { this.calls.openPlotline.push(id); }
  async openPlotCard(id: string) { this.calls.openPlotCard.push(id); }
  async openScene(id: string) { this.calls.openScene.push(id); }
}
function openers() {
  return new Openers();
}

describe("resolveCommitSubject (#2246)", () => {
  it.each([
    ["lore_1", "Elara", "openLore"],
    ["plot_line", "The Girl in the Ghost", "openPlotline"],
    ["plot_card", "The Toll", "openPlotCard"],
    ["scene_1", "Opening", "openScene"],
  ] as const)("%s resolves to its title and its document opener", async (id, title, opener) => {
    const o = openers();
    const subject = resolveCommitSubject(id, ROSTERS, o);
    expect(subject?.title).toBe(title);
    await subject!.open();
    for (const [name, ids] of Object.entries(o.calls)) expect(ids).toEqual(name === opener ? [id] : []);
  });

  it("an id in no roster (e.g. a character arc) resolves to null", () => {
    expect(resolveCommitSubject("plot_arc", ROSTERS, openers())).toBeNull();
  });
});
