// @vitest-environment happy-dom
// ADR-0095 §6/§8 (browser-run follow-up): a scene save that touches a
// mutation marker refreshes the mutation-set ROSTER too, not just
// `mutationsVersion` — the roster's per-set `anchors` is what the pill's
// "N places" tell, the pill dialog's "Linked" line and the linked stop
// caption all read, and only a SET write refreshed it before this. Without
// this, a Link (or any anchor add/remove/paste) left every one of those
// tells stale until something else happened to refresh the roster.
import { afterEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import { Editor } from "@tiptap/core";
import { api } from "@/lib/api";
import { refreshAfterSave, sameAnchorIds, type SaveRefreshHost } from "./editorPaneSave";
import { mutationSetEntriesStore, mutationSetRosterLoadedStore, mutationSetsByIdStore } from "./mutationSets";
import { mutationsVersion } from "./mutationsVersion.svelte";
import { createMutationMark } from "@/lib/editor-core/proseMarks";
import { proseStarterKit } from "@/lib/editor-core/proseStarterKit";
import type { MutationSetEntrySummary } from "@/lib/types";

const host: SaveRefreshHost = { onProjectNodeSaved: () => {} };

function stubSceneRefreshes(): void {
  vi.spyOn(api, "getStructure").mockResolvedValue({ nodes: [] } as never);
  vi.spyOn(api, "getTodos").mockResolvedValue({ items: [] } as never);
  vi.spyOn(api, "getEmbeddedTodos").mockResolvedValue({ items: [] } as never);
}

function summary(over: Partial<MutationSetEntrySummary> = {}): MutationSetEntrySummary {
  return {
    id: "set1",
    title: "Promotion",
    entry_type: "mutation_set:mutation_set",
    target_entry_type: "lore:character",
    target_entity: "mira",
    row_count: 1,
    rows: [{ id: "r1", field: "rank", op: "replace", value: "Captain" }],
    anchors: [],
    state: "active",
    pin_missing: false,
    source_layer_id: "",
    source_layer_label: "",
    ...over,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  mutationSetEntriesStore.set([]);
  mutationSetRosterLoadedStore.set(false);
});

describe("refreshAfterSave — mutation-set roster refresh on a marker-bearing scene save", () => {
  it("refreshes the roster (no extra bump) after a save that adds an anchor", async () => {
    stubSceneRefreshes();
    // Before the save: the roster still shows the set with ONE anchor (stale —
    // this scene's save just anchored it a second time, e.g. via Link).
    mutationSetEntriesStore.set([
      summary({ anchors: [{ anchor_id: "a1", scene_id: "scene1", scene_title: "Ch 1" }] }),
    ]);
    mutationSetRosterLoadedStore.set(true);
    const editor = new Editor({
      element: document.createElement("div"),
      extensions: [proseStarterKit(), createMutationMark()],
      content: "<p></p>",
    });
    editor.chain().insertContent({ type: "mutation", attrs: { setId: "set1", anchorId: "a1" } }).run();
    const pillText = () =>
      editor.view.dom.querySelector('.mutation-pill[data-mutation-id="a1"]')?.textContent ?? null;
    expect(pillText()).toBe("⤳ Promotion"); // stale: still shows as a single anchor

    vi.spyOn(api, "listMutationSetEntries").mockResolvedValue({
      entries: [
        summary({
          anchors: [
            { anchor_id: "a1", scene_id: "scene1", scene_title: "Ch 1" },
            { anchor_id: "a2", scene_id: "scene1", scene_title: "Ch 1" },
          ],
        }),
      ],
    });

    const before = mutationsVersion.value;
    await refreshAfterSave(host, {
      documentKind: "manuscript",
      savedTitle: "Ch 1",
      baselineBody: "before <!-- mutate:set=set1;id=a1 -->",
      draftMarkdown: "before <!-- mutate:set=set1;id=a1 --> after <!-- mutate:set=set1;id=a2 -->",
    });

    // One bump total — the existing invalidation bump, not a second one from
    // the roster refresh (`{ bump: false }`).
    expect(mutationsVersion.value).toBe(before + 1);

    const entry = get(mutationSetsByIdStore).get("set1");
    expect(entry?.anchors).toHaveLength(2);
    // The pill reads live off the store (ADR-0095 §1) — no doc change needed.
    expect(pillText()).toBe("⤳ Promotion · 2 places");
    editor.destroy();
  });

  it("does not refresh the roster for a save with no mutation markers, before or after", async () => {
    stubSceneRefreshes();
    const listSpy = vi.spyOn(api, "listMutationSetEntries");

    await refreshAfterSave(host, {
      documentKind: "manuscript",
      savedTitle: "Ch 1",
      baselineBody: "plain prose",
      draftMarkdown: "still plain prose",
    });

    expect(listSpy).not.toHaveBeenCalled();
  });

  it("does not refresh the roster when a save only edits prose around an unchanged pill", async () => {
    stubSceneRefreshes();
    const listSpy = vi.spyOn(api, "listMutationSetEntries");
    const anchor = "<!-- mutate:set=mutation_set_a;id=mut_1 -->";
    const before = mutationsVersion.value;

    await refreshAfterSave(host, {
      documentKind: "manuscript",
      savedTitle: "Ch 1",
      baselineBody: `She read the letter. ${anchor}`,
      draftMarkdown: `She read the letter twice. ${anchor}`,
    });

    expect(listSpy).not.toHaveBeenCalled();
    // The version still bumps: offsets moved, so resolution must re-read.
    expect(mutationsVersion.value).toBe(before + 1);
  });
});

describe("sameAnchorIds", () => {
  const a = "<!-- mutate:set=mutation_set_a;id=mut_1 -->";
  const b = "<!-- mutate:set=mutation_set_a;id=mut_2 -->";
  it("is true when only the prose around the anchors changed", () => {
    expect(sameAnchorIds(`x ${a} y`, `xx ${a} yy`)).toBe(true);
  });
  it("is false when an anchor was added, removed or repointed", () => {
    expect(sameAnchorIds(`${a}`, `${a} ${b}`)).toBe(false);
    expect(sameAnchorIds(`${a} ${b}`, `${a}`)).toBe(false);
    expect(sameAnchorIds(a, "<!-- mutate:set=mutation_set_z;id=mut_1 -->")).toBe(false);
  });
});
