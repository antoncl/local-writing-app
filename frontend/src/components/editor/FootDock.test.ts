// @vitest-environment happy-dom
import { describe, it, expect, vi } from "vitest";
import { render } from "@/lib/test/component";

import FootDock from "@/components/editor/FootDock.svelte";
import { SnapshotStripController } from "@/lib/stores/snapshotStrip.svelte";
import { LoreScrubController } from "@/lib/stores/loreScrub.svelte";
import type { MutationMarkerRecord } from "@/lib/types";

// FootDock owns the ONE window keydown handler for both time-axes (ADR-0088 §4).
// These pin the dispatch and the mode switch: ← / → drive the CURRENT track, Esc
// returns it to its editable end, A/S/B are snapshots-only, `m` cycles the mode
// AND resets the outgoing axis (the structural collision-dissolve), and a
// mutation-less node shows no control and stays on snapshots. Every controller
// method the handler calls is spied, so no real fetch/render runs.

function marker(over: Partial<MutationMarkerRecord>): MutationMarkerRecord {
  return {
    marker_id: "m",
    entity_id: "e",
    field: "title",
    op: "replace",
    value: "v",
    name: "",
    group: "",
    unit_id: "",
    unit_name: "",
    scene_id: "s",
    offset: 0,
    line: 0,
    scene_path: "",
    ...over,
  };
}

function scrubWithMutations(): LoreScrubController {
  const scrub = new LoreScrubController();
  scrub.markers = [marker({ unit_id: "u1" }), marker({ unit_id: "u2" })]; // units.length = 2
  return scrub;
}

/** Dispatch a window-bound keydown whose target is inside the dock (so the
 *  editable-end focus gate passes), the way a real press from the pane would. */
function press(container: HTMLElement, key: string, opts: KeyboardEventInit = {}): void {
  const dock = container.querySelector(".foot-dock");
  if (!dock) throw new Error("no .foot-dock mounted");
  dock.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...opts }));
}

function mount(scrub: LoreScrubController) {
  const snapshots = new SnapshotStripController();
  const spies = {
    snapStep: vi.spyOn(snapshots, "step").mockImplementation(() => {}),
    park: vi.spyOn(snapshots, "park").mockResolvedValue(),
    toggleView: vi.spyOn(snapshots, "toggleView").mockImplementation(() => {}),
    setView: vi.spyOn(snapshots, "setView").mockImplementation(() => {}),
    scrubStep: vi.spyOn(scrub, "step").mockImplementation(() => {}),
    scrubTo: vi.spyOn(scrub, "scrubTo").mockResolvedValue(),
  };
  const { container } = render(FootDock, {
    props: { snapshots, scrub, documentKind: "lore", writesLabel: null },
  });
  return { container, spies };
}

describe("FootDock — unified keyboard + mode switch (ADR-0088 S2)", () => {
  it("drives the snapshot track by default", () => {
    const { container, spies } = mount(scrubWithMutations());

    press(container, "ArrowLeft");
    expect(spies.snapStep).toHaveBeenCalledWith(-1);
    press(container, "ArrowRight");
    expect(spies.snapStep).toHaveBeenCalledWith(1);
    press(container, "a");
    expect(spies.toggleView).toHaveBeenCalledWith("now");
    press(container, "s");
    expect(spies.toggleView).toHaveBeenCalledWith("was");
    press(container, "b");
    expect(spies.setView).toHaveBeenCalledWith("both");
    press(container, "Escape");
    expect(spies.park).toHaveBeenCalledWith(null);
    // The mutation axis was never touched while snapshots had the track.
    expect(spies.scrubStep).not.toHaveBeenCalled();
  });

  it("cycles to mutations with `m`, resetting the snapshot axis to Live", () => {
    const { container, spies } = mount(scrubWithMutations());

    press(container, "m"); // snapshots → mutations
    expect(spies.park).toHaveBeenCalledWith(null); // outgoing axis reset to its editable end
    expect(container.querySelector(".mode-control")).not.toBeNull();

    // Now the arrows step the mutation stops and Esc returns to base.
    press(container, "ArrowLeft");
    expect(spies.scrubStep).toHaveBeenCalledWith(-1);
    press(container, "Escape");
    expect(spies.scrubTo).toHaveBeenCalledWith(0);

    // A/S/B are ABSENT in mutations mode — a stop has nothing to compare (§4).
    spies.toggleView.mockClear();
    spies.setView.mockClear();
    press(container, "a");
    press(container, "b");
    expect(spies.toggleView).not.toHaveBeenCalled();
    expect(spies.setView).not.toHaveBeenCalled();
    expect(spies.snapStep).not.toHaveBeenCalled(); // snapshots untouched in this mode
  });

  it("cycles back to snapshots with `m`, resetting the mutation axis to base", () => {
    const { container, spies } = mount(scrubWithMutations());

    press(container, "m"); // → mutations
    spies.scrubTo.mockClear();
    press(container, "m"); // → snapshots, resets the mutation axis
    expect(spies.scrubTo).toHaveBeenCalledWith(0);

    // Back on snapshots, the arrows drive snapshots again.
    press(container, "ArrowLeft");
    expect(spies.snapStep).toHaveBeenCalledWith(-1);
  });

  it("shows no mode control and ignores `m` when there are no mutations", () => {
    const { container, spies } = mount(new LoreScrubController()); // no markers → units.length 0

    expect(container.querySelector(".mode-control")).toBeNull();
    press(container, "m"); // no second timeline to cycle to
    expect(spies.park).not.toHaveBeenCalled();
    // The single track still answers the keys — exactly ADR-0044's strip.
    press(container, "ArrowLeft");
    expect(spies.snapStep).toHaveBeenCalledWith(-1);
    expect(spies.scrubStep).not.toHaveBeenCalled();
  });

  it("ignores a key typed outside the dock at the editable end", () => {
    // The load-bearing gate: at rest (nothing parked/scrubbed) a plain key typed
    // elsewhere in the pane must NOT move the track (the #409 daily-bug guard).
    const { spies } = mount(scrubWithMutations());
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "a", bubbles: true }));
    expect(spies.snapStep).not.toHaveBeenCalled();
    expect(spies.toggleView).not.toHaveBeenCalled();
    expect(spies.scrubStep).not.toHaveBeenCalled();
  });

  it("follows the engaged axis: shows mutations when scrubbed, even without cycling", () => {
    // The rail timeline can engage the mutation axis (scrub.index>0) outside the
    // dock; the dock must then show the mutation track, never a parked-snapshot
    // strip, so scrubbed and snapshotParked can't present at once.
    const scrub = scrubWithMutations();
    scrub.index = 1;
    const { container } = mount(scrub);
    expect(container.querySelector(".mutation-scrubber-strip")).not.toBeNull();
    expect(container.querySelector(".snapshot-strip")).toBeNull();
  });

  it("requires focus in the dock for the mutations track even at a stop (ADR-0095 §8: a stop is now editable)", () => {
    // The old "engaged frees the whole keyboard" bypass (ADR-0088 §4) is gone
    // for the mutations track: a stop's fields are live now, so a key typed on
    // a focused rail field/button must not scrub the card out from under it.
    const scrub = scrubWithMutations();
    scrub.index = 1; // at a stop
    const { spies } = mount(scrub);
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect(spies.scrubStep).not.toHaveBeenCalled();
    expect(spies.scrubTo).not.toHaveBeenCalled();
  });

  it("still answers the keys with focus inside the dock at a stop", () => {
    const scrub = scrubWithMutations();
    scrub.index = 1;
    const { container, spies } = mount(scrub);
    press(container, "ArrowLeft");
    expect(spies.scrubStep).toHaveBeenCalledWith(-1);
  });

  it("refocuses the mode control after a cycle so the keyboard stays alive", () => {
    // Cycling unmounts the focused track (a clicked notch/bead) and would drop
    // focus to <body>, stranding the keys behind the editable-end gate. The
    // cycle moves focus to the persistent mode control instead (ADR §4).
    const { container } = mount(scrubWithMutations());
    press(container, "m");
    const modeControl = container.querySelector(".mode-control");
    expect(modeControl).not.toBeNull();
    expect(document.activeElement).toBe(modeControl);
  });
});
