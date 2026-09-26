// @vitest-environment happy-dom
import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@/lib/test/component";
import { waitFor } from "@testing-library/svelte";

import ListReviewSection from "@/components/editor/body/ListReviewSection.svelte";
import { composeList, listUnits, pairListItems, type ListResolution } from "@/lib/utils/listCompare";
import type { MetadataFieldDefinition, MetadataValue } from "@/lib/types";

// ADR-0096 §6/§7 (S3): a seeded beats journey through the per-item review —
// pin the ADR's own "definition of done" walk, not just the pure engine (S2
// already covers that): unchanged beats stay quiet, the edited one shows its
// changed member as a region, the added one is one cool block, and clicking
// the change reports the right unit + composes to the right saved list.

const field: MetadataFieldDefinition = {
  name: "Beats",
  type: "list",
  options: [],
  item_identity: "id",
  item_members: [
    { key: "id", name: "Id", type: "text" },
    { key: "title", name: "Title", type: "text" },
    { key: "guidance", name: "Guidance", type: "long_text" },
  ],
} as unknown as MetadataFieldDefinition;

const beat = (id: string, title: string, guidance: string) => ({ id, title, guidance });

const L: MetadataValue[] = [
  beat("b1", "Setup", "g1"),
  beat("b2", "Rising action", "g2"),
  beat("b3", "Complication", "g3"),
  beat("b4", "Midpoint reversal", "she hesitates"),
  beat("b5", "Crisis", "g5"),
  beat("b6", "Resolution", "g6"),
];

const O: MetadataValue[] = [
  beat("b1", "Setup", "g1"),
  beat("b2", "Rising action", "g2"),
  beat("b3", "Complication", "g3"),
  beat("b4", "Midpoint reversal", "she hesitates, then chooses"),
  beat("b5", "Crisis", "g5"),
  beat("b6", "Resolution", "g6"),
  beat("b7", "Aftermath", "the fallout settles"),
];

function seed() {
  const pairing = pairListItems(field, L, O);
  const units = listUnits(field, pairing);
  return { pairing, units };
}

function baseProps(over: Record<string, unknown> = {}) {
  const { pairing, units } = seed();
  return {
    field,
    label: "Beats",
    pairing,
    units,
    L,
    O,
    resolution: {},
    view: "both" as const,
    onSettleUnit: vi.fn(),
    ...over,
  };
}

describe("ListReviewSection — the ADR-0096 seeded beats journey", () => {
  it("renders 5 quiet lines, the edited item, and a cool addition block", () => {
    const { container } = render(ListReviewSection, { props: baseProps() });
    const quiet = container.querySelectorAll(".lrs-quiet");
    expect(quiet).toHaveLength(5);
    expect([...quiet].map((el) => el.textContent)).toEqual([
      "Setup",
      "Rising action",
      "Complication",
      "Crisis",
      "Resolution",
    ]);
    const edited = container.querySelector(".lrs-edited .lrs-item-title");
    expect(edited?.textContent).toBe("Midpoint reversal");
    expect(container.querySelectorAll(".lrs-add")).toHaveLength(1);
    expect(container.querySelectorAll(".lrs-remove")).toHaveLength(0);
  });

  it("a prose member stays in its flip after one region settles, named once (regions settle one by one)", async () => {
    // Browser-found: the section used to swap the whole member for its settled
    // text on the first click, so a second change in the same guidance could
    // never be chosen — and the member's name printed twice.
    const { container } = render(ListReviewSection, {
      props: baseProps({ resolution: { "m|3|guidance": "she hesitates, then chooses" } }),
    });
    await waitFor(() => {
      expect(container.querySelector(".lrs-edited [data-region]")).not.toBeNull();
    });
    expect(container.querySelector(".lrs-edited .lrs-settled")).toBeNull();
    const names = [...container.querySelectorAll(".lrs-edited")].map((el) => el.textContent ?? "");
    expect(names.join("").split("Guidance").length - 1).toBe(1);
  });

  it("clicking the guidance change reports the unit's resolved text", async () => {
    const onSettleUnit = vi.fn();
    const { container } = render(ListReviewSection, { props: baseProps({ onSettleUnit }) });
    let region: HTMLElement | null = null;
    await waitFor(() => {
      region = container.querySelector(".lrs-edited [data-region].r-was, .lrs-edited .blk-was");
      expect(region).not.toBeNull();
    });
    await fireEvent.click(region!);
    expect(onSettleUnit).toHaveBeenCalledTimes(1);
    const [unitKey, value] = onSettleUnit.mock.calls[0];
    expect(unitKey).toBe("m|3|guidance");
    expect(typeof value).toBe("string");
    expect(value).toContain("chooses");
  });

  it("commit (composeList) with only the guidance unit adopted keeps 6 beats' ids and content, changes only the guidance", () => {
    const { pairing, units } = seed();
    const resolution: ListResolution = { "m|3|guidance": "she hesitates, then chooses" };
    const composed = composeList(field, L, O, pairing, resolution);
    expect(composed).toHaveLength(6);
    expect(composed.map((item) => (item as Record<string, unknown>).id)).toEqual(["b1", "b2", "b3", "b4", "b5", "b6"]);
    expect((composed[3] as Record<string, unknown>).guidance).toBe("she hesitates, then chooses");
  });

  it("acceptAll-equivalent (every unit adopted) composes 7 beats — the AI's content, L's identity kept", () => {
    const { pairing, units } = seed();
    const resolution: ListResolution = {};
    for (const unit of units) resolution[unit.key] = true;
    const composed = composeList(field, L, O, pairing, resolution);
    expect(composed).toHaveLength(7);
    expect(composed.map((item) => (item as Record<string, unknown>).title)).toEqual([
      "Setup",
      "Rising action",
      "Complication",
      "Midpoint reversal",
      "Crisis",
      "Resolution",
      "Aftermath",
    ]);
    expect((composed[3] as Record<string, unknown>).guidance).toBe("she hesitates, then chooses");
  });

  it("Current view shows L's own 6 beats; Proposed shows O's 7", async () => {
    const now = render(ListReviewSection, { props: baseProps({ view: "now" }) });
    await waitFor(() => expect(now.container.textContent).toContain("Setup"));
    expect(now.container.textContent).not.toContain("Aftermath");
    now.unmount();

    const was = render(ListReviewSection, { props: baseProps({ view: "was" }) });
    await waitFor(() => expect(was.container.textContent).toContain("Aftermath"));
    expect(was.container.textContent).toContain("chooses");
  });
});
