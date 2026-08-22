import { describe, it, expect } from "vitest";
import { splitInteriority, visibleExternal, INTERIORITY_MARKER } from "@/lib/editor-core/interiority";

describe("splitInteriority", () => {
  it("returns the whole text as external when there is no marker", () => {
    expect(splitInteriority("She raised the rifle.")).toEqual({
      external: "She raised the rifle.",
      internal: "",
    });
  });

  it("splits external from internal on the marker, trimming surrounding blank lines", () => {
    const text = `She raised the rifle.\n\n${INTERIORITY_MARKER}\n\nDon't let the hand shake.`;
    expect(splitInteriority(text)).toEqual({
      external: "She raised the rifle.",
      internal: "Don't let the hand shake.",
    });
  });

  it("tolerates casing and inner spacing in the marker", () => {
    const text = "Prose here.\n[[ Interiority ]]\nHidden thought.";
    expect(splitInteriority(text)).toEqual({
      external: "Prose here.",
      internal: "Hidden thought.",
    });
  });

  it("splits on the first marker only, keeping later ones inside the interiority", () => {
    const text = `Beat.\n\n${INTERIORITY_MARKER}\n\nfirst ${INTERIORITY_MARKER} second`;
    const { external, internal } = splitInteriority(text);
    expect(external).toBe("Beat.");
    expect(internal).toBe(`first ${INTERIORITY_MARKER} second`);
  });
});

describe("visibleExternal", () => {
  it("shows plain prose unchanged while no marker has arrived", () => {
    expect(visibleExternal("She raised the")).toBe("She raised the");
  });

  it("shows only the external part once the marker is complete", () => {
    const text = `She fired.\n\n${INTERIORITY_MARKER}\n\nMissing is not an option.`;
    expect(visibleExternal(text)).toBe("She fired.");
  });

  it("hides a trailing partial marker so it never flickers into the beat", () => {
    expect(visibleExternal("She fired.\n\n[[inter")).toBe("She fired.");
    expect(visibleExternal("She fired.\n\n[[")).toBe("She fired.");
  });

  it("does not trim ordinary prose that ends without a bracket", () => {
    expect(visibleExternal("She fired at noon")).toBe("She fired at noon");
  });
});
