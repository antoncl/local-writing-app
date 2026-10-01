// The text-choice 409 recogniser (ADR-0097 §3): attach / detach answer 409
// `text_choice_required` with both texts when they differ and no `text` was sent.
import { describe, expect, it, vi } from "vitest";
import { HttpError, request } from "./core";
import { plotApi, textChoiceConflict } from "./plot";

// Only `request` is faked, so the wire bodies the deck endpoints are sent can be read back;
// HttpError stays real for the recogniser tests below.
vi.mock("./core", async (importOriginal) => ({ ...(await importOriginal<typeof import("./core")>()), request: vi.fn(async () => ({})) }));

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

describe("deck and place requests (ADR-0097 §2, §4)", () => {
  const lastCall = () => {
    const [path, init] = vi.mocked(request).mock.calls.at(-1)!;
    return { path, method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined };
  };

  it("createDeck sends the title, an optional id (undo) and an optional parent as plot_deck", async () => {
    await plotApi.createDeck("New deck");
    expect(lastCall()).toEqual({ path: "/plot/decks", method: "POST", body: { title: "New deck" } });
    await plotApi.createDeck("Childhood", { id: "d2", parent: "d1" });
    expect(lastCall().body).toEqual({ title: "Childhood", id: "d2", plot_deck: "d1" });
  });

  it("saveDeck / deleteDeck hit the deck resource", async () => {
    await plotApi.saveDeck({ id: "d1", title: "T", body: "", revision: "r", entry_type: "plot:deck", metadata: { plot_deck: "" }, computed_metadata: {} }, "synopsis");
    expect(lastCall()).toEqual({
      path: "/plot/decks/d1",
      method: "PUT",
      body: { title: "T", body: "synopsis", metadata: { plot_deck: "" }, base_revision: "r" },
    });
    await plotApi.deleteDeck("d1");
    expect(lastCall()).toMatchObject({ path: "/plot/decks/d1", method: "DELETE" });
  });

  it("placeCard sends `to` and/or `story` untouched", async () => {
    await plotApi.placeCard("c1", { to: { deck: "d1" }, story: { after_id: "c0" } });
    expect(lastCall()).toEqual({ path: "/plot/cards/c1/place", method: "POST", body: { to: { deck: "d1" }, story: { after_id: "c0" } } });
    await plotApi.placeCard("c1", { to: { loose: true } });
    expect(lastCall().body).toEqual({ to: { loose: true } });
  });

  it("createCard carries `to` (a deck's New card), and the story rank only with an id", async () => {
    await plotApi.createCard("New card", undefined, undefined, { deck: "d1" });
    expect(lastCall().body).toEqual({ title: "New card", to: { deck: "d1" } });
    await plotApi.createCard("Back", "c9", 4);
    expect(lastCall().body).toEqual({ title: "Back", id: "c9", story_rank: 4 });
    await plotApi.createCard("Plain");
    expect(lastCall().body).toEqual({ title: "Plain" });
  });
});
