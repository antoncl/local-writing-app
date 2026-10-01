// The text-choice 409 recogniser (ADR-0097 §3): attach / detach answer 409
// `text_choice_required` with both texts when they differ and no `text` was sent.
import { describe, expect, it } from "vitest";
import { HttpError } from "./core";
import { textChoiceConflict } from "./plot";

const conflict = (status: number, detail: unknown) => new HttpError("differ", status, detail);

describe("textChoiceConflict", () => {
  it("reads both texts off the 409 detail", () => {
    const error = conflict(409, {
      message: "differ",
      code: "text_choice_required",
      scene_summary: "The scene's",
      card_synopsis: "The card's",
    });
    expect(textChoiceConflict(error)).toEqual({ sceneSummary: "The scene's", cardSynopsis: "The card's" });
  });

  it("is null for any other 409, other status, plain-string detail, or non-HttpError", () => {
    expect(textChoiceConflict(conflict(409, "This card already has a scene; detach it first."))).toBeNull();
    expect(textChoiceConflict(conflict(409, { message: "x", code: "other" }))).toBeNull();
    expect(textChoiceConflict(conflict(422, { code: "text_choice_required" }))).toBeNull();
    expect(textChoiceConflict(new Error("boom"))).toBeNull();
    expect(textChoiceConflict(null)).toBeNull();
  });
});
