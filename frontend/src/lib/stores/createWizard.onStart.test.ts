import { describe, expect, it, vi } from "vitest";

// #2448: the AI step shows the MACHINE roster, which nothing else keeps current
// before the first machine-layer write — so every wizard start must ask the
// host to load it.
vi.mock("@/lib/api", () => ({ api: {} }));

import { createWizard } from "@/lib/stores/createWizard.svelte";

describe("createWizard.start", () => {
  it("fires onStart so the host loads the machine roster", () => {
    const onStart = vi.fn();
    createWizard.onStart = onStart;
    createWizard.start();
    expect(onStart).toHaveBeenCalledTimes(1);
    createWizard.close();
  });
});
