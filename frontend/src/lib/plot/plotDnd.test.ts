import { describe, expect, it } from "vitest";
import { PLOT_DND_MIME, setPlotBeatDrag, hasPlotBeatDrag, readPlotBeatDrag } from "./plotDnd";

// A minimal DataTransfer stand-in: a backing map + a live `types` view, enough to
// exercise the set/has/read round-trip the way the browser's DnD channel behaves.
function fakeDataTransfer(): DataTransfer {
  const store: Record<string, string> = {};
  return {
    getData: (t: string) => store[t] ?? "",
    setData: (t: string, v: string) => void (store[t] = v),
    get types() {
      return Object.keys(store);
    },
    effectAllowed: "none",
    dropEffect: "none",
  } as unknown as DataTransfer;
}

function dragEvent(dataTransfer: DataTransfer | null): DragEvent {
  return { dataTransfer } as unknown as DragEvent;
}

describe("plotDnd", () => {
  it("round-trips a beat payload through the custom MIME channel", () => {
    const dt = fakeDataTransfer();
    setPlotBeatDrag(dragEvent(dt), "i1", "b1");
    expect(dt.getData(PLOT_DND_MIME)).toBe(JSON.stringify({ kind: "beat", instance: "i1", beat_id: "b1" }));
    expect(dt.getData("text/plain")).toBe("i1:b1"); // the fallback
    expect(dt.effectAllowed).toBe("copy"); // a drop CREATES a link
    expect(readPlotBeatDrag(dragEvent(dt))).toEqual({ kind: "beat", instance: "i1", beat_id: "b1" });
  });

  it("hasPlotBeatDrag reads `types` (available during dragover), true only for a beat drag", () => {
    const beatDt = fakeDataTransfer();
    setPlotBeatDrag(dragEvent(beatDt), "i1", "b1");
    expect(hasPlotBeatDrag(dragEvent(beatDt))).toBe(true);
    expect(hasPlotBeatDrag(dragEvent(fakeDataTransfer()))).toBe(false); // empty drag
  });

  it("readPlotBeatDrag returns null for a foreign / malformed payload", () => {
    const foreign = fakeDataTransfer();
    foreign.setData("text/plain", "hello");
    expect(readPlotBeatDrag(dragEvent(foreign))).toBeNull();

    const malformed = fakeDataTransfer();
    malformed.setData(PLOT_DND_MIME, "{not json");
    expect(readPlotBeatDrag(dragEvent(malformed))).toBeNull();

    const wrongKind = fakeDataTransfer();
    wrongKind.setData(PLOT_DND_MIME, JSON.stringify({ kind: "other", instance: "i", beat_id: "b" }));
    expect(readPlotBeatDrag(dragEvent(wrongKind))).toBeNull();
  });

  it("tolerates a missing dataTransfer (no throw, false / null)", () => {
    expect(hasPlotBeatDrag(dragEvent(null))).toBe(false);
    expect(readPlotBeatDrag(dragEvent(null))).toBeNull();
    setPlotBeatDrag(dragEvent(null), "i1", "b1"); // no throw
  });
});
