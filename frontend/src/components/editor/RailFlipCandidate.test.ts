// @vitest-environment happy-dom
// #1884 slice 4, second follow-up — RailFlipCandidate is MetadataPanel's
// AI lore-proposal flip candidate (ADR-0046 slice 3b), extracted as a pure
// refactor. These tests pin what the extraction must preserve byte-identical:
// the hit button's `aria-pressed`/click, the "Current: …" hint (including the
// "unset" fallback), and the tag-flip vs read-only-scalar fork.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import RailFlipCandidate from "./RailFlipCandidate.svelte";
import type { MetadataFieldDefinition } from "@/lib/types";

const TEXT_FIELD = { name: "Note", type: "text" } as unknown as MetadataFieldDefinition;

describe("RailFlipCandidate", () => {
  it("renders the hit button with aria-pressed reflecting adopted, and click calls onToggle", async () => {
    const onToggle = vi.fn();
    render(RailFlipCandidate, {
      props: {
        field: TEXT_FIELD,
        fieldLabel: "Note",
        value: "Proposed text",
        adopted: false,
        onToggle,
        currentHint: "Old text",
        tagItems: null,
      },
    });
    const hit = screen.getByRole("button");
    expect(hit.getAttribute("aria-pressed")).toBe("false");
    await fireEvent.click(hit);
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("reflects adopted=true on the hit button", () => {
    render(RailFlipCandidate, {
      props: {
        field: TEXT_FIELD,
        fieldLabel: "Note",
        value: "Proposed text",
        adopted: true,
        onToggle: vi.fn(),
        currentHint: "Old text",
        tagItems: null,
      },
    });
    expect(screen.getByRole("button").getAttribute("aria-pressed")).toBe("true");
  });

  it('an empty currentHint shows "Current: unset"', () => {
    render(RailFlipCandidate, {
      props: {
        field: TEXT_FIELD,
        fieldLabel: "Note",
        value: "Proposed text",
        adopted: false,
        onToggle: vi.fn(),
        currentHint: "",
        tagItems: null,
      },
    });
    expect(screen.getByText("Current: unset")).toBeTruthy();
  });

  it("tagItems non-null renders TagFlipChips (a chip label)", () => {
    render(RailFlipCandidate, {
      props: {
        field: TEXT_FIELD,
        fieldLabel: "Tags",
        value: [],
        adopted: false,
        onToggle: vi.fn(),
        currentHint: "",
        tagItems: [{ key: "tag_1", label: "Old Tag", isNew: false }],
      },
    });
    expect(screen.getByTestId("flip-tag-chip").textContent).toBe("Old Tag");
  });

  it("tagItems null renders the read-only FieldValueEditor display instead", () => {
    render(RailFlipCandidate, {
      props: {
        field: TEXT_FIELD,
        fieldLabel: "Note",
        value: "Proposed text",
        adopted: false,
        onToggle: vi.fn(),
        currentHint: "",
        tagItems: null,
      },
    });
    expect(screen.queryByTestId("flip-tag-chip")).toBeNull();
    expect(screen.getByText("Proposed text")).toBeTruthy();
  });
});
