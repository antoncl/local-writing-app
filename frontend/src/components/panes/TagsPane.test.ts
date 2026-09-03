// @vitest-environment happy-dom
// TagsPane mount test (ADR-0082 §3/F3, #642: a pane that DISPLAYS data needs a
// mount test asserting rows render). Pins: rows render grouped by vocabulary,
// the usage-count pill reads the reference index, the "Merged" group starts
// collapsed (per vocabulary), and the merge action calls the API.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { tick } from "svelte";
import { render, screen, fireEvent, within } from "@/lib/test/component";
import TagsPane from "./TagsPane.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import { tagNodesStore } from "@/lib/stores/tagNodes";
import { referenceIndexStore } from "@/lib/stores/references";
import { confirmService } from "@/lib/stores/confirmService.svelte";
import { editorPanes } from "@/lib/stores/editorPanes.svelte";
import { api } from "@/lib/api";
import type { MetadataSchema, TagEntry } from "@/lib/types";

const SCHEMA = {
  entry_types: {
    "tag:tag": { name: "Tags", kind: "tag" },
    "tag:motifs": { name: "Motifs", kind: "tag" },
  },
  fields: {},
} as unknown as MetadataSchema;

function tag(id: string, title: string, entryType = "tag:tag", mergedInto: string | null = null): TagEntry {
  return { id, title, entry_type: entryType, metadata: {}, merged_into: mergedInto };
}

beforeEach(() => {
  metadataSchemaStore.set(SCHEMA);
  vi.spyOn(api, "listTagEntries").mockResolvedValue({ tags: [] });
  vi.spyOn(api, "referenceGraph").mockResolvedValue({ refs: {} });
  // R5's refresh set — a merge/delete re-syncs these too, so a mount test
  // that drives either one must mock them (the network guard fails a real
  // fetch, #973).
  vi.spyOn(api, "listLoreEntries").mockResolvedValue({ entries: [] });
  vi.spyOn(api, "listPromptEntries").mockResolvedValue({ entries: [] });
  vi.spyOn(api, "listAssistantEntries").mockResolvedValue({ entries: [] });
  vi.spyOn(editorPanes, "refreshOpenEditorPaneBaselines").mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
  metadataSchemaStore.set(null as unknown as MetadataSchema);
  tagNodesStore.set([]);
  referenceIndexStore.set(new Map());
  confirmService.active = null;
});

describe("TagsPane — grouping + usage count (#642)", () => {
  it("groups live tags by vocabulary and shows a usage-count pill from the reference index", () => {
    tagNodesStore.set([tag("tag_mirrors", "mirrors"), tag("tag_coastal", "Coastal", "tag:motifs")]);
    referenceIndexStore.set(new Map([["tag_mirrors", new Set(["lore_hero", "lore_villain"])]]));

    render(TagsPane, { props: { onOpenTag: () => {} } });

    expect(screen.getByText("Tags")).toBeInTheDocument();
    expect(screen.getByText("Motifs")).toBeInTheDocument();
    expect(screen.getByText("mirrors")).toBeInTheDocument();
    expect(screen.getByText("Coastal")).toBeInTheDocument();
    const mirrorsRow = screen.getByTestId("tag-row-tag_mirrors");
    expect(within(mirrorsRow).getByText("2")).toBeInTheDocument();
  });

  it("the Merged group is collapsed by default and expands on click", async () => {
    tagNodesStore.set([tag("tag_mirror", "mirror", "tag:tag", "tag_mirrors"), tag("tag_mirrors", "mirrors")]);

    render(TagsPane, { props: { onOpenTag: () => {} } });

    expect(screen.queryByText("mirror")).not.toBeInTheDocument();
    expect(screen.getByTestId("tags-merged-group")).toBeInTheDocument();

    const mergedGroup = screen.getByTestId("tags-merged-group");
    await fireEvent.click(within(mergedGroup).getByRole("button", { name: "Expand" }));

    expect(screen.getByText("mirror")).toBeInTheDocument();
  });

  it("clicking a row opens it", async () => {
    tagNodesStore.set([tag("tag_mirrors", "mirrors")]);
    const onOpenTag = vi.fn();

    render(TagsPane, { props: { onOpenTag } });
    await fireEvent.click(screen.getByText("mirrors"));

    expect(onOpenTag).toHaveBeenCalledWith("tag_mirrors");
  });
});

describe("TagsPane — merge action (#642)", () => {
  it("picking a survivor from Merge into… confirms then calls the API and refreshes", async () => {
    tagNodesStore.set([tag("tag_mirror", "mirror"), tag("tag_mirrors", "mirrors")]);
    const mergeSpy = vi.spyOn(api, "mergeTagEntries").mockResolvedValue(tag("tag_mirrors", "mirrors"));

    render(TagsPane, { props: { onOpenTag: () => {} } });

    const mirrorRow = screen.getByTestId("tag-row-tag_mirror");
    const mergeControl = within(mirrorRow).getByTestId("tag-merge");
    await fireEvent.click(within(mergeControl).getByRole("button", { expanded: false }));
    await tick();

    // The candidate menu portals to <body> (NodePickerPopover), so it is
    // found in `screen`, not scoped under `mergeControl` — and scoped to the
    // menu itself (role="menu"), since "mirrors" also names the row we're on.
    const menu = screen.getByRole("menu");
    const candidate = within(menu).getByText("mirrors");
    await fireEvent.click(candidate.closest("button")!);
    await tick();

    // The picker only queues a confirmation — the actual merge waits for it.
    expect(confirmService.active).not.toBeNull();
    expect(confirmService.active?.message).toContain("mirror");
    expect(confirmService.active?.message).toContain("mirrors");
    expect(mergeSpy).not.toHaveBeenCalled();

    await confirmService.resolve();

    expect(mergeSpy).toHaveBeenCalledWith("tag_mirror", "tag_mirrors");
    // R5: the retired App.svelte `refreshAfterTagChange`'s refresh set —
    // an open editor pane must not clobber the rewrite on its next autosave.
    expect(editorPanes.refreshOpenEditorPaneBaselines).toHaveBeenCalled();
  });

  it("deleting a tag also refreshes open editor pane baselines (R5)", async () => {
    tagNodesStore.set([tag("tag_mirrors", "mirrors")]);
    const deleteSpy = vi.spyOn(api, "deleteTagEntry").mockResolvedValue(undefined);

    render(TagsPane, { props: { onOpenTag: () => {} } });

    const row = screen.getByTestId("tag-row-tag_mirrors");
    await fireEvent.click(within(row).getByTestId("tag-delete"));
    expect(confirmService.active).not.toBeNull();

    await confirmService.resolve();

    expect(deleteSpy).toHaveBeenCalledWith("tag_mirrors");
    expect(editorPanes.refreshOpenEditorPaneBaselines).toHaveBeenCalled();
  });
});

describe("TagsPane — delete confirm names transitive redirects (R7)", () => {
  it("counts a two-hop chain (a -> b -> the tag being deleted)", async () => {
    // a redirects to b, b redirects to mirrors — deleting mirrors also
    // removes BOTH a and b, not just the one directly pointing at it.
    tagNodesStore.set([
      tag("tag_a", "a", "tag:tag", "tag_b"),
      tag("tag_b", "b", "tag:tag", "tag_mirrors"),
      tag("tag_mirrors", "mirrors"),
    ]);

    render(TagsPane, { props: { onOpenTag: () => {} } });

    const row = screen.getByTestId("tag-row-tag_mirrors");
    await fireEvent.click(within(row).getByTestId("tag-delete"));

    expect(confirmService.active?.message).toContain("2 merged tags");
  });
});
