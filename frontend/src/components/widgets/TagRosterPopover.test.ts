// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";

// #247 slice-2 PR-1: the + popover is also the govern-from-where-you-browse
// surface for PROJECT tags. Each row adds the tag; the ⋯ reveals Suggest-on /
// Rename / Merge — all backed by the existing project endpoints (rename is a
// single-source merge). After any op the popover bumps the vocabulary revision
// so App reconciles roster + open editors.
const getTagsOverview = vi.fn(async () => ({
  tags: [
    { name: "alpha", scope: { sources: [] }, count: 3 },
    { name: "beta", scope: { sources: [] }, count: 1 },
  ],
}));
const updateTagScope = vi.fn(async () => ({ tags: [] }));
const mergeTags = vi.fn(async () => ({ tags: [] }));
vi.mock("@/lib/api", () => ({
  api: {
    getTagsOverview: (...a: unknown[]) => getTagsOverview(...(a as [])),
    updateTagScope: (...a: unknown[]) => updateTagScope(...(a as [])),
    mergeTags: (...a: unknown[]) => mergeTags(...(a as [])),
  },
}));

const bump = vi.fn();
vi.mock("@/lib/stores/tags", () => ({ bumpTagVocabularyRevision: () => bump() }));

import TagRosterPopover from "@/components/widgets/TagRosterPopover.svelte";

const tags = [
  { name: "alpha", scope: { sources: [] } },
  { name: "beta", scope: { sources: [] } },
];

function setup(props: Record<string, unknown> = {}) {
  const onAdd = vi.fn<(name: string) => void>();
  const r = render(TagRosterPopover, {
    props: {
      tags,
      selectedKeys: new Set<string>(),
      scopeKind: "lore",
      scopeEntryType: "character",
      ariaLabel: "Tags",
      onAdd,
      ...props,
    },
  });
  return { ...r, onAdd };
}

beforeEach(() => {
  getTagsOverview.mockClear();
  updateTagScope.mockClear();
  mergeTags.mockClear();
  bump.mockClear();
});

describe("TagRosterPopover", () => {
  it("adds a tag by clicking its row", async () => {
    const { onAdd } = setup();
    await fireEvent.click(screen.getByText("alpha"));
    expect(onAdd).toHaveBeenLastCalledWith("alpha");
  });

  it("filters the shown rows", async () => {
    setup();
    await fireEvent.input(screen.getByLabelText("Filter Tags"), { target: { value: "bet" } });
    expect(screen.queryByText("alpha")).toBeNull();
    expect(screen.getByText("beta")).toBeInTheDocument();
  });

  it("offers Create 'x' when the filter matches no existing tag", async () => {
    const { onAdd } = setup();
    await fireEvent.input(screen.getByLabelText("Filter Tags"), { target: { value: "gamma" } });
    await fireEvent.click(screen.getByText(/Create/));
    expect(onAdd).toHaveBeenLastCalledWith("gamma");
  });

  it("renames a tag via a single-source merge to the new name", async () => {
    setup();
    await fireEvent.click(screen.getByRole("button", { name: "Govern alpha" }));
    await fireEvent.click(screen.getByText("Rename…"));
    const input = screen.getByLabelText("Rename alpha") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "protagonist" } });
    await fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    expect(mergeTags).toHaveBeenCalledWith(["alpha"], "protagonist");
    await vi.waitFor(() => expect(bump).toHaveBeenCalled());
  });

  it("saves a tag's suggest-on scope", async () => {
    setup();
    await fireEvent.click(screen.getByRole("button", { name: "Govern alpha" }));
    await fireEvent.click(screen.getByText("Suggest on…"));
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(updateTagScope).toHaveBeenCalledWith("alpha", { sources: [] });
    await vi.waitFor(() => expect(bump).toHaveBeenCalled());
  });

  it("merges multiple tags into a survivor after an explicit confirm", async () => {
    setup();
    await fireEvent.click(screen.getByRole("button", { name: "Govern alpha" }));
    await fireEvent.click(screen.getByText("Merge…")); // enter merge mode, alpha pre-ticked
    await fireEvent.click(screen.getByText("beta")); // tick the second
    await fireEvent.click(screen.getByRole("button", { name: "Merge…" })); // arm the confirm
    await fireEvent.click(screen.getByRole("button", { name: "Merge" })); // confirm
    // The survivor (alpha) is the TARGET, never its own source — only beta is a
    // source, so alpha is never folded into itself (which the backend rejects for
    // inherited tags and could drop the target on).
    expect(mergeTags).toHaveBeenCalledWith(["beta"], "alpha");
  });

  it("excludes the survivor from sources when merging into a new name", async () => {
    setup();
    await fireEvent.click(screen.getByRole("button", { name: "Govern alpha" }));
    await fireEvent.click(screen.getByText("Merge…"));
    await fireEvent.click(screen.getByText("beta"));
    await fireEvent.input(screen.getByLabelText("Merge into a new name"), { target: { value: "cast" } });
    await fireEvent.click(screen.getByRole("button", { name: "Merge…" }));
    await fireEvent.click(screen.getByRole("button", { name: "Merge" }));
    // A brand-new survivor isn't among the ticked, so both sources fold in.
    expect(mergeTags).toHaveBeenCalledWith(["alpha", "beta"], "cast");
  });

  it("backs out of the ⋯ menu to the plain list", async () => {
    setup();
    await fireEvent.click(screen.getByRole("button", { name: "Govern alpha" }));
    expect(screen.queryByLabelText("Filter Tags")).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Filter Tags")).toBeInTheDocument();
  });
});
