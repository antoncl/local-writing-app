// restoredBodyTab (#2013) — pins the reopen rule NodeEditor applies on a
// node switch: a remembered LIST tab only wins if it still names a real tab
// on the current strip; everything else falls back to "body".
import { describe, expect, it } from "vitest";
import { restoredBodyTab } from "./bodyTabRestore";
import type { BodyTab } from "./bodyTabs";

const TABS: BodyTab[] = [
  { id: "body", kind: "body", label: "Body", fieldIds: [] },
  { id: "list:kin", kind: "list", label: "Kin", fieldIds: ["kin"] },
];

describe("restoredBodyTab", () => {
  it("a remembered list tab still present on the strip is restored", () => {
    expect(restoredBodyTab("list:kin", TABS)).toBe("list:kin");
  });

  it("a remembered list tab whose field is gone falls back to body", () => {
    expect(restoredBodyTab("list:allies", TABS)).toBe("body");
  });

  it("a remembered 'body' tab stays body", () => {
    expect(restoredBodyTab("body", TABS)).toBe("body");
  });

  it("nothing remembered falls back to body", () => {
    expect(restoredBodyTab(undefined, TABS)).toBe("body");
  });

  it("falls back to body when the strip is empty", () => {
    expect(restoredBodyTab("list:kin", [])).toBe("body");
  });
});
