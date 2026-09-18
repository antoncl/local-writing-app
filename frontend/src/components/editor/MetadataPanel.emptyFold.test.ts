// @vitest-environment happy-dom
// #2006 — the rail is what is known: empty fields fold behind one "N more
// fields ▸" line by default. Sticky-while-open (a field filled/emptied mid-edit
// doesn't jump rows out from under the writer) is the tricky bit; the rest is
// membership + label bookkeeping.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { EntryMetadata, MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: {
    "lore:character": {
      name: "Character",
      kind: "lore",
      fields: ["alias", "nick", "tone", "hue", "kin", "role", "loyalty"],
    },
  },
  fields: {
    alias: { name: "Alias", type: "text" },
    nick: { name: "Nick", type: "text" },
    tone: { name: "Tone", type: "text" },
    hue: { name: "Hue", type: "color" },
    kin: {
      name: "Kin",
      type: "entity_ref_list",
      options: [],
      picker_config: { sources: [{ kind: "lore" }] },
    },
    // An L1 group whose fields are ALL empty by default — must NOT show a
    // group head while the fold is closed, but must once opened (#2006 item 4).
    role: { name: "Role", type: "text", group: "Arc" },
    loyalty: { name: "Loyalty", type: "text", group: "Arc" },
  },
} as unknown as MetadataSchema;

beforeEach(() => metadataSchemaStore.set(SCHEMA));

function baseProps(metadata: EntryMetadata) {
  return {
    entryType: "lore:character",
    status: "",
    metadata,
    documentKind: "lore",
    documentLabel: "Entry",
    documentEntryTypes: [["lore:character", SCHEMA.entry_types["lore:character"]]] as never,
    metadataFieldIds: ["alias", "nick", "tone", "hue", "kin", "role", "loyalty"],
    onMetadataChange: vi.fn(),
  };
}

function mount(metadata: EntryMetadata) {
  return render(MetadataPanel, { props: baseProps(metadata) as never });
}

describe("MetadataPanel — empty fields fold (#2006)", () => {
  it("closed by default: only filled rows render, toggle names the live empty count", () => {
    // alias + hue are "filled" (hue always shows an effective swatch); the
    // rest (nick, tone, kin, role, loyalty) are empty → 5 folded.
    mount({ alias: "The Painted" });
    expect(screen.getByText("Alias")).toBeInTheDocument();
    expect(screen.queryByText("Nick")).toBeNull();
    expect(screen.queryByText("Role")).toBeNull();
    const toggle = screen.getByTestId("rail-fold-toggle");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveTextContent("5 more fields");
  });

  it("opening reveals every row, empties carry .empty, the all-empty group head appears, label flips", async () => {
    mount({ alias: "The Painted" });
    const toggle = screen.getByTestId("rail-fold-toggle");
    await fireEvent.click(toggle);

    expect(screen.getByText("Nick")).toBeInTheDocument();
    const nickRow = screen.getByText("Nick").closest(".field-row");
    expect(nickRow).not.toBeNull();
    expect(nickRow!.classList.contains("empty")).toBe(true);

    // The "Arc" group is all-empty, so it never renders while closed — but
    // does once the fold is open (#2006 item 4).
    expect(screen.getByText("Arc")).toBeInTheDocument();

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveTextContent("fewer fields");
  });

  it("singular: 1 more field", () => {
    // Fill everything except one field (nick).
    mount({ alias: "x", tone: "x", kin: ["lore_1"], role: "x", loyalty: "x" });
    const toggle = screen.getByTestId("rail-fold-toggle");
    expect(toggle).toHaveTextContent("1 more field");
    expect(toggle).not.toHaveTextContent("1 more fields");
  });

  it("no toggle at all when nothing is empty", () => {
    mount({ alias: "x", nick: "x", tone: "x", kin: ["lore_1"], role: "x", loyalty: "x" });
    expect(screen.queryByTestId("rail-fold-toggle")).toBeNull();
  });

  it("sticky while open: a field filled mid-edit stays inside the fold until closed", async () => {
    const props = baseProps({ tone: "x", kin: ["lore_1"], role: "x", loyalty: "x" });
    const { rerender } = render(MetadataPanel, { props: props as never });

    const toggle = screen.getByTestId("rail-fold-toggle");
    await fireEvent.click(toggle); // open — alias/nick snapshotted into the held set

    const foldBodyBefore = screen.getByTestId("rail-fold-body");
    expect(foldBodyBefore.textContent).toContain("Alias");
    const aliasRowOpen1 = screen.getByText("Alias").closest(".field-row")!;
    expect(aliasRowOpen1.classList.contains("empty")).toBe(true);
    expect(toggle).toHaveTextContent("fewer fields");

    // Fill alias while the fold stays open — it must stay INSIDE the fold
    // (sticky membership) and lose .empty, and the count line must still read
    // "fewer fields" (not jump back to a live count).
    await rerender({ ...props, metadata: { ...props.metadata, alias: "The Painted" } } as never);

    const foldBody = screen.getByTestId("rail-fold-body");
    expect(foldBody.textContent).toContain("Alias");
    const aliasRowOpen2 = screen.getByText("Alias").closest(".field-row")!;
    expect(aliasRowOpen2.closest("[data-testid='rail-fold-body']")).not.toBeNull();
    expect(aliasRowOpen2.classList.contains("empty")).toBe(false);
    expect(screen.getByTestId("rail-fold-toggle")).toHaveTextContent("fewer fields");

    // Close: Alias now renders among the known rows, outside the fold body.
    await fireEvent.click(screen.getByTestId("rail-fold-toggle"));
    expect(screen.queryByTestId("rail-fold-body")).toBeNull();
    const aliasRowClosed = screen.getByText("Alias").closest(".field-row")!;
    expect(aliasRowClosed).toBeInTheDocument();
  });
});
