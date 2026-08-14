// @vitest-environment happy-dom
// The offer_on authoring picker (ADR-0054 §4 / S4b). Pins the control's contract:
// it lists the CONCRETE, offerable subject types grouped by kind (dropping
// abstract / deprecated types and the prompt / chat kinds, which are never
// conversation subjects), reflects the current allow-list as checked boxes, and
// on a toggle mutates `offer_on` + fires `onChange` so the pane saves.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import OfferOnPicker from "./OfferOnPicker.svelte";
import type { MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:base": { name: "Lore", kind: "lore", fields: [] },
    "lore:character": { name: "Character", kind: "lore", parent: "lore:base", fields: [] },
    "lore:abstract": { name: "Abstract", kind: "lore", abstract: true, fields: [] },
    "lore:old": { name: "Old note", kind: "lore", deprecated: true, fields: [] },
    "plot:card": { name: "Card", kind: "plot", fields: [] },
    "scene:scene": { name: "Scene", kind: "scene", fields: [] },
    // Non-host kinds — no node of these mounts a Conversations panel, so the
    // picker must not offer them (dead config otherwise).
    "prompt:general": { name: "General", kind: "prompt", fields: [] },
    "chat:chat_session": { name: "Chat", kind: "chat", fields: [] },
    "view:board": { name: "Board", kind: "view", fields: [] },
    "research:note": { name: "Note", kind: "research", fields: [] },
  },
  fields: {},
} as unknown as MetadataSchema;

// The closed <details> may report children as hidden depending on the DOM impl,
// so query with { hidden: true } to be robust either way.
const box = (id: string) => screen.getByRole("checkbox", { name: new RegExp(id), hidden: true });

describe("OfferOnPicker (ADR-0054 §4 / S4b)", () => {
  it("offers only concrete conversation-host subject types", () => {
    render(OfferOnPicker, { props: { metadataSchema: SCHEMA, offerOn: [] } });
    const checkboxes = screen.getAllByRole("checkbox", { hidden: true });
    // lore:base, lore:character, plot:card, scene:scene — the four offerable ones.
    expect(checkboxes).toHaveLength(4);
    // Abstract / deprecated dropped...
    expect(screen.queryByText("lore:abstract")).not.toBeInTheDocument();
    expect(screen.queryByText("lore:old")).not.toBeInTheDocument();
    // ...and every non-conversation-host kind dropped (dead config otherwise).
    expect(screen.queryByText("prompt:general")).not.toBeInTheDocument();
    expect(screen.queryByText("chat:chat_session")).not.toBeInTheDocument();
    expect(screen.queryByText("view:board")).not.toBeInTheDocument();
    expect(screen.queryByText("research:note")).not.toBeInTheDocument();
  });

  it("renders the current allow-list as checked boxes (opt-in: unlisted are unchecked)", () => {
    render(OfferOnPicker, { props: { metadataSchema: SCHEMA, offerOn: ["lore:character"] } });
    expect(box("lore:character")).toBeChecked();
    expect(box("plot:card")).not.toBeChecked();
    expect(box("scene:scene")).not.toBeChecked();
  });

  it("checking a box adds the exact id and fires onChange", async () => {
    const onChange = vi.fn();
    render(OfferOnPicker, { props: { metadataSchema: SCHEMA, offerOn: [], onChange } });
    const target = box("plot:card");
    expect(target).not.toBeChecked();
    await fireEvent.click(target);
    expect(box("plot:card")).toBeChecked();
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("unchecking a box removes the id and fires onChange", async () => {
    const onChange = vi.fn();
    render(OfferOnPicker, { props: { metadataSchema: SCHEMA, offerOn: ["scene:scene"], onChange } });
    const target = box("scene:scene");
    expect(target).toBeChecked();
    await fireEvent.click(target);
    expect(box("scene:scene")).not.toBeChecked();
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("readOnly locks every box and swallows toggles", async () => {
    const onChange = vi.fn();
    render(OfferOnPicker, { props: { metadataSchema: SCHEMA, offerOn: [], readOnly: true, onChange } });
    const target = box("lore:base");
    expect(target).toBeDisabled();
    await fireEvent.click(target);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("no schema → nothing to offer", () => {
    render(OfferOnPicker, { props: { metadataSchema: null, offerOn: [] } });
    expect(screen.queryAllByRole("checkbox", { hidden: true })).toHaveLength(0);
  });
});
