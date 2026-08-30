// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import type { LoreEntry, MutationSetEntry, PromptEntry, PromotionPlan, PromotionTarget } from "@/lib/types";

// ADR-0078 §2/§9 (+ slice 3, prompts): PromoteModal fetches its own roster +
// dry-run plan (like DirectoryPickerModal), so the api calls are stubbed
// rather than the component reaching a real backend (#973 network guard).
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
  also_promoted: [],
  resolves_differently: [],
  blocked_reason: null,
  related: [],
};

// A lore plan with pinned staged mutation sets (ADR-0078 §7): the "related —
// promote separately" bucket, which only ever populates for a lore promotion.
const relatedPlan: PromotionPlan = { ...plan, related: ["Full Moon Transformation"] };

// A prompt's plan (slice 3): the two lore-always-empty buckets populated, and
// no lore-only buckets (stays_in_origin / invisible_at_destination are lore's
// static-partition concepts — empty here, which is realistic for a prompt).
const promptPlan: PromotionPlan = {
  destination: { layer_id: "series", label: "Series" },
  travels: [],
  stays_in_origin: [],
  invisible_at_destination: [],
  also_promoted: ["Style Guide Snippet"],
  resolves_differently: ["setting_context"],
  blocked_reason: null,
  related: [],
};

const blockedPlan: PromotionPlan = {
  ...promptPlan,
  blocked_reason: "Includes a dynamic {% include input.x %} the cascade can't follow.",
};

// A mutation set's plan (slice 4): its pinned entity cascades (also_promoted),
// mirroring a prompt's include cascade — no dynamic references, so
// resolves_differently stays empty.
const mutationSetPlan: PromotionPlan = {
  destination: { layer_id: "series", label: "Series" },
  travels: [],
  stays_in_origin: [],
  invisible_at_destination: [],
  also_promoted: ["Alice"],
  resolves_differently: [],
  blocked_reason: null,
  related: [],
};

const mutationSetBlockedPlan: PromotionPlan = {
  ...mutationSetPlan,
  blocked_reason: "Alice is owned by an intermediate ancestor and can't be lifted from here.",
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

const promotedPrompt: PromptEntry = {
  id: "style-guide",
  title: "Style Guide",
  body: "…",
  revision: "2",
  entry_type: "prompt:snippet",
  metadata: {},
  inputs: [],
  computed_metadata: {},
  source_layer_id: "series",
  source_layer_label: "Series",
};

const promotedMutationSet: MutationSetEntry = {
  id: "mset-1",
  title: "Full Moon Transformation",
  revision: "2",
  entry_type: "mutation_set:mutation_set",
  target_entry_type: "lore:character",
  target_entity: "alice",
  rows: [],
  placed: false,
  source_layer_id: "series",
  source_layer_label: "Series",
};

const promotionTargets = vi.fn(async () => targets);
const previewLorePromotion = vi.fn(async () => plan);
const promoteLoreEntry = vi.fn(async () => promoted);
const previewPromptPromotion = vi.fn(async () => promptPlan);
const promotePromptEntry = vi.fn(async () => promotedPrompt);
const previewMutationSetPromotion = vi.fn(async () => mutationSetPlan);
const promoteMutationSetEntry = vi.fn(async () => promotedMutationSet);

vi.mock("@/lib/api", () => ({
  api: {
    promotionTargets: (...args: unknown[]) => promotionTargets(...(args as [])),
    previewLorePromotion: (...args: unknown[]) => previewLorePromotion(...(args as [])),
    promoteLoreEntry: (...args: unknown[]) => promoteLoreEntry(...(args as [])),
    previewPromptPromotion: (...args: unknown[]) => previewPromptPromotion(...(args as [])),
    promotePromptEntry: (...args: unknown[]) => promotePromptEntry(...(args as [])),
    previewMutationSetPromotion: (...args: unknown[]) => previewMutationSetPromotion(...(args as [])),
    promoteMutationSetEntry: (...args: unknown[]) => promoteMutationSetEntry(...(args as [])),
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

const styleGuidePrompt: PromptEntry = {
  id: "style-guide",
  title: "Style Guide",
  body: "…",
  revision: "1",
  entry_type: "prompt:snippet",
  metadata: {},
  inputs: [],
  computed_metadata: {},
  source_layer_id: "book",
  source_layer_label: "Book",
};

const stagedMutationSet: MutationSetEntry = {
  id: "mset-1",
  title: "Full Moon Transformation",
  revision: "1",
  entry_type: "mutation_set:mutation_set",
  target_entry_type: "lore:character",
  target_entity: "alice",
  rows: [],
  placed: false,
  source_layer_id: "book",
  source_layer_label: "Book",
};

const base = {
  kind: "lore" as const,
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
  previewPromptPromotion.mockClear();
  promotePromptEntry.mockClear();
  previewMutationSetPromotion.mockClear();
  promoteMutationSetEntry.mockClear();
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

  it("renders the 'Related — promote separately' bucket for a lore plan with pinned staged sets (ADR-0078 §7)", async () => {
    previewLorePromotion.mockResolvedValueOnce(relatedPlan);
    render(PromoteModal, { props: { ...base } });

    expect(await screen.findByText("Related — promote separately")).toBeTruthy();
    expect(screen.getByText("Full Moon Transformation")).toBeTruthy();
  });
});

describe("PromoteModal — prompt kind (ADR-0078 §2/§9 slice 3)", () => {
  const promptBase = { ...base, kind: "prompt" as const, entry: styleGuidePrompt };

  it("dispatches to the prompt endpoints and renders the two new buckets from a stub prompt plan", async () => {
    render(PromoteModal, { props: { ...promptBase } });

    await screen.findByRole("radio", { name: "Series" });
    expect(previewPromptPromotion).toHaveBeenCalledWith("style-guide", "series");
    expect(previewLorePromotion).not.toHaveBeenCalled();

    // "Also promoted" — the cascaded include-closure, by title.
    expect(await screen.findByText("Also promoted")).toBeTruthy();
    expect(screen.getByText("Style Guide Snippet")).toBeTruthy();

    // "Resolves differently" — the dynamic input names.
    expect(screen.getByText("Resolves differently")).toBeTruthy();
    expect(screen.getByText("setting_context")).toBeTruthy();

    const confirmButton = screen.getByRole("button", { name: "Promote to Series" });
    await fireEvent.click(confirmButton);
    expect(promotePromptEntry).toHaveBeenCalledWith("style-guide", "series");
    expect(promoteLoreEntry).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(promptBase.onPromoted).toHaveBeenCalledWith(promotedPrompt));
  });

  it("shows a blocked reason prominently and disables Promote, without dropping the other buckets", async () => {
    previewPromptPromotion.mockResolvedValueOnce(blockedPlan);
    render(PromoteModal, { props: { ...promptBase } });

    await screen.findByText(
      "Includes a dynamic {% include input.x %} the cascade can't follow.",
    );
    // Context still renders alongside the block.
    expect(screen.getByText("Also promoted")).toBeTruthy();

    const confirmButton = screen.getByRole("button", { name: "Promote to Series" });
    expect((confirmButton as HTMLButtonElement).disabled).toBe(true);

    await fireEvent.click(confirmButton);
    expect(promotePromptEntry).not.toHaveBeenCalled();
  });
});

describe("PromoteModal — mutation_set kind (ADR-0078 §2/§9 slice 4)", () => {
  const mutationSetBase = { ...base, kind: "mutation_set" as const, entry: stagedMutationSet };

  it("dispatches to the mutation-set endpoints and renders also_promoted from a stub plan", async () => {
    render(PromoteModal, { props: { ...mutationSetBase } });

    await screen.findByRole("radio", { name: "Series" });
    expect(previewMutationSetPromotion).toHaveBeenCalledWith("mset-1", "series");
    expect(previewLorePromotion).not.toHaveBeenCalled();
    expect(previewPromptPromotion).not.toHaveBeenCalled();

    // "Also promoted" — the cascaded pinned entity, by title.
    expect(await screen.findByText("Also promoted")).toBeTruthy();
    expect(screen.getByText("Alice")).toBeTruthy();
    // A mutation set carries no dynamic references.
    expect(screen.queryByText("Resolves differently")).toBeNull();

    const confirmButton = screen.getByRole("button", { name: "Promote to Series" });
    await fireEvent.click(confirmButton);
    expect(promoteMutationSetEntry).toHaveBeenCalledWith("mset-1", "series");
    await vi.waitFor(() => expect(mutationSetBase.onPromoted).toHaveBeenCalledWith(promotedMutationSet));
  });

  it("shows a blocked reason (a pin owned by an intermediate ancestor) and disables Promote", async () => {
    previewMutationSetPromotion.mockResolvedValueOnce(mutationSetBlockedPlan);
    render(PromoteModal, { props: { ...mutationSetBase } });

    expect(
      await screen.findByText("Alice is owned by an intermediate ancestor and can't be lifted from here."),
    ).toBeTruthy();
    const confirmButton = screen.getByRole("button", { name: "Promote to Series" });
    expect((confirmButton as HTMLButtonElement).disabled).toBe(true);

    await fireEvent.click(confirmButton);
    expect(promoteMutationSetEntry).not.toHaveBeenCalled();
  });
});
