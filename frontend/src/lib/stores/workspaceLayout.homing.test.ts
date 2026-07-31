// Region homing (#757) — where ensureVisible drops a not-yet-placed region. The
// plot board is a large SvelteFlow canvas, so it must home to the CENTRAL editor
// group like the open documents, not the side column. HOMES drives this (and
// doubles as the known-region allowlist), so an accidental removal would silently
// send the board back to the narrow side and stop it persisting.
import { beforeEach, describe, expect, it } from "vitest";
import { workspaceLayout } from "./workspaceLayout.svelte";
import { G_EDITOR, G_SIDE } from "./workspaceLayout.serialize";

describe("workspaceLayout region homing (#757)", () => {
  beforeEach(() => workspaceLayout.reset());

  it("homes the plot board to the central editor group", () => {
    workspaceLayout.ensureVisible("plotEditor");
    expect(workspaceLayout.groupOf("plotEditor")?.id).toBe(G_EDITOR);
  });

  it("still homes a side region (lore) to the side column", () => {
    workspaceLayout.ensureVisible("lore");
    expect(workspaceLayout.groupOf("lore")?.id).toBe(G_SIDE);
  });
});
