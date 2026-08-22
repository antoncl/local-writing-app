import { describe, expect, it } from "vitest";

import { formatChatRosterDetail } from "@/lib/utils/chatRoster";

describe("formatChatRosterDetail", () => {
  it("uses the singular for exactly 1 message", () => {
    expect(formatChatRosterDetail(1, "2026-08-22T14:30:59.123Z")).toMatch(/^1 message ·/);
  });

  it("uses the plural for 0 or more than 1 message", () => {
    expect(formatChatRosterDetail(0, "2026-08-22T14:30:59.123Z")).toMatch(/^0 messages ·/);
    expect(formatChatRosterDetail(2, "2026-08-22T14:30:59.123Z")).toMatch(/^2 messages ·/);
  });

  it("slices the timestamp to minutes, swapping T for a space", () => {
    expect(formatChatRosterDetail(3, "2026-08-22T14:30:59.123Z")).toContain("2026-08-22 14:30");
  });
});
