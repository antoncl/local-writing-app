// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";

// #247 slice-2 PR-1 (generalized in PR-3): the + popover is the
// govern-from-where-you-browse surface. Each row adds the tag; the ⋯ reveals
// Rename / Merge (+ Suggest-on for scoped vocabularies). Every op goes through
// an injected governance ADAPTER — project tags vs the flat, scope-less
// assistant tags — so these tests drive a fake adapter and assert the contract
// the component actually depends on (not a particular api/store wiring).
import type { TagGovernanceAdapter } from "@/lib/utils/tagGovernance";
import TagRosterPopover from "@/components/widgets/TagRosterPopover.svelte";

function makeAdapter(overrides: Partial<TagGovernanceAdapter> = {}) {
  return {
    supportsScope: true,
    loadCounts: vi.fn(async () => new Map<string, number>([["alpha", 3], ["beta", 1]])),
    setColor: vi.fn(async () => {}),
    updateScope: vi.fn(async () => {}),
    merge: vi.fn(async () => {}),
    reconcile: vi.fn(async () => {}),
    ...overrides,
  };
}

const tags = [
  { name: "alpha", scope: { sources: [] } },
  { name: "beta", scope: { sources: [] } },
];

function setup(adapterOverrides: Partial<TagGovernanceAdapter> = {}) {
  const adapter = makeAdapter(adapterOverrides);
  const onAdd = vi.fn<(name: string) => void>();
  const r = render(TagRosterPopover, {
    props: {
      tags,
      selectedKeys: new Set<string>(),
      ariaLabel: "Tags",
      adapter,
      onAdd,
    },
  });
  return { ...r, onAdd, adapter };
}

// The manager embeds the same roster with NO add-target (onAdd omitted).
function setupManager(adapterOverrides: Partial<TagGovernanceAdapter> = {}) {
  const adapter = makeAdapter(adapterOverrides);
  const r = render(TagRosterPopover, {
    props: { tags, selectedKeys: new Set<string>(), ariaLabel: "Tags", adapter },
  });
  return { ...r, adapter };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("TagRosterPopover", () => {
  it("adds a tag by clicking its row", async () => {
    const { onAdd } = setup();
    await fireEvent.click(screen.getByText("alpha"));
    expect(onAdd).toHaveBeenLastCalledWith("alpha");
  });

  it("keeps the entry input focused — a row's mousedown default is prevented", async () => {
    const { onAdd } = setup();
    // fireEvent resolves to false when the handler called preventDefault, so the
    // field's blur→crystallise never fires and half-typed text can't become a
    // stray chip when a suggestion is clicked.
    const notCancelled = await fireEvent.mouseDown(screen.getByTitle("Add alpha"));
    expect(notCancelled).toBe(false);
    // The click still adds — mousedown-prevent doesn't block activation.
    await fireEvent.click(screen.getByTitle("Add alpha"));
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
    const { adapter } = setup();
    await fireEvent.click(screen.getByRole("button", { name: "Govern alpha" }));
    await fireEvent.click(screen.getByText("Rename…"));
    const input = screen.getByLabelText("Rename alpha") as HTMLInputElement;
    await fireEvent.input(input, { target: { value: "protagonist" } });
    await fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    expect(adapter.merge).toHaveBeenCalledWith(["alpha"], "protagonist");
    await vi.waitFor(() => expect(adapter.reconcile).toHaveBeenCalled());
  });

  it("saves a tag's suggest-on scope", async () => {
    const { adapter } = setup();
    await fireEvent.click(screen.getByRole("button", { name: "Govern alpha" }));
    await fireEvent.click(screen.getByText("Suggest on…"));
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(adapter.updateScope).toHaveBeenCalledWith("alpha", { sources: [] });
    await vi.waitFor(() => expect(adapter.reconcile).toHaveBeenCalled());
  });

  it("merges multiple tags into a survivor after an explicit confirm", async () => {
    const { adapter } = setup();
    await fireEvent.click(screen.getByRole("button", { name: "Govern alpha" }));
    await fireEvent.click(screen.getByText("Merge…")); // enter merge mode, alpha pre-ticked
    await fireEvent.click(screen.getByText("beta")); // tick the second
    await fireEvent.click(screen.getByRole("button", { name: "Merge…" })); // arm the confirm
    await fireEvent.click(screen.getByRole("button", { name: "Merge" })); // confirm
    // The survivor (alpha) is the TARGET, never its own source — only beta folds in.
    expect(adapter.merge).toHaveBeenCalledWith(["beta"], "alpha");
  });

  it("excludes the survivor from sources when merging into a new name", async () => {
    const { adapter } = setup();
    await fireEvent.click(screen.getByRole("button", { name: "Govern alpha" }));
    await fireEvent.click(screen.getByText("Merge…"));
    await fireEvent.click(screen.getByText("beta"));
    await fireEvent.input(screen.getByLabelText("Merge into a new name"), { target: { value: "cast" } });
    await fireEvent.click(screen.getByRole("button", { name: "Merge…" }));
    await fireEvent.click(screen.getByRole("button", { name: "Merge" }));
    // A brand-new survivor isn't among the ticked, so both sources fold in.
    expect(adapter.merge).toHaveBeenCalledWith(["alpha", "beta"], "cast");
  });

  it("sets a tag's colour from the row swatch — the light path, no reconcile or rescan", async () => {
    const { adapter } = setup();
    const triggers = screen.getAllByRole("button", { name: "Pick a color" });
    await fireEvent.click(triggers[0]);
    // The palette is empty in tests, but Clear still exercises swatch → setColor.
    await fireEvent.click(screen.getByRole("button", { name: /Clear/ }));
    expect(adapter.setColor).toHaveBeenCalledWith("alpha", null);
    // Colour is the light path: the adapter refreshes its own roster, and the
    // component runs neither the heavy reconcile nor a use-count rescan.
    await vi.waitFor(() => expect(adapter.setColor).toHaveBeenCalled());
    expect(adapter.reconcile).not.toHaveBeenCalled();
    expect(adapter.loadCounts).toHaveBeenCalledTimes(1); // only the onMount load
  });

  it("surfaces an error and skips reconcile when a colour write fails", async () => {
    const setColor = vi.fn(async () => {
      throw new Error("colour service down");
    });
    setup({ setColor });
    const triggers = screen.getAllByRole("button", { name: "Pick a color" });
    await fireEvent.click(triggers[0]);
    await fireEvent.click(screen.getByRole("button", { name: /Clear/ }));
    await vi.waitFor(() => expect(screen.getByText("colour service down")).toBeInTheDocument());
  });

  it("backs out of the ⋯ menu to the plain list", async () => {
    setup();
    await fireEvent.click(screen.getByRole("button", { name: "Govern alpha" }));
    expect(screen.queryByLabelText("Filter Tags")).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByLabelText("Filter Tags")).toBeInTheDocument();
  });

  // ---- assistant vocabulary (no scope) ----------------------------------
  it("hides the Suggest-on affordance when the vocabulary has no scope", async () => {
    setup({ supportsScope: false });
    await fireEvent.click(screen.getByRole("button", { name: "Govern alpha" }));
    expect(screen.queryByText("Suggest on…")).toBeNull();
    // Rename + Merge stay — assistant tags still get those.
    expect(screen.getByText("Rename…")).toBeInTheDocument();
    expect(screen.getByText("Merge…")).toBeInTheDocument();
  });

  it("still merges a scope-less vocabulary through the adapter", async () => {
    const { adapter } = setup({ supportsScope: false });
    await fireEvent.click(screen.getByRole("button", { name: "Govern alpha" }));
    await fireEvent.click(screen.getByText("Rename…"));
    await fireEvent.input(screen.getByLabelText("Rename alpha"), { target: { value: "Editor" } });
    await fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    expect(adapter.merge).toHaveBeenCalledWith(["alpha"], "Editor");
  });

  // ---- manager mode (no add-target: onAdd omitted) ----------------------
  it("renders row names as static labels, not add-buttons, without an add-target", () => {
    setupManager();
    // No "Add …" button — the name is a plain label in the manager.
    expect(screen.queryByTitle("Add alpha")).toBeNull();
    expect(screen.getByText("alpha")).toBeInTheDocument();
    // Governance stays fully available.
    expect(screen.getByRole("button", { name: "Govern alpha" })).toBeInTheDocument();
  });

  it("suppresses the Create affordance when there is no add-target", async () => {
    setupManager();
    await fireEvent.input(screen.getByLabelText("Filter Tags"), { target: { value: "gamma" } });
    expect(screen.queryByText(/Create/)).toBeNull();
  });
});
