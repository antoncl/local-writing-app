// @vitest-environment happy-dom
// The offer_on authoring picker (ADR-0054 §4 / S4b, reworked #903). The tree
// model itself is unit-tested in offerOnTree.test.ts; this pins the component's
// render + interaction contract: it renders one row per hostable subject, a
// parent-covered type shows checked-but-disabled, and a toggle fires onChange.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import OfferOnPicker from "./OfferOnPicker.svelte";
import type { MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore", abstract: true, fields: [] },
    "lore:character": { name: "Character", kind: "lore", parent: "lore:base", fields: [] },
    "lore:item": { name: "Item", kind: "lore", parent: "lore:base", fields: [] },
    "lore:location": { name: "Location", kind: "lore", parent: "lore:base", fields: [] },
    "scene:scene": { name: "Scene", kind: "scene", fields: [] },
    "scene:act": { name: "Act", kind: "scene", fields: [] },
    "plot:card": { name: "Card", kind: "plot", fields: [] },
    "plot:board": { name: "Board", kind: "plot", fields: [] },
    "prompt:general": { name: "General", kind: "prompt", fields: [] },
  },
  fields: {},
} as unknown as MetadataSchema;

// The closed <details> may report children hidden depending on the DOM impl.
const box = (name: string) => screen.getByRole("checkbox", { name: new RegExp(`^${name}$`), hidden: true });

describe("OfferOnPicker (#903)", () => {
  it("renders a row per hostable subject and none of the dead targets", () => {
    render(OfferOnPicker, { props: { metadataSchema: SCHEMA, offerOn: [] } });
    // Lore (root + 3 leaves) + Scene + Card = 6.
    expect(screen.getAllByRole("checkbox", { hidden: true })).toHaveLength(6);
    expect(screen.queryByText("Act")).not.toBeInTheDocument();
    expect(screen.queryByText("Board")).not.toBeInTheDocument();
    expect(screen.queryByText("General")).not.toBeInTheDocument();
  });

  it("a type covered by a checked parent is on but disabled", () => {
    render(OfferOnPicker, { props: { metadataSchema: SCHEMA, offerOn: ["lore:base"] } });
    expect(box("Lore")).toBeChecked();
    expect(box("Character")).toBeChecked();
    expect(box("Character")).toBeDisabled();
    // A peer host outside the covered subtree stays interactive + off.
    expect(box("Scene")).not.toBeChecked();
    expect(box("Scene")).not.toBeDisabled();
  });

  it("checking a leaf fires onChange and reflects as checked", async () => {
    const onChange = vi.fn();
    render(OfferOnPicker, { props: { metadataSchema: SCHEMA, offerOn: [], onChange } });
    expect(box("Location")).not.toBeChecked();
    await fireEvent.click(box("Location"));
    expect(box("Location")).toBeChecked();
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("readOnly disables every row and swallows toggles", async () => {
    const onChange = vi.fn();
    render(OfferOnPicker, { props: { metadataSchema: SCHEMA, offerOn: [], readOnly: true, onChange } });
    expect(box("Character")).toBeDisabled();
    await fireEvent.click(box("Character"));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("no schema → nothing to offer", () => {
    render(OfferOnPicker, { props: { metadataSchema: null, offerOn: [] } });
    expect(screen.queryAllByRole("checkbox", { hidden: true })).toHaveLength(0);
  });

  it("a stale non-host id (from an older picker) renders no row and doesn't inflate the count", () => {
    // scene:act is a real type but not under the scene:scene host root, so it is
    // never offered — and must not count toward the badge.
    const { container } = render(OfferOnPicker, {
      props: { metadataSchema: SCHEMA, offerOn: ["lore:character", "scene:act"] },
    });
    expect(screen.getAllByRole("checkbox", { hidden: true })).toHaveLength(6);
    expect(screen.queryByText("Act")).not.toBeInTheDocument();
    const badge = container.querySelector(".offer-on-editor > summary > small");
    expect(badge?.textContent).toBe("1");
  });
});
