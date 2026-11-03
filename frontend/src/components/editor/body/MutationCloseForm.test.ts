// @vitest-environment happy-dom
// #73: the close picker notes later same-field appends still in play
// (advisory) and resolves the live set at the cursor position it is given.
import { afterEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render } from "@/lib/test/component";
import MutationCloseForm from "./MutationCloseForm.svelte";
import { api } from "@/lib/api";
import type { LoreEntrySummary, MutationMarkerRecord } from "@/lib/types";

const NOOP = () => {};

function record(id: string): MutationMarkerRecord {
  return {
    marker_id: id,
    entity_id: "mira",
    field: "bio",
    op: "add",
    value: "text",
    name: "",
    group: "",
    unit_id: id,
    unit_name: "",
    scene_id: "scene1",
    offset: 0,
    line: 1,
    scene_path: "Scene One",
  };
}

async function mount(position?: number) {
  render(MutationCloseForm, {
    props: {
      loreEntries: [{ id: "mira", title: "Mira", entry_type: "lore:character", metadata: {} } as unknown as LoreEntrySummary],
      sceneId: "scene1",
      presetEntityId: "mira",
      ...(position !== undefined ? { position } : {}),
      onPick: NOOP,
      onCancel: NOOP,
    },
  });
  await tick();
  await tick();
  await tick();
}

describe("MutationCloseForm later-append note", () => {
  afterEach(() => vi.restoreAllMocks());

  it("shows the note and link when later appends remain live", async () => {
    vi.spyOn(api, "getLiveEntityMutations").mockResolvedValue({
      items: [record("A")],
      later_appends: { A: ["B"] },
    });
    await mount();
    const note = document.querySelector(".close-note");
    expect(note?.textContent).toContain("1 later append to the same field remains live");
    expect(note?.querySelector("a")?.getAttribute("href")).toContain(
      "docs/mutations.md#appending-and-why-fragments-must-stand-alone",
    );
  });

  it("shows no note without later_appends", async () => {
    vi.spyOn(api, "getLiveEntityMutations").mockResolvedValue({ items: [record("A")] });
    await mount();
    expect(document.querySelector(".close-note")).toBeNull();
  });

  it("passes the cursor position to the live read", async () => {
    const spy = vi.spyOn(api, "getLiveEntityMutations").mockResolvedValue({ items: [] });
    await mount(42);
    expect(spy).toHaveBeenCalledWith("mira", "scene1", 42);
  });
});
