// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import type { LoreEntry, PromotionPlan, PromotionTarget } from "@/lib/types";

// ADR-0078 §2/§9: PromoteModal fetches its own roster + dry-run plan (like
// DirectoryPickerModal), so the api calls are stubbed rather than the
// component reaching a real backend (#973 network guard).
const targets: PromotionTarget[] = [
  { layer_id: "root", label: "World" },
  { layer_id: "series", label: "Series" },
];

const plan: PromotionPlan = {
  destination: { layer_id: "series", label: "Series" },
  travels: ["aliases"],
  stays_in_origin: [
    { field: "location", reason: 'points at "The Rusty Anchor", a Book 2 place' },
  ],
  invisible_at_destination: ["faction"],
};

const promoted: LoreEntry = {
  id: "alice",
  title: "Alice",
  body: "…",
  revision: "2",
  entry_type: "lore:character",
  metadata: {},
  computed_metadata: {},
  source_layer_id: "series",
  source_layer_label: "Series",
};

const promotionTargets = vi.fn(async () => targets);
const previewLorePromotion = vi.fn(async () => plan);
const promoteLoreEntry = vi.fn(async () => promoted);

vi.mock("@/lib/api", () => ({
  api: {
    promotionTargets: (...args: unknown[]) => promotionTargets(...(args as [])),
    previewLorePromotion: (...args: unknown[]) => previewLorePromotion(...(args as [])),
    promoteLoreEntry: (...args: unknown[]) => promoteLoreEntry(...(args as [])),
  },
}));

import PromoteModal from "@/components/dialogs/PromoteModal.svelte";

const alice: LoreEntry = {
  id: "alice",
  title: "Alice",
  body: "…",
  revision: "1",
  entry_type: "lore:character",
  metadata: {},
  computed_metadata: {},
  source_layer_id: "book",
  source_layer_label: "Book",
};

const base = {
  open: true,
  entry: alice,
  onClose: vi.fn(),
  onFlush: vi.fn(async () => {}),
  onPromoted: vi.fn(),
};

beforeEach(() => {
  promotionTargets.mockClear();
  previewLorePromotion.mockClear();
  promoteLoreEntry.mockClear();
  base.onClose = vi.fn();
  base.onFlush = vi.fn(async () => {});
  base.onPromoted = vi.fn();
});

describe("PromoteModal", () => {
  it("renders nothing while closed, and does not fetch", () => {
    render(PromoteModal, { props: { ...base, open: false } });
    expect(screen.queryByText("Promote to…")).toBeNull();
    expect(promotionTargets).not.toHaveBeenCalled();
  });

  it("defaults to the nearest ancestor (last in the list) and renders the three plan buckets from the stub", async () => {
    render(PromoteModal, { props: { ...base } });

    // Nearest = last of the outermost-first list.
    const seriesRadio = (await screen.findByRole("radio", { name: "Series" })) as HTMLInputElement;
    expect(seriesRadio.checked).toBe(true);
    expect(previewLorePromotion).toHaveBeenCalledWith("alice", "series");

    // "Moves to <label>" — the travels field names.
    expect(await screen.findByText("Moves to Series")).toBeTruthy();
    expect(screen.getByText("aliases")).toBeTruthy();

    // "Stays in this project" — field + reason.
    expect(screen.getByText("Stays in this project")).toBeTruthy();
    expect(screen.getByText("location")).toBeTruthy();
    expect(screen.getByText(/points at "The Rusty Anchor"/)).toBeTruthy();

    // "Hidden at <label> until promoted".
    expect(screen.getByText("Hidden at Series until promoted")).toBeTruthy();
    expect(screen.getByText("faction")).toBeTruthy();
  });

  it("re-previews against the newly picked destination on a radio change", async () => {
    render(PromoteModal, { props: { ...base } });
    await screen.findByText("Moves to Series");
    previewLorePromotion.mockClear();

    await fireEvent.click(screen.getByRole("radio", { name: "World" }));

    expect(previewLorePromotion).toHaveBeenCalledWith("alice", "root");
  });

  it("shows a quiet message and no destination picker when there are no ancestor projects", async () => {
    promotionTargets.mockResolvedValueOnce([]);
    render(PromoteModal, { props: { ...base } });

    expect(await screen.findByText("No ancestor projects to promote into.")).toBeTruthy();
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Promote to/ })).toBeNull();
    // Close is still offered.
    expect(screen.getByRole("button", { name: "Close" })).toBeTruthy();
  });

  it("shows a backend error inline rather than crashing", async () => {
    promotionTargets.mockRejectedValueOnce(new Error("No project is open."));
    render(PromoteModal, { props: { ...base } });

    expect(await screen.findByText("No project is open.")).toBeTruthy();
  });

  it("flushes, promotes, and hands the result to onPromoted then closes, on confirm", async () => {
    render(PromoteModal, { props: { ...base } });
    // Wait for the plan (not just the targets) — the button stays disabled
    // until the preview has loaded.
    await screen.findByText("Moves to Series");
    const confirmButton = screen.getByRole("button", { name: "Promote to Series" });

    await fireEvent.click(confirmButton);

    expect(base.onFlush).toHaveBeenCalledWith("alice");
    expect(promoteLoreEntry).toHaveBeenCalledWith("alice", "series");
    await vi.waitFor(() => expect(base.onPromoted).toHaveBeenCalledWith(promoted));
    expect(base.onClose).toHaveBeenCalledTimes(1);
  });

  it("surfaces a 409/400-style commit failure inline and does not close", async () => {
    promoteLoreEntry.mockRejectedValueOnce(new Error("This entry is inherited, not owned here."));
    render(PromoteModal, { props: { ...base } });
    await screen.findByText("Moves to Series");
    const confirmButton = screen.getByRole("button", { name: "Promote to Series" });

    await fireEvent.click(confirmButton);

    expect(await screen.findByText("This entry is inherited, not owned here.")).toBeTruthy();
    expect(base.onClose).not.toHaveBeenCalled();
  });

  it("closes via the Close button", async () => {
    render(PromoteModal, { props: { ...base } });
    await fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(base.onClose).toHaveBeenCalledTimes(1);
  });
});
