// @vitest-environment happy-dom
// The "Proposed new entry" review card. #642 lesson: a pane that DISPLAYS data
// needs a mount test. Here the regression guard is #1018 — a long profile must
// not push "Create entry" off-screen — so the structural test asserts the
// action bar lives OUTSIDE the scroll region (pinned), not inside it.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import EntryDraftCard from "./EntryDraftCard.svelte";
import type { EntryPatch, MetadataSchema } from "@/lib/types";

const draft: EntryPatch = {
  body: "A long character profile body.",
  fields: { title: "Mira", condition: "cursed" },
};

const baseProps = {
  draft,
  dropped: [] as string[],
  metadataSchema: null,
  creating: false,
  onCreate: () => {},
  onDiscard: () => {},
};

describe("EntryDraftCard (#1018)", () => {
  it("renders the proposed title, fields, and the Create entry action", () => {
    render(EntryDraftCard, { props: baseProps });
    expect(screen.getByText("Mira")).toBeInTheDocument();
    expect(screen.getByText("cursed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create entry" })).toBeInTheDocument();
  });

  it("Create and Discard fire their gestures", async () => {
    const onCreate = vi.fn();
    const onDiscard = vi.fn();
    render(EntryDraftCard, { props: { ...baseProps, onCreate, onDiscard } });

    await fireEvent.click(screen.getByRole("button", { name: "Create entry" }));
    expect(onCreate).toHaveBeenCalledOnce();
    expect(onDiscard).not.toHaveBeenCalled();

    await fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    expect(onDiscard).toHaveBeenCalledOnce();
  });

  it("renders a proposed value through FieldValue — a select shows its LABEL, not the raw value (#1108)", () => {
    render(EntryDraftCard, {
      props: {
        ...baseProps,
        draft: { body: "", fields: { title: "Mira", status: "cursed" } },
        metadataSchema: {
          fields: {
            status: { name: "Status", type: "select", options: [{ value: "cursed", label: "Cursed soul" }] },
          },
          entry_types: {},
        } as unknown as MetadataSchema,
      },
    });
    // The pill shows the option's label; the raw stored value never leaks — the
    // draft card now reads like the metadata rail (ADR-0064).
    expect(screen.getByText("Cursed soul")).toBeInTheDocument();
    expect(screen.queryByText("cursed")).toBeNull();
  });

  it("pins the actions OUTSIDE the scroll region so a long profile can't hide them", () => {
    const { container } = render(EntryDraftCard, { props: baseProps });
    const scroll = container.querySelector(".edc-scroll");
    const actions = container.querySelector(".edc-actions");
    expect(scroll).not.toBeNull();
    expect(actions).not.toBeNull();
    // The fields scroll…
    expect(scroll!.querySelector(".edc-fields")).not.toBeNull();
    // …but the action bar must not be inside the scroller, or it would clip.
    expect(scroll!.contains(actions)).toBe(false);
  });
});
