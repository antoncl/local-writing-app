// @vitest-environment happy-dom
// BacklinksPanel displays data (incoming references) and had no test — a display
// surface needs a mount test asserting rows render (#642/#724). The #49 runes
// port also turns the `navigate` CustomEvent into an `onNavigate` callback prop;
// the second test locks that the navigation target still reaches the parent.
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/lib/test/component";
import BacklinksPanel from "./BacklinksPanel.svelte";
import { metadataSchemaStore } from "@/lib/stores/schema";
import type { Backlink } from "@/lib/types";

function backlink(over: Partial<Backlink> = {}): Backlink {
  return {
    id: "lore_1",
    title: "Mira",
    kind: "lore",
    entry_type: "lore:character",
    field_id: "field_pov",
    field_name: "POV",
    ...over,
  };
}

// Null schema is a valid state (schema not yet loaded); the type pill then falls
// back to the raw entry_type, so it never collides with a row's title text.
afterEach(() => metadataSchemaStore.set(null));

describe("BacklinksPanel", () => {
  it("renders the reference roster with its count (a display pane's mount test)", () => {
    render(BacklinksPanel, {
      props: {
        backlinks: [
          backlink(),
          backlink({ id: "lore_2", title: "Jonas", field_id: "field_ally" }),
        ],
      },
    });
    expect(screen.getByText("References")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument(); // the count pill
  });

  it("reports the navigation target through onNavigate (runes port of the `navigate` event)", async () => {
    const onNavigate = vi.fn();
    render(BacklinksPanel, { props: { backlinks: [backlink()], onNavigate } });
    // Collapsed by default — expand the group to reveal the rows, then click one.
    // onNavigate carries targetId (the real node id), not the composite row key.
    await fireEvent.click(screen.getByText("References"));
    await fireEvent.click(screen.getByText("Mira"));
    expect(onNavigate).toHaveBeenCalledWith({ id: "lore_1", kind: "lore" });
  });
});
