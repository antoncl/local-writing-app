// @vitest-environment happy-dom
// #2438: MetadataPanel tags each write of an open field with that edit
// session's id, so the rail undo collapses one session's keystrokes into one
// step; a reopen starts a new session, and a one-click change (the reset mark)
// carries none.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import MetadataPanel from "./MetadataPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { MetadataSchema } from "@/lib/types";

const SCHEMA = {
  version: 1,
  entry_types: { "lore:character": { name: "Character", kind: "lore", fields: ["alias"] } },
  fields: { alias: { name: "Alias", type: "text" } },
} as unknown as MetadataSchema;

beforeEach(() => metadataSchemaStore.set(SCHEMA));

function mount() {
  const onMetadataChange = vi.fn();
  render(MetadataPanel, {
    props: {
      entryType: "lore:character",
      status: "",
      metadata: { alias: "Mi" },
      documentKind: "lore",
      documentLabel: "Entry",
      documentEntryTypes: [["lore:character", SCHEMA.entry_types["lore:character"]]] as never,
      metadataFieldIds: ["alias"],
      onMetadataChange,
    },
  });
  return { onMetadataChange };
}

async function typeInAlias(text: string) {
  await fireEvent.click(screen.getByRole("button", { name: /^Edit Alias/ }));
  const input = screen.getByDisplayValue("Mi") as HTMLInputElement;
  await fireEvent.input(input, { target: { value: text } });
}

describe("MetadataPanel — edit-session ids for rail undo (#2438)", () => {
  it("tags writes of an open field with its session; a reopen gets a new one", async () => {
    const { onMetadataChange } = mount();
    await typeInAlias("Mia");
    const first = onMetadataChange.mock.calls.at(-1)!;
    expect(first[0]).toEqual({ alias: "Mia" });
    expect(first[1]).toMatch(/^alias#\d+$/);

    await fireEvent.keyDown(screen.getByDisplayValue("Mia"), { key: "Escape" });
    await typeInAlias("Mira");
    const second = onMetadataChange.mock.calls.at(-1)!;
    expect(second[1]).toMatch(/^alias#\d+$/);
    expect(second[1]).not.toBe(first[1]);
  });

  it("a reset-mark clear carries no session", async () => {
    const { onMetadataChange } = mount();
    await fireEvent.click(screen.getByRole("button", { name: "Reset Alias to default" }));
    const [next, session] = onMetadataChange.mock.calls.at(-1)!;
    expect(next).toEqual({});
    expect(session).toBeUndefined();
  });
});
