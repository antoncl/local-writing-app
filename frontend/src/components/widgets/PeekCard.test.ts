// @vitest-environment happy-dom
// PeekCard (#2011) — the hover/focus preview: title + kind · type + summary
// rows for a node, the carried-by/breakdown line for a tag; an actions row
// built from whichever callbacks the site wires (Open always, Swap only with
// both `field` and `on.swap`, Remove/Clear only with `on.remove`); Escape
// closes it.
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import PeekCard from "./PeekCard.svelte";
import type { MetadataFieldDefinition } from "@/lib/types";
import type { PeekTarget } from "@/lib/utils/peekTarget";

function anchorEl(): HTMLElement {
  const el = document.createElement("button");
  document.body.appendChild(el);
  return el;
}

const nodeModel: PeekTarget = {
  id: "char_1",
  kind: "lore",
  entryType: "lore:character",
  title: "Mira",
  typeLabel: "Character",
  summary: [
    { key: "role", label: "Role", text: "Courier" },
    { key: "age", label: "Age", text: "27" },
  ],
};

const tagModel: PeekTarget = {
  id: "tag_coastal",
  kind: "tag",
  entryType: "tag:motif",
  title: "Coastal",
  typeLabel: "Motif",
  summary: [],
  tag: {
    vocabularyLabel: "Motif",
    carriers: 3,
    byKind: [
      { kind: "lore", count: 2 },
      { kind: "manuscript", count: 1 },
    ],
  },
};

const singleField = { name: "Home Place", type: "entity_ref", options: [] } as unknown as MetadataFieldDefinition;
const listField = { name: "Characters", type: "entity_ref_list", options: [] } as unknown as MetadataFieldDefinition;

describe("PeekCard — node", () => {
  it("renders title, Kind · Type, and summary rows", () => {
    render(PeekCard, { props: { model: nodeModel, anchor: anchorEl(), on: { open: vi.fn(), close: vi.fn() } } });
    expect(screen.getByRole("dialog", { name: "Mira" })).toBeInTheDocument();
    expect(screen.getByText("Lore · Character")).toBeInTheDocument();
    expect(screen.getByText("Role")).toBeInTheDocument();
    expect(screen.getByText("Courier")).toBeInTheDocument();
    expect(screen.getByText("Age")).toBeInTheDocument();
    expect(screen.getByText("27")).toBeInTheDocument();
  });

  // #2227: a long value (a tag list) truncates with an ellipsis on one line;
  // the full text stays available on hover.
  it("a summary value carries its full text as a hover title", () => {
    const tags = "Aetheria, Setting, Elysian, flesh trade, Religion, Techne";
    render(PeekCard, {
      props: {
        model: { ...nodeModel, summary: [{ key: "tags", label: "Tags", text: tags }] },
        anchor: anchorEl(),
        on: { open: vi.fn(), close: vi.fn() },
      },
    });
    expect(screen.getByText(tags).getAttribute("title")).toBe(tags);
  });

  it("Open always renders and calls on.open", async () => {
    const open = vi.fn();
    render(PeekCard, { props: { model: nodeModel, anchor: anchorEl(), on: { open, close: vi.fn() } } });
    await fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(open).toHaveBeenCalledOnce();
  });

  it("no Swap/Remove when the callbacks are absent", () => {
    render(PeekCard, { props: { model: nodeModel, anchor: anchorEl(), field: listField, on: { open: vi.fn(), close: vi.fn() } } });
    expect(screen.queryByRole("button", { name: /remove/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /change/i })).toBeNull();
  });

  it("Remove label for a list field, Clear for a single field", () => {
    const remove = vi.fn();
    const { unmount } = render(PeekCard, {
      props: { model: nodeModel, anchor: anchorEl(), field: listField, on: { open: vi.fn(), close: vi.fn(), remove } },
    });
    expect(screen.getByText("× Remove")).toBeInTheDocument();
    unmount();

    render(PeekCard, {
      props: { model: nodeModel, anchor: anchorEl(), field: singleField, on: { open: vi.fn(), close: vi.fn(), remove } },
    });
    expect(screen.getByText("× Clear")).toBeInTheDocument();
  });

  it("clicking Remove calls on.remove", async () => {
    const remove = vi.fn();
    render(PeekCard, {
      props: { model: nodeModel, anchor: anchorEl(), field: listField, on: { open: vi.fn(), close: vi.fn(), remove } },
    });
    await fireEvent.click(screen.getByText("× Remove"));
    expect(remove).toHaveBeenCalledOnce();
  });

  it("Swap renders only with BOTH a field and on.swap", () => {
    render(PeekCard, {
      props: { model: nodeModel, anchor: anchorEl(), on: { open: vi.fn(), close: vi.fn(), swap: vi.fn() } },
    });
    // No field given — no picker_config to drive Swap, so it stays absent.
    expect(screen.queryByRole("button", { name: /change/i })).toBeNull();
  });

  it("Escape calls on.close", async () => {
    const close = vi.fn();
    render(PeekCard, { props: { model: nodeModel, anchor: anchorEl(), on: { open: vi.fn(), close } } });
    await fireEvent.keyDown(document, { key: "Escape" });
    expect(close).toHaveBeenCalledOnce();
  });

  it("a pointerdown outside the card and its anchor calls on.close", async () => {
    const close = vi.fn();
    render(PeekCard, { props: { model: nodeModel, anchor: anchorEl(), on: { open: vi.fn(), close } } });
    const outside = document.createElement("div");
    document.body.appendChild(outside);
    outside.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    expect(close).toHaveBeenCalledOnce();
  });

  it("a pointerdown on the anchor itself does not close the card", async () => {
    const close = vi.fn();
    const anchor = anchorEl();
    render(PeekCard, { props: { model: nodeModel, anchor, on: { open: vi.fn(), close } } });
    anchor.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    expect(close).not.toHaveBeenCalled();
  });
});

describe("PeekCard — tag", () => {
  it("renders the carried-by line and the kind breakdown", () => {
    render(PeekCard, { props: { model: tagModel, anchor: anchorEl(), on: { open: vi.fn(), close: vi.fn() } } });
    expect(screen.getByText("Tag · Motif · carried by 3 nodes")).toBeInTheDocument();
    expect(screen.getByText("Lore")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("Scene")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
  });
});
