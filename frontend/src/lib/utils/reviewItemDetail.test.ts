import { describe, expect, it } from "vitest";
import { reviewItemSourceDetail } from "./reviewItemDetail";

describe("reviewItemSourceDetail", () => {
  it("names a change-candidate route with the 'from' grammar", () => {
    expect(
      reviewItemSourceDetail(
        { node_id: "a", snapshot_id: "", reason: "references_source", marker_id: "" },
        "Kaela Voss",
      ),
    ).toBe("refers to the change · from Kaela Voss");
  });

  it("reads a follow_up source as 'follow-up from <title>' (ADR-0099 §4)", () => {
    expect(
      reviewItemSourceDetail(
        { node_id: "a", snapshot_id: "", reason: "follow_up", marker_id: "" },
        "Kaela Voss",
      ),
    ).toBe("follow-up from Kaela Voss");
  });
});
